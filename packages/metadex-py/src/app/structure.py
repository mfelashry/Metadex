"""Container parsers for PNG, JPEG, and BMP.

Each parser returns the offset where the container ends and a map an analyst
can check by hand. Bytes after that offset are trailing data, not a parse error.
"""
import struct
import zlib

JPEG_NAMES = {
    0xD8: "SOI",
    0xD9: "EOI",
    0xDA: "SOS",
    0xC0: "SOF0",
    0xC1: "SOF1",
    0xC2: "SOF2",
    0xC4: "DHT",
    0xDB: "DQT",
    0xDD: "DRI",
    0xFE: "COM",
}


def _jpeg_name(marker: int) -> str:
    if marker in JPEG_NAMES:
        return JPEG_NAMES[marker]
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    if 0xD0 <= marker <= 0xD7:
        return f"RST{marker - 0xD0}"
    return f"0x{marker:02X}"


def parse_png(data: bytes) -> dict:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG signature")
    pos = 8
    chunks = []
    anomalies = []
    ihdr = None
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        end = pos + 12 + length
        if length < 0 or end > len(data):
            raise ValueError("Truncated PNG chunk")
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        stored = int.from_bytes(data[pos + 8 + length : end], "big")
        actual = zlib.crc32(ctype + body) & 0xFFFFFFFF
        try:
            name = ctype.decode("ascii")
        except UnicodeDecodeError:
            name = ctype.hex()
        if len(name) != 4:
            anomalies.append(f"Chunk type at offset {pos} is not four ASCII characters")
        crc_ok = stored == actual
        if not crc_ok:
            anomalies.append(f"CRC mismatch on {name} at offset {pos}")
        ancillary = bool(ctype[0] & 0x20) if ctype else False
        chunks.append(
            {
                "offset": pos,
                "type": name,
                "length": length,
                "crc_ok": crc_ok,
                "ancillary": ancillary,
                "critical": not ancillary,
            }
        )
        if name == "IHDR" and len(body) >= 13 and ihdr is None:
            width, height, bit_depth, color_type, compression, filtr, interlace = struct.unpack(">IIBBBBB", body[:13])
            ihdr = {
                "width": width,
                "height": height,
                "bit_depth": bit_depth,
                "color_type": color_type,
                "compression": compression,
                "filter": filtr,
                "interlace": interlace,
            }
        if ctype == b"IEND":
            if length != 0:
                raise ValueError("Invalid PNG IEND")
            if not crc_ok:
                anomalies.append("IEND checksum failed")
            if not chunks or chunks[0]["type"] != "IHDR":
                anomalies.append("IHDR is not the first chunk")
            if sum(1 for c in chunks if c["type"] == "IHDR") != 1:
                anomalies.append("PNG does not contain exactly one IHDR")
            return _result(end, "PNG IEND chunk end", chunks, anomalies, ihdr, "png-chunk")
        pos = end
    raise ValueError("PNG IEND missing")


def parse_jpeg(data: bytes) -> dict:
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        raise ValueError("Invalid JPEG")
    markers = [{"offset": 0, "marker": "SOI", "code": "FFD8", "length": 0, "note": ""}]
    details = {}
    pos = 2
    in_scan = False
    while pos < len(data):
        if not in_scan:
            if data[pos] != 0xFF:
                raise ValueError("Invalid JPEG marker")
            marker_offset = pos
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
        else:
            idx = data.find(b"\xff", pos)
            if idx < 0:
                break
            marker_offset = idx
            pos = idx + 1
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker == 0 or 0xD0 <= marker <= 0xD7:
                continue
            in_scan = False
        name = _jpeg_name(marker)
        if marker == 0xD9:
            markers.append({"offset": marker_offset, "marker": "EOI", "code": "FFD9", "length": 0, "note": ""})
            return _result(pos, "JPEG EOI marker after the entropy-coded scan", markers, [], details, "jpeg-marker")
        if marker == 0xDA:
            if pos + 2 > len(data):
                break
            length = int.from_bytes(data[pos : pos + 2], "big")
            if length < 2 or pos + length > len(data):
                break
            markers.append({"offset": marker_offset, "marker": name, "code": f"FF{marker:02X}", "length": length, "note": "entropy-coded scan follows"})
            pos += length
            in_scan = True
            continue
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            markers.append({"offset": marker_offset, "marker": name, "code": f"FF{marker:02X}", "length": 0, "note": ""})
            continue
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos : pos + 2], "big")
        if length < 2 or pos + length > len(data):
            break
        note = ""
        if marker in (0xC0, 0xC1, 0xC2) and length >= 7:
            precision = data[pos + 2]
            height, width = struct.unpack(">HH", data[pos + 3 : pos + 7])
            details = {"precision": precision, "width": width, "height": height, "progressive": marker == 0xC2}
            note = f"{width}×{height}, {precision}-bit" + (", progressive" if marker == 0xC2 else ", baseline")
        if marker == 0xFE:
            note = f"comment, {max(0, length - 2)} bytes"
            if length - 2 > 512:
                details["long_comment"] = length - 2
        markers.append({"offset": marker_offset, "marker": name, "code": f"FF{marker:02X}", "length": length, "note": note})
        pos += length
    raise ValueError("JPEG EOI missing")


def parse_bmp(data: bytes) -> dict:
    if len(data) < 54 or data[0:2] != b"BM":
        raise ValueError("BMP header too short")
    size = int.from_bytes(data[2:6], "little")
    reserved = int.from_bytes(data[6:10], "little")
    offset = int.from_bytes(data[10:14], "little")
    dib = int.from_bytes(data[14:18], "little")
    if size < offset or size > len(data) or dib < 12 or offset > len(data):
        raise ValueError("Invalid BMP declared size or header")
    anomalies = []
    if reserved != 0:
        anomalies.append("BMP reserved fields are not zero")
    width = height = planes = bit_count = compression = None
    if dib >= 16 and len(data) >= 26:
        width = struct.unpack_from("<i", data, 18)[0]
        height = struct.unpack_from("<i", data, 22)[0]
    if dib >= 40 and len(data) >= 34:
        planes = struct.unpack_from("<H", data, 26)[0]
        bit_count = struct.unpack_from("<H", data, 28)[0]
        compression = struct.unpack_from("<I", data, 30)[0]
        if planes not in (0, 1):
            anomalies.append(f"BMP planes value is {planes}")
    fields = [
        {"field": "bfType", "value": "BM", "note": "Bitmap signature"},
        {"field": "bfSize", "value": size, "note": "Declared file size. Bytes beyond this are trailing."},
        {"field": "bfOffBits", "value": offset, "note": "Pixel data offset"},
        {"field": "biSize", "value": dib, "note": "DIB header length"},
        {"field": "biWidth", "value": width, "note": ""},
        {"field": "biHeight", "value": height, "note": ""},
        {"field": "biPlanes", "value": planes, "note": ""},
        {"field": "biBitCount", "value": bit_count, "note": ""},
        {"field": "biCompression", "value": compression, "note": "0 is uncompressed BI_RGB"},
    ]
    header = {"bit_depth": bit_count, "compression": compression, "width": width, "height": abs(height) if isinstance(height, int) else None}
    return _result(size, "BMP bfSize file-header field", fields, anomalies, header, "bmp-header")


def parse_container(data: bytes, fmt: str) -> dict:
    if fmt == "PNG":
        return parse_png(data)
    if fmt == "JPEG":
        return parse_jpeg(data)
    if fmt == "BMP":
        return parse_bmp(data)
    raise ValueError("Unsupported format")


def _result(end: int, rule: str, rows: list, anomalies: list, header: dict | None, parser: str) -> dict:
    return {
        "end": end,
        "rule": rule,
        "rows": rows,
        "anomalies": anomalies,
        "header": header or {},
        "parser": parser,
    }
