"""Recover only steganography layouts this workbench explicitly supports.

Supported layouts:
- bytes appended after the container end
- text in EXIF fields and JPEG COM segments (see metadata_messages.py)
- PNG text keys Comment, Description, Message, Payload, Stego
- TECHSTEG1 RGB least-significant-bit framing

Recovered bytes are decoded as text for the analyst. They are not written,
opened, or executed. embed_demo builds the fixed exercise image; it is not an
API.
"""
import base64
import binascii
import hashlib

MAGIC = b"TECHSTEG1"
MAX_PREVIEW = 4096
TEXT_KEYS = {"comment", "description", "message", "payload", "stego"}


def _decode(payload: bytes) -> dict:
    if len(payload) > MAX_PREVIEW:
        return {"status": "unrecognized", "reason": "Payload exceeds the 4096-byte text preview"}
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "unrecognized",
            "reason": "Bytes are not UTF-8. Encrypted or unknown binary layouts stay unread.",
        }
    if not all(c.isprintable() or c in "\r\n\t" for c in value):
        return {"status": "unrecognized", "reason": "Non-printable bytes"}
    out = {"status": "decoded", "encoding": "utf-8", "message": value}
    stripped = value.strip()
    if stripped.startswith("base64:"):
        try:
            raw = base64.b64decode(stripped[7:], validate=True)
            out = {"status": "decoded", "encoding": "base64 -> utf-8", "message": raw.decode("utf-8")}
        except (ValueError, UnicodeDecodeError, binascii.Error):
            pass
    else:
        # Bare base64 or hex that turns into readable text is decoded too. The raw value is kept.
        from app.metadata_messages import try_decode

        decoded = try_decode(stripped)
        if decoded and "text" in decoded:
            out = {
                "status": "decoded",
                "encoding": f"{decoded['encoding']} -> utf-8",
                "message": decoded["text"],
                "raw": value[:MAX_PREVIEW],
            }
        elif decoded and "binary" in decoded:
            out = {
                "status": "unrecognized",
                "reason": (
                    f"{decoded['encoding']} that decodes to {len(decoded['binary'])} bytes of binary. "
                    "Looks compressed or encrypted. Encoding was reversed, but the content was not decrypted."
                ),
                "raw": value[:MAX_PREVIEW],
            }
    return out


def _record(method: str, payload: bytes, detail: str) -> dict:
    return {
        "method": method,
        "detail": detail,
        "length_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content": _decode(payload),
    }


def _lsb_bits(img):
    rgb = img.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    total = width * height * 3

    def bit_at(index: int):
        if index >= total:
            return None
        pixel_index, channel = divmod(index, 3)
        y, x = divmod(pixel_index, width)
        return pixels[x, y][channel] & 1

    return bit_at


def _read_bytes(bit_at, count: int):
    output = bytearray()
    index = 0
    # Caller passes a cursor via closure attribute.
    start = getattr(bit_at, "cursor", 0)
    for _ in range(count):
        byte = 0
        for _ in range(8):
            bit = bit_at(start + index)
            index += 1
            if bit is None:
                return None
            byte = (byte << 1) | bit
        output.append(byte)
    bit_at.cursor = start + index
    return bytes(output)


def recover(data: bytes, fmt: str, img, end: int, meta: dict | None = None) -> dict:
    found = []
    if end < len(data):
        found.append(_record("appended_bytes", data[end:], "Bytes after the container end"))
    # Messages found in EXIF fields and JPEG comments. PNG text keys are handled below as before.
    for item in (meta or {}).get("fields", []):
        png_known_key = item["source"] == "PNG text chunk" and item["field"].lower() in TEXT_KEYS
        if not item.get("flagged") or png_known_key or len(found) >= 12:
            continue
        raw = item["preview"].encode("utf-8")
        record = {
            "method": "metadata_text",
            "detail": "JPEG comment segment" if item["field"] == "COM" else f"{item['source']} field {item['field']}",
            "length_bytes": item["length"],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if item.get("decoded"):
            encoding = "utf-8" if item["encoding"] == "plain" else f"{item['encoding']} -> utf-8"
            record["content"] = {"status": "decoded", "encoding": encoding, "message": item["decoded"]}
            if item["encoding"] != "plain":
                record["content"]["raw"] = item["preview"]
        else:
            record["content"] = {"status": "unrecognized", "reason": item["reason"]}
        found.append(record)
    if fmt == "PNG":
        for key, val in sorted(img.text.items()):
            if len(found) >= 12:
                break
            if isinstance(val, str) and key.lower() in TEXT_KEYS:
                found.append(
                    _record("png_text_chunk", val.encode("utf-8")[: MAX_PREVIEW + 1], f"PNG text key: {key}")
                )
    if fmt in ("PNG", "BMP") and img.width * img.height <= 2_000_000:
        bit_at = _lsb_bits(img)
        bit_at.cursor = 0
        header = _read_bytes(bit_at, 13)
        if header is not None and header[:9] == MAGIC:
            length = int.from_bytes(header[9:13], "big")
            if 0 < length <= MAX_PREVIEW and (13 + length) * 8 <= img.width * img.height * 3:
                payload = _read_bytes(bit_at, length)
                if payload is not None:
                    found.append(
                        _record(
                            "rgb_lsb_techsteg1",
                            payload,
                            "RGB order, row-major, MSB-first inside each byte. Magic TECHSTEG1, then a 4-byte big-endian length.",
                        )
                    )
    methods = [item["method"] for item in found]
    return {
        "status": "recovered" if found else "no_indicator_found",
        "supported_methods": ["appended_bytes", "metadata_text", "png_text_chunk", "rgb_lsb_techsteg1"],
        "methods_found": list(dict.fromkeys(methods)),
        "payloads": found,
        "explanation": (
            "Only the layouts named above are decoded. Base64 and hex are decoded when they turn into readable text. "
            "Other steganography tools, passwords, and ciphertext stay unread. Nothing recovered here is executed."
        ),
    }


def embed_demo(img, message: str):
    """Stamp a TECHSTEG1 message into a copy of img. Used for the exercise fixture and tests."""
    payload = message.encode("utf-8")
    framed = MAGIC + len(payload).to_bytes(4, "big") + payload
    rgb = img.convert("RGB")
    if len(framed) * 8 > rgb.width * rgb.height * 3:
        raise ValueError("Image too small for the demonstration message")
    pixels = list(rgb.getdata())
    for i in range(len(framed) * 8):
        index, channel = divmod(i, 3)
        bit = (framed[i // 8] >> (7 - (i % 8))) & 1
        pixel = list(pixels[index])
        pixel[channel] = (pixel[channel] & ~1) | bit
        pixels[index] = tuple(pixel)
    rgb.putdata(pixels)
    return rgb
