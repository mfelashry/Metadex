"""Assemble one local report. Hidden data, activity, and device health stay separate."""
import hashlib
import io
import time
from datetime import datetime, timezone

from PIL import Image, UnidentifiedImageError

from app.activity import correlate
from app.indicators import appended_report, lsb_report, metadata_report, shannon_entropy
from app.metadata_messages import metadata_messages
from app.recovery import recover
from app.scoring import score_rules
from app.sensors import assess
from app.structure import parse_container

EXTENSIONS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".jpe": "JPEG",
    ".jfif": "JPEG",
    ".png": "PNG",
    ".bmp": "BMP",
    ".dib": "BMP",
}

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

LIMITATIONS = (
    "Hidden-data checks cover appended bytes, EXIF, JPEG comment and PNG text metadata, two LSB heuristics on PNG and BMP, "
    "an extension check, and four supported recovery layouts (appended bytes, metadata text, selected PNG text keys, TECHSTEG1). "
    "Base64 and hex are decoded only when they become readable text. XMP is not parsed. "
    "Encrypted payloads and unknown steganography stay unread. A clear result does not mean the file is clean. "
    "Activity correlation requires events the analyst supplies and can only link filename, host, process, and time. "
    "It cannot identify a sender or prove the image caused a connection. "
    "Sensor thresholds are demonstration values for device health, not intrusion detections."
)


class AnalysisError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def analyze_bytes(data: bytes, filename: str | None, events, sensors) -> dict:
    intake_sha256 = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_BYTES:
        strain = _strain(len(data), None, None, rejected=True, reason="Image exceeds the 10 MiB limit")
        raise AnalysisError(413, _error("Image exceeds the 10 MiB limit", sensors, strain))
    if not data:
        raise AnalysisError(400, _error("Empty image", sensors, _strain(0, None, None, rejected=True, reason="Empty upload")))
    fmt = _signature(data)
    if fmt is None:
        raise AnalysisError(
            415,
            _error("Only PNG, JPEG, and BMP signatures are supported", sensors, _strain(len(data), None, None, rejected=True, reason="Unsupported signature")),
        )
    started = time.perf_counter()
    try:
        with Image.open(io.BytesIO(data)) as check:
            if check.format != fmt or check.width * check.height > MAX_PIXELS:
                raise ValueError("Format mismatch or image dimensions exceed the limit")
            check.verify()
        with Image.open(io.BytesIO(data)) as decoded:
            decoded.load()
            width, height = decoded.size
            if width * height > MAX_PIXELS:
                raise ValueError("Image dimensions exceed the limit")
            structure = parse_container(data, fmt)
            end = structure["end"]
            meta = metadata_report(decoded, fmt, structure)
            messages = metadata_messages(decoded, fmt, data, structure)
            lsb = lsb_report(decoded, fmt)
            recovered = recover(data, fmt, decoded, end, messages)
            mode = decoded.mode
    except AnalysisError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        strain = _strain(len(data), None, None, rejected=True, reason="Malformed or unsafe image")
        raise AnalysisError(422, _error("Malformed or unsafe image", sensors, strain)) from exc
    decode_ms = round((time.perf_counter() - started) * 1000, 2)
    pixel_count = width * height
    strain = _strain(len(data), pixel_count, decode_ms, rejected=False, reason=None)
    appended = appended_report(data, end, structure["rule"])
    activity = correlate(events, filename or "")
    device = assess(sensors, strain)
    entropy = {
        "file": round(shannon_entropy(data), 3),
        "body": round(shannon_entropy(data[:end]), 3),
        "trailer": round(shannon_entropy(data[end:]), 3) if end < len(data) else None,
    }
    extension = extension_check(filename, fmt)
    rules = _rules(structure, meta, appended, lsb, recovered, activity, device, messages, extension)
    pixel_message = any(
        p["method"] == "rgb_lsb_techsteg1" and (p.get("content") or {}).get("status") == "decoded"
        for p in recovered.get("payloads", [])
    )
    suspicion = score_rules(rules, messages.get("top_weight", 0), pixel_message)
    hidden_hits = [rule for rule in rules if rule["domain"] == "hidden_data" and rule["result"] in ("indicator", "recovered")]
    hidden_status = "indicators_found" if hidden_hits else "no_indicator_found"
    conclusions = {
        "hidden_data": {
            "status": hidden_status,
            "headline": "Hidden-data indicators found" if hidden_hits else "No hidden-data indicators found",
            "indicator_count": len(hidden_hits),
            "statement": "Image-only. This does not establish malicious intent or identify a sender.",
        },
        "activity": {
            "status": activity["status"],
            "headline": activity["headline"],
            "statement": "Based only on the events submitted with this request.",
        },
        "device_health": {
            "status": device["status"],
            "headline": device["headline"],
            "statement": "Observed device condition. Not an attack verdict.",
        },
    }
    fileinfo = {
        "filename": filename,
        "format": fmt,
        "media_type": {"PNG": "image/png", "JPEG": "image/jpeg", "BMP": "image/bmp"}[fmt],
        "size_bytes": len(data),
        "width": width,
        "height": height,
        "mode": mode,
        "bit_depth": structure.get("header", {}).get("bit_depth"),
        "pixel_count": pixel_count,
        "sha256": intake_sha256,
        "sha1": hashlib.sha1(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "extension_check": extension,
        "decode_ms": decode_ms,
        "limits": {
            "max_bytes": MAX_BYTES,
            "max_pixels": MAX_PIXELS,
            "bytes_ratio": strain["bytes_ratio"],
            "pixel_ratio": strain["pixel_ratio"],
        },
    }
    after_sha256 = hashlib.sha256(data).hexdigest()
    integrity = {
        "sha256_at_intake": intake_sha256,
        "sha256_after_analysis": after_sha256,
        "unchanged": intake_sha256 == after_sha256,
        "method": "memory",
        "statement": (
            "The bytes were hashed when they arrived and again after every check ran. Matching hashes show the analysis did not alter them. "
            "This cannot show whether the file was changed before it reached this tool."
        ),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_version": "stillframe-2",
        "file": fileinfo,
        "integrity": integrity,
        "suspicion": suspicion,
        "messages_found": collect_messages(recovered),
        "conclusions": conclusions,
        "image_analysis": {
            "structure": {
                "status": "anomaly" if structure["anomalies"] else "consistent",
                "parser": structure["parser"],
                "rule": structure["rule"],
                "structure_end_offset": end,
                "file_size": len(data),
                "trailing_bytes": len(data) - end,
                "anomalies": structure["anomalies"],
                "rows": structure["rows"],
                "header": structure["header"],
                "note": "The container ended before the file ended." if end < len(data) else "The container end and the file end agree.",
            },
            "metadata": meta,
            "metadata_messages": messages,
            "appended_data": appended,
            "lsb": lsb,
            "entropy": entropy,
        },
        "recovery": recovered,
        "activity_correlation": activity,
        "sensor_assessment": device,
        "rules": rules,
        "findings": [rule for rule in rules if rule["result"] not in ("clear", "info", "not_assessed", "not_applicable")],
        "attack_context": _context(activity),
        "summary": _summary(conclusions),
        "narrative": _narrative(conclusions, recovered, activity, device, messages),
        "limitations": LIMITATIONS,
    }
    return report


def parse_events(raw: str | None):
    return _parse_json_list(raw, "activity_events")


def parse_sensors(raw: str | None):
    return _parse_json_list(raw, "sensor_samples")


def object_list(value, name: str):
    if value is None:
        return None
    import json

    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, dict) for item in value):
        raise AnalysisError(422, {"message": f"{name} must be a JSON array of at most 100 objects (100 KB)"})
    if len(json.dumps(value)) > 100_000:
        raise AnalysisError(422, {"message": f"{name} must be a JSON array of at most 100 objects (100 KB)"})
    return value


def decode_image_b64(raw: str) -> bytes:
    import base64
    import binascii

    if not raw or not str(raw).strip():
        raise AnalysisError(400, {"message": "Empty image"})
    text = raw.strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AnalysisError(422, {"message": "image_base64 must be standard base64"}) from exc


def _parse_json_list(raw: str | None, name: str):
    if raw is None or raw == "":
        return None
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisError(422, {"message": f"{name} must be a JSON array of at most 100 objects (100 KB)"}) from exc
    if not isinstance(value, list) or len(value) > 100 or len(raw) > 100_000 or any(not isinstance(item, dict) for item in value):
        raise AnalysisError(422, {"message": f"{name} must be a JSON array of at most 100 objects (100 KB)"})
    return value


METHOD_WORDS = {
    "appended_bytes": "bytes after the end of the image",
    "metadata_text": "metadata text",
    "png_text_chunk": "PNG text chunk",
    "rgb_lsb_techsteg1": "pixel least significant bits (TECHSTEG1)",
}


def _signature_detail(signature: dict, listing: list | None) -> str:
    text = f"The extra bytes start with a {signature['type']} signature, so a second file is hidden after the image."
    if listing:
        names = ", ".join(f"{item['name']} ({item['size_bytes']} bytes)" for item in listing[:5])
        text += f" Archive lists: {names}. Not extracted."
    return text


def collect_messages(recovered: dict) -> list:
    """Every readable message the recovery step produced, one entry per distinct text."""
    out = []
    by_text: dict = {}
    for payload in recovered.get("payloads", []):
        content = payload.get("content") or {}
        text = content.get("message")
        if content.get("status") != "decoded" or not text:
            continue
        where = METHOD_WORDS.get(payload["method"], payload["method"])
        if payload["method"] in ("metadata_text", "png_text_chunk"):
            where = payload["detail"]
        if text in by_text:
            by_text[text]["also_in"].append(where)
            continue
        item = {
            "method": payload["method"],
            "where": where,
            "encoding": content.get("encoding", "utf-8"),
            "text": text,
            "also_in": [],
        }
        by_text[text] = item
        out.append(item)
    return out


def extension_check(filename: str | None, fmt: str) -> dict:
    """Compare the name's extension with the format the bytes actually have."""
    if not filename:
        return {"status": "not_applicable", "extension": None, "expected_format": None, "actual_format": fmt, "detail": "No filename was supplied."}
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    expected = EXTENSIONS.get(ext)
    if expected == fmt:
        return {"status": "match", "extension": ext, "expected_format": expected, "actual_format": fmt, "detail": f"Extension {ext} matches the {fmt} bytes."}
    if expected:
        detail = f"Named {ext} but the bytes are a {fmt} image."
    elif ext:
        detail = f"Named {ext}, which is not an image extension, but the bytes are a {fmt} image."
    else:
        detail = f"No extension, but the bytes are a {fmt} image."
    return {"status": "mismatch", "extension": ext or None, "expected_format": expected, "actual_format": fmt, "detail": detail}


def _signature(data: bytes):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"BM"):
        return "BMP"
    return None


def _strain(size: int, pixels, decode_ms, rejected: bool, reason: str | None) -> dict:
    byte_ratio = round(size / MAX_BYTES, 6) if MAX_BYTES else None
    pixel_ratio = round(pixels / MAX_PIXELS, 6) if pixels is not None else None
    near = bool((byte_ratio is not None and byte_ratio >= 0.8) or (pixel_ratio is not None and pixel_ratio >= 0.8))
    return {
        "rejected": rejected,
        "reason": reason,
        "size_bytes": size,
        "max_bytes": MAX_BYTES,
        "pixel_count": pixels,
        "max_pixels": MAX_PIXELS,
        "bytes_ratio": byte_ratio,
        "pixel_ratio": pixel_ratio,
        "decode_ms": decode_ms,
        "near_limit": near,
    }


def _error(message: str, sensors, strain: dict) -> dict:
    safe_sensors = sensors if isinstance(sensors, list) else None
    return {"message": message, "device_health": assess(safe_sensors, strain), "strain": strain}


def _rules(structure, meta, appended, lsb, recovered, activity, device, messages=None, extension=None) -> list:
    rules = [
        _rule("SF-STRUCT-001", "Container end", "structure", "info", structure["rule"]),
        _rule(
            "SF-STRUCT-002",
            "Structure integrity",
            "structure",
            "anomaly" if structure["anomalies"] else "clear",
            "; ".join(structure["anomalies"]) if structure["anomalies"] else "Checksums and required headers held.",
        ),
        _rule(
            "SF-APP-001",
            "Appended bytes",
            "hidden_data",
            "indicator" if appended["status"] == "indicator" else "clear",
            f"{appended['evidence']['trailing_bytes']:,} extra bytes found after the end of the image."
            if appended["status"] == "indicator"
            else "File ends where the container ends.",
        ),
    ]
    signature = appended["evidence"].get("embedded_signature")
    rules.append(
        _rule(
            "SF-MAG-001",
            "Trailer file signature",
            "hidden_data",
            "indicator" if signature else "clear",
            _signature_detail(signature, appended["evidence"].get("archive_listing"))
            if signature
            else "No recognized file signature at the start of the trailer.",
        )
    )
    rules.append(
        _rule(
            "SF-ENT-001",
            "Trailer entropy",
            "hidden_data",
            "indicator" if appended["evidence"].get("high_entropy") else "clear",
            "Trailer entropy is at least 7.5 bits/byte over 64 bytes or more. Consistent with compressed or encrypted bytes. Not decrypted."
            if appended["evidence"].get("high_entropy")
            else "Trailer is absent or not high-entropy.",
        )
    )
    lsb_result = {"indicator": "indicator", "no_indicator_found": "clear", "not_applicable": "not_applicable"}[lsb["status"]]
    rules.append(_rule("SF-LSB-001", "LSB bias and pair uniformity", "hidden_data", lsb_result, _lsb_detail(lsb)))
    carrier = meta["status"] == "clue" and any("carrier" in c or "unusually long" in c or "COM segment" in c for c in meta["evidence"]["clues"])
    rules.append(
        _rule(
            "SF-META-001",
            "Metadata carriers",
            "hidden_data",
            "indicator" if carrier else "clear",
            "A metadata field matches a known text carrier or is unusually long." if carrier else "No oversized or known-carrier metadata field.",
        )
    )
    messages = messages or {"status": "not_applicable", "fields": []}
    flagged = [f for f in messages.get("fields", []) if f.get("flagged")]
    if messages["status"] == "not_applicable":
        meta_result, meta_detail = "not_applicable", messages.get("explanation", "")
    elif flagged:
        top = max(flagged, key=lambda f: f["weight"])
        meta_result = "indicator"
        meta_detail = top["reason"]
        if top.get("decoded") and top.get("encoding") != "plain":
            meta_detail += f" Decoded: “{top['decoded'][:120]}”"
        elif top.get("decoded"):
            meta_detail += f" Text: “{top['decoded'][:120]}”"
        if len(flagged) > 1:
            meta_detail += f" ({len(flagged)} fields flagged.)"
    else:
        meta_result, meta_detail = "clear", "No message, encoding, or unusual length in the metadata text fields."
    rules.append(_rule("SF-META-002", "Metadata message", "hidden_data", meta_result, meta_detail))
    extension = extension or {"status": "not_applicable", "detail": "No filename was supplied."}
    ext_result = {"match": "clear", "mismatch": "indicator", "not_applicable": "not_applicable"}[extension["status"]]
    rules.append(_rule("SF-TYPE-001", "Extension matches content", "hidden_data", ext_result, extension["detail"]))
    readable_methods = list(
        dict.fromkeys(
            p["method"] for p in recovered.get("payloads", []) if (p.get("content") or {}).get("status") == "decoded"
        )
    )
    if readable_methods:
        rec_result = "recovered"
        rec_detail = "Readable hidden content recovered from: " + ", ".join(METHOD_WORDS.get(m, m) for m in readable_methods) + "."
    elif recovered["methods_found"]:
        rec_result = "clear"
        rec_detail = "Hidden bytes were located but are not readable text (binary, possibly compressed or encrypted). Not decrypted."
    else:
        rec_result = "clear"
        rec_detail = "No supported layout was present."
    rules.append(_rule("SF-REC-001", "Supported-layout recovery", "hidden_data", rec_result, rec_detail))
    activity_result = {"correlated": "correlated", "partial": "partial", "no_indicator_found": "clear", "not_assessed": "not_assessed"}[
        activity["status"]
    ]
    rules.append(_rule("SF-ACT-001", "Arrival, read, outbound", "activity", activity_result, activity["explanation"]))
    temp = any(item["condition"] == "Elevated temperature" for item in device["observations"])
    motion = any(item["condition"] == "Large acceleration" for item in device["observations"])
    if device["status"] == "not_assessed":
        temp_result = motion_result = "not_assessed"
    else:
        temp_result = "observed" if temp else "clear"
        motion_result = "observed" if motion else "clear"
    rules.append(_rule("SF-DEV-001", "CPU or battery temperature", "device", temp_result, "Demonstration threshold 85 °C. Device condition only."))
    rules.append(_rule("SF-DEV-002", "Accelerometer", "device", motion_result, "Demonstration threshold magnitude 30. Device condition only."))
    rules.append(
        _rule(
            "SF-STRAIN-001",
            "Scanner budget",
            "device",
            "info",
            device["strain"].get("note") or "",
        )
    )
    return rules


def _rule(rule_id: str, name: str, domain: str, result: str, detail: str) -> dict:
    return {"id": rule_id, "name": name, "domain": domain, "result": result, "detail": detail}


def _lsb_detail(lsb: dict) -> str:
    if lsb["status"] == "not_applicable":
        return lsb["explanation"]
    evidence = lsb["evidence"]
    pair = evidence.get("pair_test") or {}
    if lsb["status"] == "indicator":
        lead = []
        if evidence.get("pair_indicator"):
            lead.append(
                f"Pixel color values come in suspiciously even pairs (score {pair.get('chi_square_per_df')}, "
                f"normal photos are well above {pair.get('threshold_per_df')}). That is the pattern hiding data in the last bit of each pixel leaves behind."
            )
        if evidence.get("bias_indicator"):
            lead.append(
                f"The last bit of the pixels leans heavily to one side (z {evidence.get('bias_z_score')}, threshold {evidence.get('bias_threshold')})."
            )
        return " ".join(lead) + " Statistics alone cannot read the content."
    return (
        f"Sampled bits {evidence.get('sampled_bits')}, one-fraction {evidence.get('one_fraction')}, "
        f"bias z {evidence.get('bias_z_score')} against {evidence.get('bias_threshold')}. "
        f"Pair chi-square/df {pair.get('chi_square_per_df', 'n/a')} against {pair.get('threshold_per_df', 'n/a')}. "
        + lsb["explanation"]
    )


def _context(activity: dict) -> list:
    items = [
        {
            "technique": "T1027.003",
            "name": "Steganography",
            "url": "https://attack.mitre.org/techniques/T1027/003/",
            "role": "Hypothesis for hiding a payload or command in an image. An image finding can support the hypothesis. It cannot confirm intent.",
        }
    ]
    if activity.get("sequence") and any(step["role"] == "outbound" for step in activity["sequence"]["steps"]):
        items.append(
            {
                "technique": "T1071",
                "name": "Application Layer Protocol",
                "url": "https://attack.mitre.org/techniques/T1071/",
                "role": "Context for the outbound event in the correlated sequence. Naming the technique does not identify the protocol payload or the operator.",
            }
        )
    return items


def _summary(conclusions: dict) -> str:
    return " · ".join(
        [
            conclusions["hidden_data"]["headline"],
            conclusions["activity"]["headline"],
            conclusions["device_health"]["headline"],
        ]
    )


def _narrative(conclusions, recovered, activity, device, messages=None) -> str:
    parts = []
    found = collect_messages(recovered)
    if found:
        first = found[0]
        more = f" {len(found) - 1} more message(s) recovered." if len(found) > 1 else ""
        parts.append(f"Message recovered from {first['where']} ({first['encoding']}): “{first['text'][:160]}”.{more}")
    if conclusions["hidden_data"]["status"] == "indicators_found":
        methods = ", ".join(recovered["methods_found"]) or "statistical indicators"
        parts.append(
            f"Hidden-data indicators found ({conclusions['hidden_data']['indicator_count']} rules). Supported recovery hit: {methods}."
            if recovered["methods_found"]
            else f"Hidden-data indicators found ({conclusions['hidden_data']['indicator_count']} rules). No supported layout could be read as text."
        )
    else:
        parts.append("No hidden-data indicators found. That is not a proof that the file is clean.")
    if activity["status"] == "correlated":
        handoff = (activity.get("sequence") or {}).get("handoff")
        parts.append("Activity correlated. " + (handoff + ". " if handoff else "") + "The outbound step is the same process that read the file. This is not attribution.")
    elif activity["status"] == "partial":
        parts.append("Activity shows filename overlap only. The full arrival, read, and outbound sequence is not in the submitted events.")
    elif activity["status"] == "not_assessed":
        parts.append("Activity was not assessed. No host events were submitted.")
    else:
        parts.append("No related activity. None of the submitted events name this file.")
    if device["status"] == "condition_observed":
        labels = ", ".join(item["condition"].lower() for item in device["observations"])
        parts.append(f"Observed device condition ({labels}). {device['strain'].get('note', '')} This is not an attack verdict.")
    elif device["status"] == "not_assessed":
        parts.append("Device health was not assessed. No readings were submitted, and this machine was not sampled.")
    else:
        parts.append("No device condition noted in the submitted readings. " + (device["strain"].get("note") or ""))
    return " ".join(part.strip() for part in parts if part)
