"""Built-in evidence set for the image-search demo.

Every byte is drawn in this process. The presentation does not download photos.
One image is an ordinary meadow, two are drawn so a visual search has something
to rank, and one carries a synthetic JPEG comment plus trailing bytes so the
forensic panel has a known indicator. The indicator is planted for the demo.
It is not proof of an attack.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

SUGGESTED_QUERIES = ["a red backpack", "a person near a window"]

BACKPACK_SIZE = (520, 400)
WINDOW_SIZE = (500, 380)
MEADOW_SIZE = (540, 400)
LOCKER_SIZE = (460, 360)

LOCKER_MESSAGE = "Meet at locker 12. Bring the red key."


def build_items() -> list[dict]:
    return [
        {
            "filename": "red-backpack.png",
            "data": _backpack(),
            "role": "visual_match",
            "role_label": "Drawn red backpack. A search for that phrase should rank it highly.",
        },
        {
            "filename": "person-by-window.png",
            "data": _window(),
            "role": "visual_match",
            "role_label": "A person standing beside a window.",
        },
        {
            "filename": "clean-meadow.jpg",
            "data": _meadow(),
            "role": "clean",
            "role_label": "Ordinary meadow photo. No hidden-data indicator was planted.",
        },
        {
            "filename": "locker-note.jpg",
            "data": _locker(),
            "role": "forensic",
            "role_label": "Synthetic JPEG comment and trailing bytes. An indicator is not proof of an attack.",
        },
    ]


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _jpeg(image: Image.Image, comment: bytes | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Metadex"
    exif[0x0110] = "Demo"
    exif[0x0132] = "2026:10:18 09:00:00"
    out = io.BytesIO()
    kwargs = {"quality": 90, "exif": exif.tobytes()}
    if comment is not None:
        kwargs["comment"] = comment
    image.save(out, "JPEG", **kwargs)
    return out.getvalue()


def _backpack() -> bytes:
    width, height = BACKPACK_SIZE
    image = Image.new("RGB", (width, height), (244, 241, 234))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 300, width, height), fill=(214, 206, 196))
    draw.ellipse((70, 250, 450, 390), fill=(196, 186, 174))
    body = (150, 78, 318, 292)
    draw.rounded_rectangle(body, radius=36, fill=(196, 36, 42))
    draw.rounded_rectangle((168, 48, 300, 110), radius=18, fill=(168, 24, 32))
    draw.rectangle((176, 96, 292, 128), fill=(150, 18, 28))
    draw.arc((118, 40, 190, 150), 200, 20, fill=(90, 42, 28), width=10)
    draw.arc((278, 40, 350, 150), 160, 340, fill=(90, 42, 28), width=10)
    draw.rounded_rectangle((188, 168, 280, 230), radius=8, fill=(150, 22, 30))
    draw.rectangle((214, 188, 254, 198), fill=(232, 196, 64))
    draw.ellipse((228, 118, 246, 136), fill=(40, 40, 40))
    return _png(image)


def _window() -> bytes:
    width, height = WINDOW_SIZE
    image = Image.new("RGB", (width, height), (239, 232, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 300, width, height), fill=(186, 170, 150))
    draw.rectangle((250, 36, 430, 280), fill=(232, 236, 240))
    draw.rectangle((262, 48, 338, 150), fill=(126, 176, 214))
    draw.rectangle((346, 48, 418, 150), fill=(98, 156, 204))
    draw.rectangle((262, 162, 338, 268), fill=(110, 168, 210))
    draw.rectangle((346, 162, 418, 268), fill=(150, 196, 220))
    draw.rectangle((332, 36, 344, 280), fill=(92, 78, 64))
    draw.rectangle((250, 148, 430, 162), fill=(92, 78, 64))
    draw.ellipse((78, 78, 132, 132), fill=(232, 196, 160))
    draw.polygon([(70, 150), (140, 150), (156, 280), (54, 280)], fill=(46, 58, 84))
    draw.rectangle((72, 280, 100, 330), fill=(42, 42, 48))
    draw.rectangle((112, 280, 140, 330), fill=(42, 42, 48))
    draw.line((132, 168, 210, 150), fill=(46, 58, 84), width=8)
    return _png(image)


def _meadow() -> bytes:
    width, height = MEADOW_SIZE
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        if y < 210:
            t = y / 210
            color = (int(150 + 40 * t), int(196 + 20 * t), int(230 - 30 * t))
        else:
            t = (y - 210) / max(1, height - 210)
            color = (int(92 - 30 * t), int(158 - 40 * t), int(78 - 20 * t))
        draw.line((0, y, width, y), fill=color)
    draw.ellipse((390, 36, 470, 116), fill=(255, 214, 96))
    draw.ellipse((40, 230, 220, 300), fill=(46, 120, 62))
    draw.polygon([(300, 250), (340, 160), (380, 250)], fill=(34, 90, 48))
    return _jpeg(image)


def _locker() -> bytes:
    width, height = LOCKER_SIZE
    image = Image.new("RGB", (width, height), (210, 204, 196))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 36), fill=(72, 76, 82))
    for index in range(4):
        x = 36 + index * 104
        draw.rounded_rectangle((x, 70, x + 88, 320), radius=6, fill=(168, 154, 132))
        draw.rectangle((x + 36, 150, x + 52, 168), fill=(70, 70, 74))
    data = _jpeg(image, comment=LOCKER_MESSAGE.encode("utf-8"))
    return data + b"\nMETADEX-DEMO-TRAILER"
