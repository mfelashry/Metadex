"""Scan photos for hidden data from the terminal.

    metadex                  scan the folder you are in, and every folder inside it
    metadex ~/Pictures       scan that folder (or a single photo)
    metadex --all            scan the whole computer
    metadex serve            start the website checker

`scan` is still accepted as a first word, so `metadex scan ~/Pictures` works too.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}

EPILOG = """examples:
  metadex                  scan this folder and everything inside it
  metadex ~/Pictures       scan one folder
  metadex photo.jpg        scan one photo
  metadex --all            scan the whole computer (Ctrl+C stops and shows results so far)
  metadex --save out.json  scan, then save the results without asking (.html for the visual report)
  metadex --compare out.json   scan again and show exactly which files changed
  metadex serve            start the website checker on 127.0.0.1:8741"""


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BrokenPipeError:
        # Output was piped into something like `head` that stopped reading. Not an error.
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="metadex",
        description="Find hidden data in photos. With no path, scans the folder you are in.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", metavar="path", help="Folders or photos to scan (default: this folder)")
    parser.add_argument("--all", action="store_true", help="Scan the whole computer")
    parser.add_argument("--compare", metavar="FILE", help="Compare with the JSON saved from an earlier scan and list what changed")
    parser.add_argument("--save", metavar="FILE", help="Save without asking: a .json name saves the data, a .html name saves the visual report")
    parser.add_argument("--explain", action="store_true", help="Ask Gemini to explain the top finding (needs GEMINI_API_KEY)")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON instead of the table")
    parser.add_argument("--no-recursive", action="store_true", help="Only the top folder, not the folders inside it")
    # Removed option. Still accepted so old commands keep working, with a note.
    parser.add_argument("--sensors", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    paths = list(args.paths)
    if paths and paths[0] == "serve" and not Path("serve").exists():
        if len(paths) > 1 or args.all:
            parser.error("serve does not take a path")
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=8741)
        return 0
    if paths and paths[0] == "scan" and not Path("scan").exists():
        paths = paths[1:]
    if args.all and paths:
        parser.error("use either --all or a path, not both")

    from metadex import ui

    if args.sensors:
        ui.err_console.print("[yellow]--sensors is no longer needed and was ignored.[/]")

    previous = None
    if args.compare:
        from metadex.compare import load_previous

        try:
            previous = load_previous(args.compare)
        except RuntimeError as error:
            ui.err_console.print(f"[bold red]metadex:[/] {error}")
            return 1
    quiet = args.json
    started = time.monotonic()
    from datetime import datetime

    when = datetime.now()
    try:
        if args.all:
            from app.sweep import whole_computer_roots

            roots = whole_computer_roots()
            if not quiet:
                ui.header(
                    [
                        f"Scanning [bold]the whole computer[/] ({', '.join(roots)})",
                        "[dim]System and app folders are skipped. Press Ctrl+C to stop early.[/]",
                    ]
                )
            reports = [scan_tree(roots, True, True, quiet)]
            label = "The whole computer (" + ", ".join(roots) + "). System and app folders were skipped."
        else:
            targets = [Path(item).expanduser() for item in (paths or ["."])]
            for target in targets:
                if not target.exists():
                    raise RuntimeError(f"No such file or folder: {target}")
            if not quiet:
                ui.header([_describe(t, not args.no_recursive) for t in targets])
            reports = [scan(t, not args.no_recursive, quiet) for t in targets]
            label = "; ".join(_plain_label(t, not args.no_recursive) for t in targets)
    except KeyboardInterrupt:
        ui.err_console.print("\n[yellow]Cancelled before the scan started.[/]")
        return 130
    except (OSError, RuntimeError) as error:
        ui.err_console.print(f"[bold red]metadex:[/] {error}")
        return 1
    elapsed = time.monotonic() - started
    from metadex.compare import add_case_fingerprint, combined, compare

    for report in reports:
        add_case_fingerprint(report)
    data = reports if len(reports) > 1 else reports[0]
    result = None
    if previous:
        result = compare(previous["fingerprints"], combined(reports))
        result["compared_with"] = previous["file"]
        if isinstance(data, dict):
            data["comparison"] = result

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        for report in reports:
            ui.render(report, whole_computer=args.all, elapsed=elapsed)
        if result:
            ui.comparison(result, previous)
    if args.explain:
        for report in reports:
            text, error = explain_report(report)
            if args.json:
                print(f"Gemini: {error or text}", file=sys.stderr)
            else:
                ui.explanation(text, error)

    context = {"label": label, "when": when, "whole_computer": args.all, "elapsed": elapsed}
    if args.save:
        ui.saved(ui.save(data, args.save, context))
    elif not args.json and sys.stdin.isatty() and sys.stdout.isatty():
        ui.ask_to_save(data, context)
    return 0


def _plain_label(target: Path, recursive: bool) -> str:
    shown = str(target.resolve())
    if target.is_dir():
        return f"The folder {shown}" + (" and the folders inside it" if recursive else "")
    return f"The photo {shown}"


def _describe(target: Path, recursive: bool) -> str:
    from metadex.ui import tidy

    shown = tidy(str(target.resolve()))
    if target.is_dir():
        return f"Scanning [bold]{shown}[/]" + (" and the folders inside it" if recursive else "")
    return f"Checking [bold]{shown}[/]"


def scan_tree(roots: list[str], recursive: bool, whole_computer: bool, quiet: bool) -> dict:
    """Count, then scan with a progress bar. Ctrl+C during the scan stops early and keeps the results."""
    from app.sweep import iter_files, sweep
    from metadex import ui

    keep = "flagged" if whole_computer else "all"
    if quiet:
        return sweep(roots, recursive=recursive, whole_computer=whole_computer, keep_reports=keep)
    resolved = [str(Path(r).expanduser().resolve()) for r in roots]
    total = ui.count_files(iter_files(resolved, recursive, whole_computer))
    with ui.ScanProgress(total) as bar:
        return sweep(roots, recursive=recursive, whole_computer=whole_computer, keep_reports=keep, progress=bar.update)


def scan(path: Path, recursive: bool, quiet: bool = True) -> dict:
    from app.batch import analyze_many

    if path.is_dir():
        return scan_tree([str(path)], recursive, False, quiet)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise RuntimeError(f"Not an image: {path.name}")
    if quiet:
        return analyze_many([(path.name, path.read_bytes())], source={"type": "local", "path": str(path)})
    from metadex import ui

    with ui.console.status("[dim]Checking the photo…[/]", spinner="dots"):
        return analyze_many([(path.name, path.read_bytes())], source={"type": "local", "path": str(path)})


def _forensic_reasons(item: dict) -> list[str]:
    text = " ".join(item.get("top_reasons") or []).lower()
    reasons = []
    if item.get("messages"):
        reasons.append("Readable content was recovered")
    if any(word in text for word in ("after the end", "trailer", "extra bytes")):
        reasons.append("Extra data after the image end")
    if any(word in text for word in ("metadata", "exif", "base64", "comment", "description")):
        reasons.append("Unusual metadata or encoding")
    if any(word in text for word in ("pixel", "lsb", "channel")):
        reasons.append("Unusual pixel pattern")
    return reasons or ["No specific hidden-data indicators were reported"]


def explain_report(report: dict) -> tuple[str | None, str | None]:
    """Returns (text, error). Only the level and finding categories are sent to Gemini."""
    from app.gemini import GeminiError, explain

    ranking = report.get("ranking") or []
    if not ranking:
        return None, "Nothing to explain."
    lead = max(ranking, key=lambda item: item.get("score") or 0)
    try:
        return explain(str(lead.get("level") or "none"), _forensic_reasons(lead), []), None
    except GeminiError as error:
        return None, str(error)


if __name__ == "__main__":
    raise SystemExit(main())
