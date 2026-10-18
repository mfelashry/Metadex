"""Scan photos through the Metadex checker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metadex", description="Scan a photo or a folder.")
    parser.add_argument("command", choices=["scan", "serve"], help="Scan locally or start the website checker")
    parser.add_argument("path", nargs="*", help="An image, or a folder of images")
    parser.add_argument("--json", action="store_true", help="Print the full scanner result")
    parser.add_argument("--no-recursive", action="store_true", help="Do not open folders inside a folder")
    args = parser.parse_args(argv)

    if args.command == "serve":
        if args.path:
            parser.error("serve does not take a path")
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=8741)
        return 0
    if not args.path:
        parser.error("scan needs an image or folder")

    try:
        reports = [scan(Path(item).expanduser(), recursive=not args.no_recursive) for item in args.path]
    except (OSError, RuntimeError) as error:
        print(f"metadex: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
        return 0
    for report in reports:
        print_report(report)
    return 0


def scan(path: Path, recursive: bool) -> dict:
    from app.batch import analyze_many, scan_folder

    if not path.exists():
        raise RuntimeError(f"No such file or folder: {path}")
    if path.is_dir():
        return scan_folder(str(path), recursive)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise RuntimeError(f"Not an image: {path.name}")
    return analyze_many([(path.name, path.read_bytes())], source={"type": "local", "path": str(path)})


DETAIL_WORDS = ("make", "model", "date", "time", "gps", "software", "artist", "lens", "iso", "captured")
STRUCTURE_WORDS = ("byte", "trailer", "pixel", "lsb", "file type", "extension", "end of", "extra")


def _fields(item: dict) -> list:
    report = item.get("report") or {}
    image = report.get("image_analysis") or {}
    return (image.get("metadata_messages") or {}).get("fields") or []


def _value(field: dict) -> str | None:
    value = field.get("decoded") or field.get("preview")
    return str(value).strip() if value else None


def _groups(item: dict) -> list[tuple[str, list[str]]]:
    details = []
    structure = []
    for field in _fields(item):
        name = (field.get("field") or "").lower()
        value = _value(field)
        if not value:
            continue
        line = f"{field.get('field')}: {value}"
        if any(word in name for word in DETAIL_WORDS):
            details.append(line)
        elif any(word in name for word in STRUCTURE_WORDS):
            structure.append(line)
    for reason in item.get("top_reasons") or []:
        if any(word in reason.lower() for word in STRUCTURE_WORDS):
            structure.append(reason)
    hidden = []
    messages = item.get("messages") or (item.get("report") or {}).get("messages_found") or []
    for message in messages:
        text = message.get("text")
        if text:
            hidden.append(text)
    groups = []
    if details:
        groups.append(("File details", details[:4]))
    if hidden:
        groups.append(("Hidden text clues", hidden[:3]))
    if structure:
        groups.append(("Image structure", structure[:3]))
    return groups


def print_report(report: dict) -> None:
    summary = report.get("summary") or {}
    headline = summary.get("headline")
    if headline:
        print(headline)
        print()
    ranking = report.get("ranking") or []
    if not ranking:
        print("No images in that scan.")
        return
    for item in ranking:
        level = item.get("level_label") or item.get("level") or "None"
        print(f"{level}\t{item.get('filename')}")
        for title, lines in _groups(item):
            print(f"  {title}")
            for line in lines:
                print(f"    {line}")


if __name__ == "__main__":
    raise SystemExit(main())
