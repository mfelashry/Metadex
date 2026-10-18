"""Scan a folder from the terminal, no browser needed.

Usage (from the backend folder):
    python3 -m app.cli ~/Desktop/seized_images
    python3 -m app.cli ~/Desktop/seized_images --recursive
    python3 -m app.cli ~/Desktop/seized_images --json > report.json
    python3 -m app.cli --demo        (the built in evidence set, nothing on disk)
"""
import argparse
import json
import sys
import textwrap

from app.analyze import AnalysisError
from app.batch import analyze_many, scan_folder

LEVEL_MARK = {"high": "!!!", "suspicious": "!! ", "low": "!  ", "none": "   "}


def _print(result: dict) -> None:
    summary = result["summary"]
    source = result["source"]
    where = source.get("path") or source.get("title") or source.get("type")
    print(f"\nStillframe scan of {where}")
    print(f"{summary['headline']}. Skipped {summary['skipped']}. Messages recovered: {summary['messages_recovered']}.")
    print(result["integrity"]["statement"])
    print()
    print(f"{'#':>3}  {'':3} {'score':>5}  {'level':<14} file")
    print("-" * 78)
    for entry in result["ranking"]:
        print(f"{entry['rank']:>3}  {LEVEL_MARK[entry['level']]} {entry['score']:>5}  {entry['level_label']:<14} {entry['path'] or entry['filename']}")
        for reason in entry["top_reasons"][:2]:
            for i, line in enumerate(textwrap.wrap(reason, 70)):
                print(f"{'':30}{'- ' if i == 0 else '  '}{line}")
        for msg in entry["messages"]:
            text = msg["text"].replace("\n", " ")[:90]
            print(f"{'':30}> message ({msg['where']}, {msg['encoding']}): {text}")
    if result["skipped"]:
        print("\nSkipped:")
        for item in result["skipped"]:
            print(f"  {item['filename']}: {item['reason']}")
    corr = result["correlations"]
    if corr["duplicate_files"] or corr["shared_payloads"]:
        print("\nCorrelations:")
        for dup in corr["duplicate_files"]:
            print(f"  identical files: {', '.join(dup['files'])}")
        for shared in corr["shared_payloads"]:
            print(f"  same hidden content in: {', '.join(shared['files'])}")
    print(f"\n{result['statement']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rank a folder of images by hidden-data suspicion.")
    parser.add_argument("folder", nargs="?", help="Folder to scan")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    parser.add_argument("--demo", action="store_true", help="Scan the built in evidence set instead of a folder")
    args = parser.parse_args(argv)
    try:
        if args.demo:
            from app.evidence import DEMO_ACTIVITY, build_evidence

            items = [(f["filename"], f["data"]) for f in build_evidence()]
            result = analyze_many(items, DEMO_ACTIVITY, None, {"type": "demo", "title": "built in evidence set"})
        elif args.folder:
            result = scan_folder(args.folder, args.recursive)
        else:
            parser.print_help()
            return 2
    except AnalysisError as exc:
        detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
        print(f"Error: {detail}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
