"""The saved report: a plain text file anyone can open and understand.

No technical words where plain ones work. Each photo gets its name, where it
is, how serious the finding is, what was found, and whether a hidden message
could be read. File fingerprints (SHA256 hashes) are listed at the end.
"""

from __future__ import annotations

import os
import textwrap
from datetime import datetime

WIDTH = 80
RULE = "=" * WIDTH
MAX_CLEAN_LISTED = 500

SEVERITY = {
    "high": ("HIGH", "Strong signs of hidden data. Look at these first."),
    "suspicious": ("SUSPICIOUS", "Signs of hidden data worth a closer look."),
    "low": ("LOW", "A small oddity. Probably minor, but noted."),
    "none": ("CLEAN", "Nothing unusual found."),
}


def _wrap(text: str, indent: int, first: str = "") -> list[str]:
    pad = " " * indent
    return textwrap.wrap(
        text,
        WIDTH,
        initial_indent=pad + first,
        subsequent_indent=pad + " " * len(first),
        break_on_hyphens=False,  # never split file paths
        break_long_words=False,
    ) or [pad + first]


def _field_name(name: str) -> str:
    return "the photo's comment section" if name == "COM" else f'the "{name}" information tag'


def _where(message: dict) -> str:
    method = message.get("method")
    where = message.get("where") or ""
    if method == "rgb_lsb_techsteg1":
        return "inside the colors of the pixels"
    if method == "appended_bytes":
        return "in extra data stored after the end of the picture"
    if where == "JPEG comment segment":
        return "in the photo's comment section"
    if where.startswith("EXIF field "):
        return f'in the "{where[len("EXIF field "):]}" information tag'
    if where.startswith("PNG text chunk field ") or where.startswith("PNG text key: "):
        return f'in the "{where.split(" ")[-1]}" text tag'
    return "in " + where if where else ""


def _how(message: dict) -> str:
    encoding = (message.get("encoding") or "").split(" ->")[0]
    if encoding in ("base64", "hex"):
        return f"It was disguised with {encoding} encoding, which we reversed."
    return "It was written as plain text."


def plain_findings(entry: dict) -> list[str]:
    """What was found, in sentences a non technical reader understands."""
    report = entry.get("report") or {}
    contributions = (report.get("suspicion") or {}).get("contributions") or []
    image = report.get("image_analysis") or {}
    fields = [f for f in (image.get("metadata_messages") or {}).get("fields", []) if f.get("flagged")]
    appended = (image.get("appended_data") or {}).get("evidence") or {}
    payloads = (report.get("recovery") or {}).get("payloads") or []
    ext = (report.get("file") or {}).get("extension_check") or {}
    out = []
    for item in contributions:
        rule = item["rule_id"]
        sentence = None
        if rule == "SF-META-002" and fields:
            top = max(fields, key=lambda f: f.get("weight", 0))
            where = _field_name(top["field"])
            kind = top.get("classification", "")
            extra = f" ({len(fields)} information tags were affected.)" if len(fields) > 1 else ""
            if kind.endswith("_text"):
                enc = top.get("encoding")
                how = (
                    f"It was disguised with {enc} encoding so it would not look like words, but we were able to reverse it."
                    if enc in ("base64", "hex")
                    else "It was written in plain words."
                )
                sentence = f"A hidden message was written into {where}. Phones and cameras do not put messages there. {how}{extra}"
            elif kind.endswith("_binary"):
                sentence = (
                    f"{where[0].upper() + where[1:]} contains scrambled data. It looks encrypted, so we could not read it.{extra}"
                )
            elif kind == "oversized":
                sentence = f"{where[0].upper() + where[1:]} is much larger than normal, which can mean something is stored there.{extra}"
            elif kind == "random_looking":
                sentence = f"{where[0].upper() + where[1:]} is full of random looking characters, which can mean hidden data.{extra}"
        elif rule == "SF-APP-001":
            sig = (appended.get("embedded_signature") or {}).get("type")
            n = appended.get("trailing_bytes", 0)
            if not sig:
                sentence = (
                    f"There are {n:,} bytes of extra data stored after the end of the picture. "
                    "A normal photo file stops where the picture ends."
                )
        elif rule == "SF-MAG-001":
            sig = (appended.get("embedded_signature") or {}).get("type") or "file"
            names = [i["name"] for i in appended.get("archive_listing") or []]
            inside = f" It contains: {', '.join(names[:5])}." if names else ""
            sentence = (
                f"A whole second file (a {sig}) is hidden after the end of the picture. "
                f"The photo still opens normally, so you would never notice.{inside} We did not open it."
            )
        elif rule == "SF-ENT-001":
            sentence = "The extra data after the picture looks scrambled, as if it were encrypted or compressed."
        elif rule == "SF-LSB-001":
            sentence = (
                "The colors of the pixels follow a pattern that hiding tools leave behind. "
                "Something may be hidden inside the picture itself, but this check alone cannot read it."
            )
        elif rule == "SF-REC-001":
            if any(p.get("method") == "rgb_lsb_techsteg1" for p in payloads):
                sentence = "A message was hidden inside the colors of the pixels, invisible to the eye. We were able to read it."
        elif rule == "SF-TYPE-001":
            actual, shown = ext.get("actual_format"), ext.get("extension")
            if shown:
                sentence = (
                    f'The file name ends in "{shown}", but the file is really a {actual} photo. '
                    "Someone may have renamed it so it would not look like a picture."
                )
            else:
                sentence = f"The file has no type in its name, but it is really a {actual} photo."
        elif rule == "SF-STRUCT-002":
            sentence = "Parts of the file's internal structure are damaged or do not add up."
        elif rule == "SF-META-001" and not fields:
            sentence = "One of the photo's information tags is unusual."
        if sentence and sentence not in out:
            out.append(sentence)
    return out


HIDDEN_CONTENT_RULES = {"SF-APP-001", "SF-MAG-001", "SF-ENT-001", "SF-LSB-001", "SF-META-001", "SF-META-002", "SF-REC-001"}


def _decoded_block(entry: dict) -> list[str]:
    messages = [m for m in entry.get("messages") or [] if (m.get("text") or "").strip()]
    report = entry.get("report") or {}
    fired = {c["rule_id"] for c in (report.get("suspicion") or {}).get("contributions") or []}
    appended = ((report.get("image_analysis") or {}).get("appended_data") or {}).get("evidence") or {}
    lines = []
    if not messages and not (fired & HIDDEN_CONTENT_RULES):
        lines.append("    Could we read it?  NOTHING TO READ")
        lines += _wrap("No hidden content was found in this file, only the problem described above.", 6)
        return lines
    if not messages and "SF-MAG-001" in fired:
        sig = (appended.get("embedded_signature") or {}).get("type") or "file"
        lines.append("    Could we read it?  NOT OPENED")
        lines += _wrap(
            f"A hidden {sig} was found. For safety it was not opened. "
            "An examiner can extract it with forensic tools on an isolated computer.",
            6,
        )
        return lines
    if messages:
        lines.append("    Could we read it?  YES")
        for index, message in enumerate(messages, start=1):
            label = "Message" if len(messages) == 1 else f"Message {index}"
            text = " ".join(message["text"].split())
            lines += _wrap(f'"{text}"', 6, f"{label}: ")
            where = _where(message)
            also = message.get("also_in") or []
            if also:
                where += f" (the same message is also in {len(also)} other place{'s' if len(also) > 1 else ''})"
            lines += _wrap(f"Found {where}. {_how(message)}", 6)
    else:
        lines.append("    Could we read it?  NO")
        lines += _wrap(
            "Signs of hidden data are there, but the content could not be read. "
            "It may be encrypted or hidden with a method this tool does not decode.",
            6,
        )
    return lines


def build(data, label: str, when: datetime, whole_computer: bool) -> str:
    reports = data if isinstance(data, list) else [data]
    ranking = []
    problems = []
    for report in reports:
        source = report.get("source") or {}
        base = source.get("path") if source.get("type") == "folder" else None
        for entry in report.get("ranking") or []:
            entry = dict(entry)
            path = str(entry.get("path") or entry.get("filename") or "")
            if source.get("type") == "local" and source.get("path"):
                path = source["path"]
            elif base and not os.path.isabs(path):
                path = os.path.join(base, path)
            entry["full_path"] = path
            ranking.append(entry)
        problems += report.get("skipped") or []
    order = {"high": 3, "suspicious": 2, "low": 1, "none": 0}
    ranking.sort(key=lambda e: (-(e.get("score") or 0), -order.get(e.get("level") or "none", 0), str(e.get("path") or "")))
    flagged = [e for e in ranking if (e.get("score") or 0) > 0]
    clean = [e for e in ranking if not (e.get("score") or 0) > 0]
    counts = {key: sum(1 for e in ranking if (e.get("level") or "none") == key) for key in SEVERITY}
    readable = sum(len(e.get("messages") or []) for e in flagged)
    interrupted = any((r.get("summary") or {}).get("interrupted") for r in reports)
    unchanged = all(((e.get("integrity") or {}).get("unchanged", True)) for e in ranking)

    lines = [RULE, "METADEX REPORT", "Hidden data found in photos", RULE, ""]
    lines += _wrap(label, 0, "What was scanned:  ")
    lines.append("When:              " + when.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " "))
    total = len(ranking)
    if total == 0:
        result = "No photos were found."
    elif total == 1:
        result = "This photo shows signs of hidden data." if flagged else "This photo looks clean."
    elif flagged:
        result = f"{len(flagged):,} of {total:,} photo{'s' if total != 1 else ''} show signs of hidden data."
    else:
        result = f"All {total:,} photo{'s' if total != 1 else ''} look clean."
    lines.append("Result:            " + result)
    if interrupted:
        lines += _wrap("The scan was stopped early, so this report covers only the photos checked before it stopped.", 19)
    lines += ["", "How serious is each finding?", ""]
    for key, (word, meaning) in SEVERITY.items():
        lines.append(f"  {word:<12}{counts[key]:>6,}   {meaning}")
    lines += ["", f"Hidden messages we could read: {readable:,}", ""]

    if flagged:
        lines += [RULE, "PHOTOS WITH FINDINGS (most serious first)", RULE]
        for index, entry in enumerate(flagged, start=1):
            word = SEVERITY.get(entry.get("level") or "none", SEVERITY["none"])[0]
            lines += ["", f"{index}. {entry.get('filename')}"]
            lines += _wrap(entry["full_path"], 4, "Location:   ")
            lines.append(f"    Severity:   {word}")
            lines.append("    What we found:")
            findings = plain_findings(entry) or [" ".join((entry.get("top_reasons") or ["Signs of hidden data."])[:1])]
            for finding in findings:
                lines += _wrap(finding, 6, "* ")
            lines += _decoded_block(entry)
        lines.append("")

    if clean:
        lines += [RULE, "CLEAN PHOTOS (nothing unusual found)", RULE, ""]
        if whole_computer or len(clean) > MAX_CLEAN_LISTED:
            lines.append(f"{len(clean):,} photos looked clean. They are not listed one by one.")
        else:
            for entry in clean:
                lines += _wrap(entry["full_path"], 2)
        lines.append("")

    if problems:
        lines += [RULE, "FILES WE COULD NOT CHECK", RULE, ""]
        for item in problems[:100]:
            lines += _wrap(f"{item.get('filename')}: {item.get('reason')}", 2)
        if len(problems) > 100:
            lines.append(f"  ...and {len(problems) - 100:,} more.")
        lines.append("")

    fingerprinted = flagged + ([] if (whole_computer or len(clean) > MAX_CLEAN_LISTED) else clean)
    if fingerprinted:
        lines += [RULE, "FILE FINGERPRINTS (SHA256)", RULE, ""]
        lines += _wrap(
            "A fingerprint is a code calculated from everything inside a file. If even one pixel "
            "changes, the code changes completely. Anyone can recalculate it later to prove a file "
            "is exactly the same as when it was scanned.",
            0,
        )
        lines.append("")
        if unchanged:
            lines += _wrap(
                "Every photo was fingerprinted before and after the scan, and the codes match. "
                "This scan did not change any file.",
                0,
            )
        else:
            lines += _wrap("WARNING: at least one file changed while it was being scanned. Its codes are marked below.", 0)
        lines.append("")
        for entry in fingerprinted:
            integrity = entry.get("integrity") or {}
            mark = "" if integrity.get("unchanged", True) else "   (CHANGED DURING SCAN)"
            lines.append(f"  {entry.get('filename')}{mark}")
            lines.append(f"  {entry.get('sha256') or integrity.get('sha256_at_intake')}")
            lines.append("")
        lines += _wrap("To check a fingerprint yourself on a Mac:  shasum -a 256 \"photo name\"", 0)
        lines += _wrap("On Windows (PowerShell):  Get-FileHash \"photo name\"", 0)
        lines.append("")

    lines += [RULE]
    lines += _wrap(
        "This report lists leads for a person to review. A finding is a reason to look closer, "
        "not proof that anyone did something wrong. No file was opened, run, or changed.",
        0,
    )
    lines.append(RULE)
    return "\n".join(lines) + "\n"
