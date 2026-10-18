"""Scan whole folders, or the whole computer, for the terminal command.

The website's /api/scan-folder keeps its 500 file limit. The terminal has no
limit: it walks every folder you give it (or every drive), checks the first
bytes of every file so a photo renamed to .txt is still found, and runs each
image through the same analyze_bytes as everything else.

Files are opened read only and hashed again after analysis, exactly like
scan_folder. Nothing found is executed or written.
"""
from __future__ import annotations

import hashlib
import os
import string
import sys
from pathlib import Path

from app.analyze import MAX_BYTES, AnalysisError, analyze_bytes
from app.batch import _entry, _error_text, _finish, _looks_like_image, _sha256_file

MAX_PROBLEMS_LISTED = 200

# Folder names skipped anywhere during a whole computer scan: code, caches, and package stores.
SKIP_NAMES = {
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    ".cache",
    ".npm",
    ".gradle",
    ".m2",
    "caches",
    "system volume information",
}
# Hidden folders are skipped during a whole computer scan, except the trash, where deleted evidence sits.
KEEP_HIDDEN = {".trash", ".trashes", "$recycle.bin"}
# App and system bundles on macOS hold thousands of icons, not user files.
SKIP_SUFFIXES = (".app", ".framework", ".bundle", ".kext", ".plugin", ".appex", ".xpc")


def _system_prefixes() -> list[str]:
    home = str(Path.home())
    if sys.platform == "darwin":
        items = ["/System", "/Library", "/private", "/dev", "/Volumes", "/cores", "/usr", "/bin", "/sbin", "/opt",
                 "/etc", "/var", "/tmp", "/Applications", "/Network", "/net", "/home",
                 os.path.join(home, "Library")]
    elif os.name == "nt":
        items = []
        for root in whole_computer_roots():
            items += [os.path.join(root, name) for name in ("Windows", "Program Files", "Program Files (x86)",
                                                            "ProgramData", "Recovery", "PerfLogs", "$WinREAgent")]
        items.append(os.path.join(home, "AppData"))
    else:
        items = ["/proc", "/sys", "/dev", "/run", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc",
                 "/var", "/boot", "/snap", "/opt", "/tmp", "/lost+found"]
    return [os.path.normcase(os.path.abspath(item)) for item in items]


def whole_computer_roots() -> list[str]:
    """Every local drive on Windows, or / elsewhere."""
    if os.name != "nt":
        return ["/"]
    roots = []
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        drive_type = None
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        # 2 removable, 3 fixed disk. Network shares (4) and CD drives (5) are left out.
        if drive_type is not None and drive_type(root) not in (2, 3):
            continue
        roots.append(root)
    return roots


def _skip_dir(path: str, name: str, prefixes: list[str]) -> bool:
    lowered = name.lower()
    if lowered in KEEP_HIDDEN:
        return False
    if lowered in SKIP_NAMES or lowered.endswith(SKIP_SUFFIXES):
        return True
    if name.startswith(".") or name.startswith("$"):
        return True
    norm = os.path.normcase(os.path.abspath(path))
    return any(norm == prefix or norm.startswith(prefix + os.sep) for prefix in prefixes)


def iter_files(roots: list[str], recursive: bool = True, whole_computer: bool = False):
    """Yield (path, problem) for every regular file. Symbolic links are never followed."""
    prefixes = _system_prefixes() if whole_computer else []
    for root in roots:
        stack = [root]
        while stack:
            folder = stack.pop()
            try:
                children = sorted(os.scandir(folder), key=lambda d: d.name.lower())
            except PermissionError:
                yield folder, "Permission denied"
                continue
            except OSError as exc:
                yield folder, f"Could not open: {exc.strerror or exc}"
                continue
            subfolders = []
            for child in children:
                try:
                    if child.is_symlink():
                        continue
                    if child.is_dir():
                        if not recursive:
                            continue
                        if whole_computer:
                            if _skip_dir(child.path, child.name, prefixes):
                                continue
                        elif child.name.startswith("."):
                            continue
                        subfolders.append(child.path)
                    elif child.is_file() and not child.name.startswith("."):
                        yield child.path, None
                except OSError:
                    continue
            # Reverse so folders come out in alphabetical order from the stack.
            stack.extend(reversed(subfolders))


def sweep(
    roots: list[str],
    recursive: bool = True,
    whole_computer: bool = False,
    keep_reports: str = "all",
    progress=None,
) -> dict:
    """Scan every image under roots. keep_reports is "all" or "flagged" (keeps memory small on a full disk scan)."""
    resolved = [str(Path(os.path.expanduser(r)).resolve()) for r in roots]
    single_root = resolved[0] if len(resolved) == 1 else None
    state = {"files": 0, "images": 0, "other": 0, "flagged": 0, "current": "", "interrupted": False}
    entries, problems = [], []
    problem_count = 0

    def note(name: str, reason: str) -> None:
        nonlocal problem_count
        problem_count += 1
        if len(problems) < MAX_PROBLEMS_LISTED:
            problems.append({"filename": name, "reason": reason})

    try:
        for file_path, problem in iter_files(resolved, recursive, whole_computer):
            if problem:
                note(file_path, problem)
                continue
            state["files"] += 1
            state["current"] = file_path
            if progress:
                progress(state)
            shown = os.path.relpath(file_path, single_root) if single_root and not whole_computer else file_path
            try:
                before = os.stat(file_path)
                with open(file_path, "rb") as fh:  # read only, never written
                    head = fh.read(8)
                    if not _looks_like_image(head):
                        state["other"] += 1
                        continue
                    if before.st_size > MAX_BYTES:
                        note(shown, "Image larger than the 10 MiB limit")
                        continue
                    data = head + fh.read(MAX_BYTES + 1 - len(head))
            except OSError as exc:
                if Path(file_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
                    note(shown, f"Could not read: {exc.strerror or exc}")
                continue
            state["images"] += 1
            before_hash = hashlib.sha256(data).hexdigest()
            try:
                report = analyze_bytes(data, os.path.basename(file_path), None, None)
            except AnalysisError as exc:
                note(shown, _error_text(exc))
                continue
            try:
                after = os.stat(file_path)
                after_hash = _sha256_file(Path(file_path))
            except OSError:
                after, after_hash = before, before_hash
            unchanged = before_hash == after_hash and before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
            report["integrity"] = {
                "sha256_at_intake": before_hash,
                "sha256_after_analysis": after_hash,
                "unchanged": unchanged,
                "method": "disk",
                "statement": (
                    "The file was hashed when it was read from disk and hashed again after every check ran. "
                    "Matching hashes show the scan did not alter it. This cannot show whether it was changed before."
                ),
            }
            entry = _entry(f"f{state['images'] - 1:06d}", os.path.basename(file_path), shown, report)
            if entry["score"] > 0:
                state["flagged"] += 1
            elif keep_reports == "flagged":
                entry.pop("report", None)
            entries.append(entry)
    except KeyboardInterrupt:
        state["interrupted"] = True

    if whole_computer:
        source = {"type": "computer", "roots": resolved, "skipped_system_folders": True}
    elif single_root:
        source = {"type": "folder", "path": single_root, "recursive": recursive}
    else:
        source = {"type": "folders", "paths": resolved, "recursive": recursive}
    result = _finish(entries, problems, source, state["interrupted"])
    result["summary"]["files_checked"] = state["files"]
    result["summary"]["other_files"] = state["other"]
    result["summary"]["problems"] = problem_count
    result["summary"]["interrupted"] = state["interrupted"]
    if state["interrupted"]:
        result["summary"]["headline"] += " (stopped early)"
    return result
