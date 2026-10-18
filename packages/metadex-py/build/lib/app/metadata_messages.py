"""Find text hidden in image metadata and decode simple encodings.

Sources read (all from bytes already in memory, nothing is executed):
- JPEG EXIF main IFD: ImageDescription, Artist, Copyright, Software, Make, Model,
  and the Windows XP fields (XPTitle, XPComment, XPAuthor, XPKeywords, XPSubject)
- JPEG EXIF sub IFD: UserComment, ImageUniqueID
- JPEG COM segments, read straight from the marker map in structure.py
- PNG text chunks (tEXt, zTXt, iTXt), every key

Each value is classified. Base64 and hex are decoded when they turn into
readable text. When they decode to binary, the bytes are reported as unread,
because encoded is not the same as encrypted: base64 is reversible by anyone,
ciphertext needs a key this tool does not have.
"""
import base64
import binascii
import math
import re

# Fields where a camera or phone normally writes nothing, or a short label.
CARRIER_FIELDS = {
    "ImageDescription",
    "UserComment",
    "XPComment",
    "XPTitle",
    "XPSubject",
    "XPKeywords",
    "COM",
}
# Fields with a normal, short expected value. Only encoded or oversized content is flagged here.
CONTEXT_FIELDS = {"Artist", "Copyright", "Software", "Make", "Model", "XPAuthor", "ImageUniqueID"}
# Standard PNG keywords that normally hold short tool or authorship labels.
PNG_CONTEXT_KEYS = {"software", "author", "copyright", "creation time", "source", "date:create", "date:modify", "date:timestamp"}
# PNG keys that editors fill with large structured data. Reported, never treated as a message.
PNG_STRUCTURED_PREFIXES = ("xml:com.adobe.xmp", "raw profile type", "icc")

MAIN_IFD_TAGS = {
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0131: "Software",
    0x013B: "Artist",
    0x8298: "Copyright",
    0x9C9B: "XPTitle",
    0x9C9C: "XPComment",
    0x9C9D: "XPAuthor",
    0x9C9E: "XPKeywords",
    0x9C9F: "XPSubject",
}
EXIF_IFD_TAGS = {0x9286: "UserComment", 0xA420: "ImageUniqueID"}
XP_FIELDS = {"XPTitle", "XPComment", "XPAuthor", "XPKeywords", "XPSubject"}

# Labels cameras and editors write on their own. Not treated as messages.
KNOWN_DEFAULTS = {
    "olympus digital camera",
    "sony dsc",
    "default",
    "dcim",
    "created with gimp",
    "screenshot",
    "exif_jpeg_picture",
    "lead technologies inc. v1.01",
    "camera",
    "image",
    "picture",
}

LONG_FIELD = 256
MAX_FIELDS = 40
MAX_TEXT = 4096
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
B64URL_RE = re.compile(r"^[A-Za-z0-9_\-]+={0,2}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def char_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def readable(value: str) -> bool:
    """True when the text is something a person could read."""
    if not value or len(value) < 3:
        return False
    if not all(ch.isprintable() or ch in "\r\n\t" for ch in value):
        return False
    letters = sum(ch.isalpha() for ch in value)
    return letters >= max(2, len(value) * 0.4)


def _to_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if readable(text) else None


def try_decode(value: str) -> dict | None:
    """Return {"encoding", "text"} for readable base64 or hex, {"encoding", "binary"} for opaque, else None."""
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 12:
        return None
    mixed = any(c.isupper() for c in compact) and any(c.islower() for c in compact)
    if len(compact) % 4 == 0 and (B64_RE.match(compact) or B64URL_RE.match(compact)):
        try:
            if B64_RE.match(compact):
                raw = base64.b64decode(compact, validate=True)
            else:
                raw = base64.urlsafe_b64decode(compact)
        except (ValueError, binascii.Error):
            raw = None
        if raw:
            text = _to_text(raw)
            if text is not None:
                return {"encoding": "base64", "text": text[:MAX_TEXT]}
            # Long, mixed-case base64 with digits or symbols that decodes to binary looks like packed or encrypted data.
            # A single long word would also pass the alphabet test, so it must have no spaces and some non-letters.
            has_non_letter = any(c.isdigit() or c in "+/_-" for c in compact)
            if len(compact) >= 24 and mixed and has_non_letter and " " not in value.strip():
                return {"encoding": "base64", "binary": raw}
    if len(compact) % 2 == 0 and len(compact) >= 16 and HEX_RE.match(compact):
        raw = bytes.fromhex(compact)
        text = _to_text(raw)
        if text is not None:
            return {"encoding": "hex", "text": text[:MAX_TEXT]}
        return {"encoding": "hex", "binary": raw}
    return None


def _decode_user_comment(raw) -> str:
    if not isinstance(raw, bytes):
        return str(raw)
    head, body = raw[:8], raw[8:]
    if head.startswith(b"ASCII"):
        return body.decode("ascii", "replace")
    if head.startswith(b"UNICODE"):
        for codec in ("utf-16-be", "utf-16-le"):
            text = body.decode(codec, "replace")
            if readable(text.strip("\x00")):
                return text
        return body.decode("utf-16-le", "replace")
    if head == b"\x00" * 8:
        return body.decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


def _flatten(name: str, value) -> str:
    if name == "UserComment":
        text = _decode_user_comment(value)
    elif name in XP_FIELDS and isinstance(value, (bytes, tuple, list)):
        raw = bytes(value) if not isinstance(value, bytes) else value
        text = raw.decode("utf-16-le", "replace")
    elif isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
    else:
        text = str(value)
    return text.replace("\x00", "").strip()


def collect_fields(img, fmt: str, data: bytes, structure: dict) -> list:
    """Every text-bearing metadata value this module knows how to read."""
    fields = []
    if fmt == "JPEG":
        try:
            exif = img.getexif()
        except Exception:
            exif = None
        if exif:
            for tag, name in MAIN_IFD_TAGS.items():
                if tag in exif:
                    fields.append({"source": "EXIF", "ifd": "IFD0", "field": name, "tag": f"0x{tag:04X}", "value": _flatten(name, exif[tag])})
            try:
                sub = exif.get_ifd(0x8769)
            except Exception:
                sub = {}
            for tag, name in EXIF_IFD_TAGS.items():
                if tag in sub:
                    fields.append({"source": "EXIF", "ifd": "Exif", "field": name, "tag": f"0x{tag:04X}", "value": _flatten(name, sub[tag])})
        # COM segments, read from the raw marker map so nothing depends on a library's choice of which comment to keep.
        for row in structure.get("rows", []):
            if row.get("marker") == "COM" and row.get("length", 0) > 2:
                start = row["offset"] + 4
                body = data[start : start + row["length"] - 2]
                fields.append(
                    {
                        "source": "JPEG COM segment",
                        "ifd": None,
                        "field": "COM",
                        "tag": f"offset {row['offset']}",
                        "value": body.decode("utf-8", "replace").replace("\x00", "").strip(),
                    }
                )
    elif fmt == "PNG":
        for key, value in sorted(getattr(img, "text", {}).items()):
            if isinstance(value, str):
                fields.append({"source": "PNG text chunk", "ifd": None, "field": key, "tag": key, "value": value.strip()})
    return fields[:MAX_FIELDS]


def classify(field: dict) -> dict:
    name = field["field"]
    value = field["value"]
    label = "The JPEG comment segment" if name == "COM" else name
    is_png = field["source"] == "PNG text chunk"
    lowered = name.lower()
    is_context = name in CONTEXT_FIELDS or (is_png and lowered in PNG_CONTEXT_KEYS)
    is_carrier = name in CARRIER_FIELDS or (is_png and not is_context)
    entropy = round(char_entropy(value), 3)
    out = {
        "source": field["source"],
        "ifd": field["ifd"],
        "field": name,
        "tag": field["tag"],
        "length": len(value),
        "entropy_bits_per_char": entropy,
        "preview": value[:300],
        "classification": "normal",
        "flagged": False,
        "weight": 0,
        "decoded": None,
        "encoding": None,
        "reason": "",
    }
    if not value:
        out["classification"] = "empty"
        out["reason"] = "Field is present but empty."
        return out
    if value.lower() in KNOWN_DEFAULTS:
        out["classification"] = "camera_default"
        out["reason"] = f"“{value}” is a label cameras and editors write on their own."
        return out
    if is_png and lowered.startswith(PNG_STRUCTURED_PREFIXES):
        out["classification"] = "structured_profile"
        out["preview"] = value[:120]
        out["reason"] = f"{name} is a structured block editors write (XMP or a color profile). Not parsed for messages in this version."
        return out

    decoded = try_decode(value)
    if decoded and "text" in decoded:
        out.update(
            classification=f"{decoded['encoding']}_text",
            flagged=True,
            weight=45,
            encoding=decoded["encoding"],
            decoded=decoded["text"],
            reason=f"{label} holds {decoded['encoding']} that decodes to readable text. Encoding hides text from a casual look, but anyone can reverse it.",
        )
        return out
    if decoded and "binary" in decoded and is_context and len(value) <= 64:
        # Phones write short hex or base64 IDs here (ImageUniqueID is often a 32 character hex GUID). Normal.
        out["classification"] = "identifier"
        out["reason"] = f"{label} holds a short {decoded['encoding']} identifier, which devices write on their own."
        return out
    if decoded and "binary" in decoded:
        raw = decoded["binary"]
        out.update(
            classification=f"{decoded['encoding']}_binary",
            flagged=True,
            weight=40,
            encoding=decoded["encoding"],
            reason=(
                f"{label} holds {len(value)} characters of {decoded['encoding']} that decode to {len(raw)} bytes of binary. "
                "Consistent with compressed or encrypted content. Not decrypted."
            ),
        )
        return out
    if len(value) > LONG_FIELD:
        out.update(
            classification="oversized",
            flagged=True,
            weight=30,
            reason=f"{label} is {len(value)} characters. Cameras write short labels here.",
        )
        return out
    if len(value) >= 32 and entropy >= 4.8 and not readable(value) and not (is_context and len(value) <= 64):
        out.update(
            classification="random_looking",
            flagged=True,
            weight=30,
            reason=f"{label} looks random ({entropy} bits per character). Possibly encoded or encrypted.",
        )
        return out
    if is_carrier and readable(value):
        out.update(
            classification="plain_text",
            flagged=True,
            weight=25,
            encoding="plain",
            decoded=value[:MAX_TEXT],
            reason=f"{label} holds a written message. Phones and cameras do not normally write sentences here.",
        )
        return out
    out["reason"] = "Short value in a field where a value is expected." if is_context else "No sign of a hidden message."
    return out


def metadata_messages(img, fmt: str, data: bytes, structure: dict) -> dict:
    if fmt == "BMP":
        return {
            "status": "not_applicable",
            "fields": [],
            "messages": [],
            "explanation": "BMP files have no EXIF or text metadata in this parser.",
        }
    fields = [classify(f) for f in collect_fields(img, fmt, data, structure)]
    flagged = [f for f in fields if f["flagged"]]
    messages = []
    by_text: dict = {}
    for f in flagged:
        if not f["decoded"]:
            continue
        if f["decoded"] in by_text:
            by_text[f["decoded"]]["also_in"].append(f["field"])
            continue
        item = {"source": f["source"], "field": f["field"], "encoding": f["encoding"], "text": f["decoded"], "also_in": []}
        by_text[f["decoded"]] = item
        messages.append(item)
    unread = [f for f in flagged if f["classification"].endswith("_binary") or f["classification"] in ("random_looking",)]
    if flagged:
        status = "indicator"
    else:
        status = "no_indicator_found"
    return {
        "status": status,
        "fields": fields,
        "messages": messages,
        "unread_count": len(unread),
        "top_weight": max((f["weight"] for f in flagged), default=0),
        "explanation": (
            "Each metadata text field is checked for a written message, base64 or hex encoding, unusual length, and randomness. "
            "Readable encodings are decoded and shown. Binary results stay unread. "
            "XMP packets are not parsed in this version."
        ),
    }
