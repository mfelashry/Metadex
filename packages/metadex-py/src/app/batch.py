"""Scan many images at once and rank them for the examiner.

Two inputs feed the same pipeline:
- scan_folder: a folder path on this computer. Files are opened read only and
  hashed again from disk after analysis, so the report can show the evidence
  was not altered.
- analyze_many: files already in memory (a browser folder picker upload).

Each image still goes through analyze_bytes, so single and batch reports agree.
"""
import hashlib
import os
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from app.analyze import LIMITATIONS, MAX_BYTES, AnalysisError, analyze_bytes
from app.scoring import LEVEL_ORDER

MAX_FILES = 500
MAX_DEPTH = 6
SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"BM")
MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "BMP": "image/bmp"}

# Previews: only files that a recent scan analyzed can be served back, so the
# endpoint cannot be used to read arbitrary paths. Folder scans keep the path,
# the demo keeps its bytes. Browser uploads keep nothing (the page already has the file).
MAX_SCANS_KEPT = 10
_previews: "OrderedDict[str, dict]" = OrderedDict()
_lock = threading.Lock()


def _remember(scan_id: str, items: dict) -> None:
    with _lock:
        _previews[scan_id] = items
        while len(_previews) > MAX_SCANS_KEPT:
            _previews.popitem(last=False)


def preview(scan_id: str, item_id: str) -> tuple[bytes, str] | None:
    """Bytes and media type for one image from a recent scan, re-read from disk read only."""
    with _lock:
        item = (_previews.get(scan_id) or {}).get(item_id)
    if not item:
        return None
    if "data" in item:
        data = item["data"]
    else:
        try:
            with open(item["path"], "rb") as fh:
                data = fh.read(MAX_BYTES + 1)
        except OSError:
            return None
    if len(data) > MAX_BYTES or not _looks_like_image(data[:8]):
        return None
    return data, MEDIA_TYPES[item["format"]]


def _looks_like_image(head: bytes) -> bool:
    return any(head.startswith(sig) for sig in SIGNATURES)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _error_text(exc: AnalysisError) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return f"{detail.get('message', 'Analysis error')} ({exc.status_code})"
    return f"{detail} ({exc.status_code})"


def _entry(item_id: str, name: str, rel_path: str | None, report: dict) -> dict:
    suspicion = report["suspicion"]
    return {
        "id": item_id,
        "rank": None,
        "filename": name,
        "path": rel_path,
        "format": report["file"]["format"],
        "size_bytes": report["file"]["size_bytes"],
        "width": report["file"]["width"],
        "height": report["file"]["height"],
        "sha256": report["file"]["sha256"],
        "score": suspicion["score"],
        "level": suspicion["level"],
        "level_label": suspicion["level_label"],
        "headline": report["conclusions"]["hidden_data"]["headline"],
        "top_reasons": suspicion["top_reasons"],
        "messages": report["messages_found"],
        "extension_check": report["file"]["extension_check"]["status"],
        "activity_status": report["conclusions"]["activity"]["status"],
        "integrity": report["integrity"],
        "report": report,
    }


def _finish(entries: list, skipped: list, source: dict, truncated: bool, previews: dict | None = None) -> dict:
    scan_id = uuid.uuid4().hex[:12]
    entries.sort(key=lambda e: (-e["score"], -LEVEL_ORDER[e["level"]], e["filename"].lower()))
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index
        entry["preview_url"] = f"/api/preview/{scan_id}/{entry['id']}" if previews and entry["id"] in previews else None
    if previews:
        _remember(scan_id, previews)
    levels = {"high": 0, "suspicious": 0, "low": 0, "none": 0}
    for entry in entries:
        levels[entry["level"]] += 1
    flagged = [e for e in entries if e["score"] > 0]
    all_unchanged = all(e["integrity"]["unchanged"] for e in entries)
    if entries:
        headline = f"{len(flagged)} of {len(entries)} images show hidden-data indicators"
    else:
        headline = "No supported images were found"
    return {
        "scan_id": scan_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_version": "stillframe-2",
        "source": source,
        "summary": {
            "headline": headline,
            "scanned": len(entries),
            "skipped": len(skipped),
            "with_indicators": len(flagged),
            "levels": levels,
            "most_suspicious": entries[0]["filename"] if entries and entries[0]["score"] > 0 else None,
            "messages_recovered": sum(len(e["messages"]) for e in entries),
            "truncated": truncated,
        },
        "integrity": {
            "all_unchanged": all_unchanged,
            "statement": (
                "Every file was hashed before and after analysis. All hashes match, so the scan did not alter the evidence."
                if all_unchanged
                else "At least one file changed during the scan. See the per-file integrity block."
            ),
        },
        "correlations": _correlations(entries),
        "ranking": entries,
        "skipped": skipped,
        "statement": "Ranking is a triage order for the examiner. A score is evidence to review, not proof of hidden data or intent.",
        "limitations": LIMITATIONS,
    }


def _correlations(entries: list) -> dict:
    """Link artifacts that show up in more than one file."""
    by_hash: dict = {}
    for e in entries:
        by_hash.setdefault(e["sha256"], []).append(e["filename"])
    duplicates = [{"sha256": h, "files": names} for h, names in by_hash.items() if len(names) > 1]

    by_payload: dict = {}
    for e in entries:
        seen = set()
        for payload in e["report"]["recovery"]["payloads"]:
            key = payload["sha256"]
            if key in seen:
                continue
            seen.add(key)
            preview = (payload.get("content") or {}).get("message")
            by_payload.setdefault(key, {"preview": preview, "files": []})["files"].append(e["filename"])
    shared = [
        {"payload_sha256": key, "message": value["preview"], "files": value["files"]}
        for key, value in by_payload.items()
        if len(value["files"]) > 1
    ]
    return {
        "duplicate_files": duplicates,
        "shared_payloads": shared,
        "statement": "Identical hashes mean identical files. A shared payload means the same hidden content was found in several images.",
    }


def analyze_many(items: list, events=None, sensors=None, source: dict | None = None, keep_previews: bool = False) -> dict:
    """items: list of (filename, bytes). Used for browser uploads and the built in demo."""
    entries, skipped = [], []
    previews = {}
    truncated = len(items) > MAX_FILES
    for index, (name, data) in enumerate(items[:MAX_FILES]):
        name = name or f"upload-{index}"
        if not _looks_like_image(data[:8]):
            skipped.append({"filename": name, "reason": "Not a PNG, JPEG, or BMP file"})
            continue
        try:
            report = analyze_bytes(data, name, events, sensors)
        except AnalysisError as exc:
            skipped.append({"filename": name, "reason": _error_text(exc)})
            continue
        item_id = f"f{index:03d}"
        entries.append(_entry(item_id, name.replace("\\", "/").rsplit("/", 1)[-1], name, report))
        if keep_previews:
            previews[item_id] = {"data": data, "format": report["file"]["format"]}
    return _finish(entries, skipped, source or {"type": "upload", "count": len(items)}, truncated, previews)


def _walk(root: Path, recursive: bool):
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            children = sorted(os.scandir(folder), key=lambda d: d.name.lower())
        except PermissionError:
            yield folder, "Permission denied"
            continue
        for child in children:
            if child.is_symlink():
                yield Path(child.path), "Symbolic link not followed"
                continue
            if child.is_dir():
                if recursive and depth < MAX_DEPTH and not child.name.startswith("."):
                    stack.append((Path(child.path), depth + 1))
                continue
            if child.is_file():
                yield Path(child.path), None


def scan_folder(path: str, recursive: bool = False, events=None, sensors=None) -> dict:
    if not path or not str(path).strip():
        raise AnalysisError(400, {"message": "A folder path is required"})
    root = Path(os.path.expanduser(str(path).strip())).resolve()
    if not root.exists():
        raise AnalysisError(404, {"message": f"Folder not found: {root}"})
    if not root.is_dir():
        raise AnalysisError(400, {"message": f"Not a folder: {root}"})

    entries, skipped = [], []
    previews = {}
    count = 0
    truncated = False
    for file_path, problem in _walk(root, recursive):
        rel = str(file_path.relative_to(root)) if file_path != root else file_path.name
        if problem:
            skipped.append({"filename": rel, "reason": problem})
            continue
        if file_path.name.startswith("."):
            continue
        if count >= MAX_FILES:
            truncated = True
            break
        try:
            before_stat = file_path.stat()
            if before_stat.st_size > MAX_BYTES:
                skipped.append({"filename": rel, "reason": "Larger than the 10 MiB limit"})
                continue
            with open(file_path, "rb") as fh:  # read only, never written
                data = fh.read(MAX_BYTES + 1)
        except OSError as exc:
            skipped.append({"filename": rel, "reason": f"Could not read: {exc.strerror or exc}"})
            continue
        if not _looks_like_image(data[:8]):
            skipped.append({"filename": rel, "reason": "Not a PNG, JPEG, or BMP file"})
            continue
        count += 1
        before_hash = hashlib.sha256(data).hexdigest()
        try:
            report = analyze_bytes(data, file_path.name, events, sensors)
        except AnalysisError as exc:
            skipped.append({"filename": rel, "reason": _error_text(exc)})
            continue
        # Re-read from disk so the proof covers the file itself, not just our copy in memory.
        after_stat = file_path.stat()
        after_hash = _sha256_file(file_path)
        unchanged = before_hash == after_hash and before_stat.st_size == after_stat.st_size and before_stat.st_mtime_ns == after_stat.st_mtime_ns
        report["integrity"] = {
            "sha256_at_intake": before_hash,
            "sha256_after_analysis": after_hash,
            "unchanged": unchanged,
            "method": "disk",
            "size_bytes": after_stat.st_size,
            "modified_time": datetime.fromtimestamp(after_stat.st_mtime, timezone.utc).isoformat(),
            "statement": (
                "The file was hashed when it was read from disk and hashed again from disk after every check ran. "
                "Matching hashes and an unchanged modified time show the scan did not alter it. "
                "This cannot show whether the file was changed before it was seized."
            ),
        }
        item_id = f"f{count - 1:03d}"
        entries.append(_entry(item_id, file_path.name, rel, report))
        previews[item_id] = {"path": str(file_path), "format": report["file"]["format"]}
    return _finish(entries, skipped, {"type": "folder", "path": str(root), "recursive": recursive}, truncated, previews)
