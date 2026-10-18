"""Case fingerprint and comparison with an earlier scan.

Case fingerprint: one SHA256 for the whole scan. It is the hash of a sorted
list with one line per image, "path<TAB>file sha256". If any image changes,
is renamed, added, or removed, the case fingerprint changes.

Comparison: load the JSON saved from an earlier scan and line the files up by
path to say exactly which ones changed, went missing, are new, or were renamed.
Older saved JSON (before the case fingerprint existed) still works, because
every scan has always stored each file's path and sha256 in "ranking".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HOW = "SHA256 of the sorted list of 'path<TAB>file sha256' lines, one per image in this scan."


def _key(path: str) -> str:
    return str(path).replace("\\", "/")


def fingerprints(report: dict) -> dict:
    """{path: sha256} for every image in one scan result."""
    if report.get("fingerprints"):
        return {_key(f["path"]): f["sha256"] for f in report["fingerprints"]}
    out = {}
    for entry in report.get("ranking") or []:
        sha = entry.get("sha256") or (entry.get("integrity") or {}).get("sha256_at_intake")
        path = entry.get("path") or entry.get("filename")
        if sha and path:
            out[_key(path)] = sha
    return out


def case_fingerprint(fps: dict) -> str:
    listing = "".join(f"{path}\t{sha}\n" for path, sha in sorted(fps.items()))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def add_case_fingerprint(report: dict) -> dict:
    fps = fingerprints(report)
    report["fingerprints"] = [{"path": path, "sha256": sha} for path, sha in sorted(fps.items())]
    report["case_fingerprint"] = {"sha256": case_fingerprint(fps), "files": len(fps), "how": HOW}
    return report


def combined(data) -> dict:
    reports = data if isinstance(data, list) else [data]
    out = {}
    for report in reports:
        out.update(fingerprints(report))
    return out


def load_previous(path: str) -> dict:
    """Read an earlier saved JSON. Returns {"fingerprints", "case", "when", "file"}."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise RuntimeError(f"No earlier scan file: {file}")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"{file.name} is not a metadex JSON file") from error
    reports = data if isinstance(data, list) else [data]
    if not all(isinstance(r, dict) and "ranking" in r for r in reports):
        raise RuntimeError(f"{file.name} is not a metadex results file")
    fps = combined(reports)
    case = reports[0].get("case_fingerprint", {}).get("sha256") if len(reports) == 1 else None
    return {"fingerprints": fps, "case": case or case_fingerprint(fps), "when": reports[0].get("generated_at"), "file": str(file)}


def compare(old: dict, new: dict) -> dict:
    """Line two {path: sha256} maps up and describe every difference."""
    changed = [{"path": p, "was": old[p], "now": new[p]} for p in sorted(old.keys() & new.keys()) if old[p] != new[p]]
    unchanged = sum(1 for p in old.keys() & new.keys() if old[p] == new[p])
    gone = sorted(old.keys() - new.keys())
    added = sorted(new.keys() - old.keys())
    # Same contents under a new name counts as a rename, not a delete plus an add.
    renamed = []
    by_hash = {}
    for path in added:
        by_hash.setdefault(new[path], []).append(path)
    for path in list(gone):
        candidates = by_hash.get(old[path])
        if candidates:
            target = candidates.pop(0)
            renamed.append({"from": path, "to": target, "sha256": old[path]})
            gone.remove(path)
            added.remove(target)
    return {
        "same": not (changed or gone or added or renamed),
        "case_before": case_fingerprint(old),
        "case_now": case_fingerprint(new),
        "unchanged": unchanged,
        "changed": changed,
        "missing": gone,
        "new": added,
        "renamed": renamed,
    }
