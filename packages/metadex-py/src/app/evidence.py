"""Build the demo evidence set: a pretend seized laptop's Pictures folder.

Everything is generated in memory with a fixed seed, so every run produces the
same bytes and the same hashes. tools/make_evidence.py writes these files to
disk; POST /api/demo-batch analyzes them without touching the disk.

Clean files look like ordinary phone photos and screenshots. The others each
carry one hiding technique, so the demo can show every rule firing.
"""
import base64
import copy
import functools
import io
import random
import zipfile

from PIL import Image, ImageDraw, ImageFilter
from PIL.PngImagePlugin import PngInfo

from app.demo import build_demo_image

SEED = 1042


def _photo(width: int, height: int, palette: tuple, seed: int) -> Image.Image:
    """A soft gradient scene with shapes and sensor-like noise, so it reads like a phone photo."""
    rng = random.Random(seed)
    top, bottom, accent = palette
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            (0, y, width, y),
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    for _ in range(6):
        cx, cy = rng.randrange(width), rng.randrange(height // 3, height)
        r = rng.randrange(width // 12, width // 4)
        shade = tuple(max(0, min(255, c + rng.randrange(-40, 40))) for c in accent)
        draw.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2), fill=shade)
    img = img.filter(ImageFilter.GaussianBlur(3))
    # Seeded noise (not Image.effect_noise) so the bytes, and the hashes, are identical on every run.
    noise = Image.frombytes("L", (width, height), rng.randbytes(width * height)).convert("RGB")
    return Image.blend(img, noise, 0.08)


def _randomize_lsb(img: Image.Image, seed: int) -> Image.Image:
    """Overwrite every pixel's last bit with random bits, the way a generic stego tool at full capacity would."""
    rgb = img.convert("RGB")
    rng = random.Random(seed)
    raw = bytearray(rgb.tobytes())
    noise = rng.randbytes(len(raw))
    for i in range(len(raw)):
        raw[i] = (raw[i] & 0xFE) | (noise[i] & 1)
    return Image.frombytes("RGB", rgb.size, bytes(raw))


def _camera_exif(model: str, when: str) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = model
    exif[0x0131] = "17.4.1"
    exif[0x0132] = when
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = when
    return exif


def _jpeg(img: Image.Image, exif: Image.Exif | None = None, comment: bytes | None = None) -> bytes:
    out = io.BytesIO()
    kwargs = {"quality": 88}
    if exif is not None:
        kwargs["exif"] = exif.tobytes()
    if comment is not None:
        kwargs["comment"] = comment
    img.save(out, "JPEG", **kwargs)
    return out.getvalue()


def _png(img: Image.Image, info: PngInfo | None = None) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG", pnginfo=info)
    return out.getvalue()


def _screenshot(width: int, height: int, title: str) -> Image.Image:
    img = Image.new("RGB", (width, height), (246, 247, 249))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 44), fill=(32, 33, 36))
    draw.text((16, 15), title, fill=(232, 234, 237))
    for i in range(6):
        y = 70 + i * 34
        draw.rectangle((16, y, width - 16, y + 24), fill=(255, 255, 255), outline=(220, 222, 226))
        draw.text((26, y + 6), f"Order #{4810 + i}   Delivered", fill=(60, 64, 67))
    return img


def _chart(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 14), "Q3 revenue by region", fill=(30, 30, 30))
    colors = [(66, 133, 244), (52, 168, 83), (251, 188, 5), (234, 67, 53)]
    for i, h in enumerate((120, 180, 90, 150)):
        x = 50 + i * 80
        draw.rectangle((x, height - 30 - h, x + 50, height - 30), fill=colors[i])
    draw.line((40, height - 30, width - 20, height - 30), fill=(120, 120, 120), width=2)
    return img


def build_evidence() -> list:
    """Return [{"filename", "data", "planted", "expected"}] in folder order. Cached, returned as a copy."""
    return copy.deepcopy(_build_evidence())


@functools.lru_cache(maxsize=1)
def _build_evidence() -> list:
    rng = random.Random(SEED)
    files = []

    beach = _photo(640, 480, ((120, 180, 230), (230, 210, 170), (40, 90, 140)), 11)
    files.append(
        {
            "filename": "IMG_2041.jpg",
            "data": _jpeg(beach, _camera_exif("iPhone 15", "2026:09:14 17:32:08")),
            "planted": "Nothing. Ordinary phone photo with normal camera EXIF.",
            "expected": "No indicators",
        }
    )

    dinner = _photo(640, 480, ((70, 40, 30), (200, 140, 90), (180, 60, 40)), 12)
    files.append(
        {
            "filename": "IMG_2057.jpg",
            "data": _jpeg(dinner, _camera_exif("iPhone 15", "2026:09:21 20:05:44")),
            "planted": "Nothing. Ordinary phone photo with normal camera EXIF.",
            "expected": "No indicators",
        }
    )

    files.append(
        {
            "filename": "Screenshot 2026-10-03.png",
            "data": _png(_screenshot(480, 300, "Orders")),
            "planted": "Nothing. A flat screenshot, included to show flat graphics do not trip the pixel statistics.",
            "expected": "No indicators",
        }
    )

    # Same technique as embed_message.py with base64 on: the sentence is base64 in UserComment and ImageDescription.
    secret = "Package moves Friday. Use the second phone."
    encoded = base64.b64encode(secret.encode()).decode()
    exif = _camera_exif("iPhone 14", "2026:10:02 09:12:30")
    exif[0x010E] = encoded
    exif.get_ifd(0x8769)[0x9286] = b"ASCII\x00\x00\x00" + encoded.encode()
    profile = _photo(480, 480, ((200, 190, 180), (90, 80, 70), (150, 110, 90)), 13)
    files.append(
        {
            "filename": "profile_photo.jpg",
            "data": _jpeg(profile, exif),
            "planted": f"Base64 sentence in EXIF UserComment and ImageDescription. Decodes to: {secret}",
            "expected": "High",
            "secret": secret,
        }
    )

    park = _photo(640, 480, ((150, 200, 240), (60, 120, 60), (40, 100, 40)), 14)
    files.append(
        {
            "filename": "IMG_2066.jpg",
            "data": _jpeg(park, _camera_exif("iPhone 15", "2026:10:05 12:40:19"), comment=b"drop point: north gate, 21:00"),
            "planted": "Plain sentence in a JPEG COM segment: drop point: north gate, 21:00",
            "expected": "Suspicious",
            "secret": "drop point: north gate, 21:00",
        }
    )

    # A ZIP holding a text file, glued after the end of a normal JPEG. The image still opens normally.
    sunset = _photo(640, 400, ((250, 150, 80), (60, 30, 80), (30, 20, 40)), 15)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("contacts.txt", "M. 555 0142\nR. 555 0199\nmeet at the usual place\n")
    files.append(
        {
            "filename": "sunset_wallpaper.jpg",
            "data": _jpeg(sunset, _camera_exif("iPhone 13", "2026:08:30 19:22:11")) + archive.getvalue(),
            "planted": "A ZIP archive (contacts.txt) appended after the JPEG end marker FF D9.",
            "expected": "High",
        }
    )

    # Hamza's exercise image: TECHSTEG1 message in pixel LSBs plus a short trailer. Name matches the activity timeline.
    files.append(
        {
            "filename": "invoice-scan.png",
            "data": build_demo_image(),
            "planted": "TECHSTEG1 message hidden in pixel least significant bits, plus the bytes DEMO-TRAILER after IEND.",
            "expected": "High",
        }
    )

    files.append(
        {
            "filename": "quarterly_report.jpg",
            "data": _png(_chart(420, 260)),
            "planted": "Nothing inside. It is a PNG renamed to .jpg to hide what it is.",
            "expected": "Low",
        }
    )

    # Encoded is not encrypted: random bytes, base64 encoded. It decodes, but only to binary, so it stays unread.
    blob = base64.b64encode(bytes(rng.randrange(256) for _ in range(96))).decode()
    info = PngInfo()
    info.add_text("Software", "Canva")
    info.add_text("Payload", blob)
    logo = Image.new("RGB", (320, 200), (250, 250, 252))
    ImageDraw.Draw(logo).ellipse((110, 50, 210, 150), fill=(20, 110, 200))
    files.append(
        {
            "filename": "logo_draft.png",
            "data": _png(logo, info),
            "planted": "128 characters of base64 in a PNG text chunk named Payload. It decodes to 96 random bytes, which look encrypted, so the tool flags it but cannot read it.",
            "expected": "Suspicious",
        }
    )

    # Unknown tool: every pixel's last bit replaced. No readable layout, only the statistics can see it.
    card = _randomize_lsb(_photo(640, 480, ((180, 40, 50), (250, 240, 230), (30, 120, 60)), 16), 77)
    files.append(
        {
            "filename": "holiday_card.png",
            "data": _png(card),
            "planted": "Data spread across the last bit of every pixel by an unknown tool. Nothing readable, only the pixel statistics catch it.",
            "expected": "Suspicious",
        }
    )

    # Exact copy of an earlier photo under a different name, to show duplicate detection.
    files.append(
        {
            "filename": "IMG_2041 (1).jpg",
            "data": files[0]["data"],
            "planted": "Byte for byte copy of IMG_2041.jpg. Shows up under correlations as a duplicate.",
            "expected": "No indicators",
        }
    )

    files.append(
        {
            "filename": "notes.txt",
            "data": b"grocery list: eggs, rice, tomatoes\n",
            "planted": "Not an image. Shows how the scanner skips files it does not support.",
            "expected": "Skipped",
        }
    )
    return files


DEMO_ACTIVITY = [
    {
        "timestamp": "2026-10-02T09:15:02Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "file_download",
        "process_name": "Telegram.exe",
        "file_path": "C:\\Users\\owner\\Pictures\\profile_photo.jpg",
        "detail": "Image saved from a chat",
    },
    {
        "timestamp": "2026-10-02T09:16:40Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "file_read",
        "process_name": "python.exe",
        "file_path": "C:\\Users\\owner\\Pictures\\profile_photo.jpg",
        "command_line": "python.exe read_meta.py profile_photo.jpg",
        "detail": "A script opened the image, not a photo viewer",
    },
    {
        "timestamp": "2026-10-02T09:17:05Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "network_send",
        "process_name": "python.exe",
        "destination": "198.51.100.23:8443",
        "bytes_sent": 512,
        "detail": "The same script sent data out 25 seconds later",
    },
    {
        "timestamp": "2026-10-02T11:30:00Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "file_open",
        "process_name": "Photos.exe",
        "file_path": "C:\\Users\\owner\\Pictures\\IMG_2057.jpg",
        "detail": "Normal photo viewing",
    },
    {
        "timestamp": "2026-10-17T14:02:11Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "file_write",
        "process_name": "msedge.exe",
        "file_path": "C:\\Users\\owner\\Downloads\\invoice-scan.png",
        "detail": "Browser saved the download",
    },
    {
        "timestamp": "2026-10-17T14:04:02Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "file_read",
        "process_name": "ImageDecodeHost.exe",
        "file_path": "C:\\Users\\owner\\Downloads\\invoice-scan.png",
        "detail": "A different process opened the image",
    },
    {
        "timestamp": "2026-10-17T14:04:19Z",
        "host_id": "suspect-laptop",
        "user": "owner",
        "event_type": "network_send",
        "process_name": "ImageDecodeHost.exe",
        "destination": "203.0.113.50:443",
        "bytes_sent": 428,
        "detail": "Outbound send from the process that had just read the image",
    },
]
