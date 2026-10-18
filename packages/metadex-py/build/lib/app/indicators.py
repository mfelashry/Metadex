"""Image-only heuristics. None of these establish intent or authorship."""
import hashlib
import math

STEGO_TEXT_KEYS = {"comment", "description", "message", "payload", "stego"}

# Longer signatures only. Two-byte tags such as MZ are matched only at the start.
PREFIX_SIGNATURES = (
    (b"PK\x03\x04", "ZIP archive"),
    (b"%PDF", "PDF document"),
    (b"MZ", "PE executable"),
    (b"\x7fELF", "ELF executable"),
    (b"\x1f\x8b", "gzip"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-zip archive"),
    (b"#!", "script shebang"),
    (b"<?php", "PHP source"),
    (b"<script", "HTML script element"),
    (b"{\\rtf", "RTF document"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"BM", "BMP image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
)


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    entropy = 0.0
    for count in counts:
        if count:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def hex_preview(data: bytes, limit: int = 64) -> dict:
    shown = data[:limit]
    return {
        "length": len(data),
        "shown": len(shown),
        "hex": shown.hex(),
        "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in shown),
    }


def printable_strings(data: bytes, min_len: int = 6, limit: int = 40) -> list:
    found = []
    start = None
    scan = data[:65536]
    for index, byte in enumerate(scan):
        if 32 <= byte < 127:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= min_len:
                found.append({"offset": start, "value": scan[start:index].decode("ascii")[:200]})
            start = None
            if len(found) >= limit:
                break
    if start is not None and len(scan) - start >= min_len and len(found) < limit:
        found.append({"offset": start, "value": scan[start:].decode("ascii")[:200]})
    return found


def identify_prefix(trailer: bytes) -> dict | None:
    if not trailer:
        return None
    stripped = trailer.lstrip(b"\x00\r\n\t ")
    if not stripped:
        return None
    offset = len(trailer) - len(stripped)
    for signature, name in PREFIX_SIGNATURES:
        if stripped.startswith(signature):
            return {"offset": offset, "type": name, "signature_hex": signature.hex()}
    return None


def _sample_rgb(img, budget: int = 100_000):
    rgb = img.convert("RGB")
    width, height = rgb.size
    total = width * height
    if total == 0:
        return []
    step = max(1, total // budget)
    pixels = rgb.load()
    sampled = []
    for index in range(0, total, step):
        y, x = divmod(index, width)
        sampled.append(pixels[x, y][:3])
    return sampled


def lsb_report(img, fmt: str) -> dict:
    if fmt == "JPEG":
        return {
            "status": "not_applicable",
            "evidence": {},
            "explanation": "Lossy JPEG does not preserve least-significant bits, so the LSB checks are not applied.",
        }
    sampled = _sample_rgb(img)
    bits = [channel & 1 for pixel in sampled for channel in pixel]
    n = len(bits)
    ones = sum(bits)
    ratio = ones / n if n else 0.0
    z = abs(ones - n / 2) / math.sqrt(n / 4) if n else 0.0
    flat, dominant = _flat_field(sampled)
    # A solid color is almost all 0s or all 1s in the LSB. That is the artwork, not a hidden message.
    bias_hit = n >= 300 and z > 5 and not flat
    pair = _pair_chi_square(sampled)
    pair_hit = bool(
        pair.get("applicable")
        and pair.get("chi_square_per_df", 99) <= 1.5
        and pair.get("pairs", 0) >= 8
        and pair.get("sampled_pixels", 0) >= 5000
    )
    status = "indicator" if bias_hit or pair_hit else "no_indicator_found"
    return {
        "status": status,
        "evidence": {
            "sampled_pixels": len(sampled),
            "sampled_bits": n,
            "one_fraction": round(ratio, 6),
            "bias_z_score": round(z, 3),
            "bias_threshold": 5,
            "bias_indicator": bias_hit,
            "flat_field": flat,
            "dominant_color_fraction": None if dominant is None else round(dominant, 4),
            "pair_test": pair,
            "pair_indicator": pair_hit,
        },
        "explanation": _lsb_explanation(flat, z),
    }


def _flat_field(sampled: list) -> tuple[bool, float | None]:
    if not sampled:
        return False, None
    counts: dict = {}
    for pixel in sampled:
        counts[pixel] = counts.get(pixel, 0) + 1
    ranked = sorted(counts.values(), reverse=True)
    dominant = ranked[0] / len(sampled)
    top_two = sum(ranked[:2]) / len(sampled)
    # Screenshots and flat artwork pile into a handful of colors. Their LSBs
    # are lopsided by construction, so bias is reported and not scored.
    return len(counts) < 24 or dominant >= 0.85 or top_two >= 0.70, dominant


def _lsb_explanation(flat: bool, z: float) -> str:
    base = (
        "Two limited LSB checks. Bias measures whether sampled least-significant bits lean away from one half. "
        "The pair test measures whether adjacent sample values (2i, 2i+1) are unusually equal, which LSB replacement tends to produce. "
        "A short embedded message can miss both. Supported-layout recovery is a separate rule."
    )
    if flat and z > 5:
        return (
            "The bias statistic is high because one color dominates the sample. That is normal for a flat graphic, "
            "so bias is not scored as a hiding indicator. " + base
        )
    return base


def _pair_chi_square(sampled: list) -> dict:
    if len(sampled) < 300:
        return {"applicable": False, "reason": "Too few sampled pixels"}
    histogram = [0] * 256
    for red, _green, _blue in sampled:
        histogram[red] += 1
    chi = 0.0
    pairs = 0
    occupied = 0
    for i in range(0, 256, 2):
        total = histogram[i] + histogram[i + 1]
        if total == 0:
            continue
        occupied += 1
        expected = total / 2
        chi += (histogram[i] - expected) ** 2 / expected
        chi += (histogram[i + 1] - expected) ** 2 / expected
        pairs += 1
    if pairs == 0:
        return {"applicable": False, "reason": "Empty histogram"}
    return {
        "applicable": True,
        "channel": "R",
        "sampled_pixels": len(sampled),
        "pairs": pairs,
        "occupied_pairs": occupied,
        "chi_square": round(chi, 3),
        "degrees_of_freedom": pairs,
        "chi_square_per_df": round(chi / pairs, 3),
        "threshold_per_df": 1.5,
        "note": "After LSB replacement, adjacent values (2i and 2i+1) tend toward equal counts, so chi-square per degree of freedom falls near 1. A natural photograph is usually much higher. At or under 1.5 is the demonstration threshold.",
    }


def metadata_report(img, fmt: str, structure: dict) -> dict:
    keys = sorted(str(k) for k in img.info.keys())
    texts = []
    clues = []
    if fmt == "PNG":
        for key, value in sorted(getattr(img, "text", {}).items()):
            if not isinstance(value, str):
                continue
            texts.append({"key": key, "length": len(value), "preview": value[:180]})
            if key.lower() in STEGO_TEXT_KEYS and value.strip():
                clues.append(f"PNG text key “{key}” is a carrier this workbench can read when the value is text.")
            # XMP packets and color profiles are long by design; editors write them on ordinary files.
            structured = key.lower().startswith(("xml:com.adobe.xmp", "raw profile type", "icc"))
            if len(value) > 512 and not structured:
                clues.append(f"PNG text key “{key}” is {len(value)} characters, which is unusually long for a caption.")
        if not texts:
            clues.append("No PNG text chunks. Absence of a caption is ordinary.")
    exif_rows = []
    if fmt == "JPEG":
        exif = img.getexif()
        if not exif:
            clues.append("No EXIF metadata. That is common, and it is not a hiding indicator by itself.")
        else:
            from PIL.ExifTags import TAGS

            interesting = {"Make", "Model", "Software", "DateTime", "Artist", "ImageDescription", "Orientation", "GPSInfo"}
            for tag, value in exif.items():
                name = TAGS.get(tag, str(tag))
                shown = _flatten(value)
                if name == "GPSInfo":
                    clues.append("GPS tags are present. Treat that as a privacy and context clue, not as hidden content.")
                if name in interesting or len(exif_rows) < 12:
                    exif_rows.append({"tag": str(name), "value": shown[:300]})
        if structure.get("header", {}).get("long_comment"):
            clues.append(f"JPEG COM segment is {structure['header']['long_comment']} bytes.")
    if fmt == "BMP":
        clues.append("BMP has no EXIF-style metadata in this parser. Captions would have to live in trailing bytes.")
    return {
        "status": "clue" if any("carrier" in c or "unusually long" in c or "COM segment" in c or "GPS" in c for c in clues) else "no_indicator_found",
        "evidence": {"info_keys": keys, "png_text": texts, "exif": exif_rows, "clues": clues},
        "explanation": "Metadata is context. A caption, a camera tag, or a missing EXIF block does not identify who sent the file.",
    }


def _flatten(value) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return value.hex()
    return str(value)


def archive_listing(trailer: bytes, signature: dict | None) -> list | None:
    """Names and sizes inside an appended ZIP, read from its directory. Nothing is extracted or opened."""
    if not signature or signature.get("type") != "ZIP archive":
        return None
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(trailer[signature["offset"] :])) as zf:
            return [
                {"name": info.filename[:200], "size_bytes": info.file_size, "compressed_bytes": info.compress_size}
                for info in zf.infolist()[:20]
            ]
    except (zipfile.BadZipFile, ValueError, OSError, EOFError):
        return None


def appended_report(data: bytes, end: int, rule: str) -> dict:
    trailer = data[end:]
    signature = identify_prefix(trailer)
    entropy = round(shannon_entropy(trailer), 3) if trailer else None
    high_entropy = bool(trailer) and len(trailer) >= 64 and entropy is not None and entropy >= 7.5
    return {
        "status": "indicator" if trailer else "no_indicator_found",
        "evidence": {
            "rule": rule,
            "structure_end_offset": end,
            "file_size": len(data),
            "trailing_bytes": len(trailer),
            "trailing_sha256": hashlib.sha256(trailer).hexdigest() if trailer else None,
            "entropy_bits_per_byte": entropy,
            "high_entropy": high_entropy,
            "embedded_signature": signature,
            "archive_listing": archive_listing(trailer, signature),
            "hex_preview": hex_preview(trailer) if trailer else None,
            "strings": printable_strings(trailer) if trailer else [],
        },
        "explanation": (
            "Bytes after the identified container end are unusual. They can be a second file, a message, padding, or a sloppy encoder. "
            "High entropy means the trailer looks compressed or encrypted; this workbench does not decrypt it. "
            "A recognized file signature is named and left in place."
            if trailer
            else "No bytes were found after the identified container end."
        ),
    }
