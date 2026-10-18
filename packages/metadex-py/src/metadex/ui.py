"""Everything the terminal shows: header, progress bar, results, save prompt.

Built on rich, which handles colors, Windows terminals, and narrow windows.
When output is piped to a file, rich drops colors and animations on its own.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

LEVELS = {
    "high": ("▲", "High", "bold red"),
    "suspicious": ("◆", "Suspicious", "bold yellow"),
    "low": ("●", "Low", "bold cyan"),
    "none": ("○", "Clean", "dim"),
}
SHOW_ALL_UP_TO = 20
MAX_MESSAGE_BOXES = 10


# Header and progress


def header(lines: list[str]) -> None:
    body = Text()
    body.append("METADEX", style="bold")
    body.append("  hidden data scanner", style="dim")
    for line in lines:
        body.append("\n")
        body.append_text(Text.from_markup(line))
    console.print(Panel(body, box=box.ROUNDED, border_style="blue", expand=False, padding=(0, 2)))


def count_files(iterator) -> int | None:
    """Count files first so the bar can show a real percentage. Ctrl+C here cancels the scan."""
    total = 0
    with console.status("[dim]Counting files…[/]", spinner="dots") as status:
        last = 0.0
        for _path, problem in iterator:
            if problem:
                continue
            total += 1
            now = time.monotonic()
            if now - last > 0.1:
                status.update(f"[dim]Counting files… {total:,}[/]")
                last = now
    return total


class ScanProgress:
    """A progress bar fed by the scanner's per-file callback."""

    def __init__(self, total: int):
        self.total = max(total, 1)
        self.bar = Progress(
            SpinnerColumn(style="blue"),
            TextColumn("[bold]Scanning"),
            BarColumn(bar_width=None, complete_style="blue", finished_style="green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TextColumn("[dim]files[/]  {task.fields[images]} images  {task.fields[flagged]}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            expand=True,
        )
        self.task = self.bar.add_task("scan", total=self.total, images="0", flagged="[dim]0 flagged[/]")

    def __enter__(self):
        self.bar.__enter__()
        return self

    def __exit__(self, *exc):
        return self.bar.__exit__(*exc)

    def update(self, state: dict) -> None:
        flagged = state["flagged"]
        self.bar.update(
            self.task,
            completed=min(state["files"], self.total),
            images=f"{state['images']:,}",
            flagged=f"[bold red]{flagged:,} flagged[/]" if flagged else "[dim]0 flagged[/]",
        )


# Results


def level_text(level: str) -> Text:
    symbol, word, style = LEVELS.get(level or "none", LEVELS["none"])
    return Text(f"{symbol} {word}", style=style)


def _field_label(name: str) -> str:
    return "the JPEG comment" if name == "COM" else name


def short_reasons(entry: dict, limit: int = 2) -> list[str]:
    """One short phrase per finding, strongest first, for the table."""
    report = entry.get("report") or {}
    contributions = (report.get("suspicion") or {}).get("contributions") or []
    image = report.get("image_analysis") or {}
    fields = [f for f in (image.get("metadata_messages") or {}).get("fields", []) if f.get("flagged")]
    appended = (image.get("appended_data") or {}).get("evidence") or {}
    payloads = (report.get("recovery") or {}).get("payloads") or []
    ext = (report.get("file") or {}).get("extension_check") or {}
    phrases = []
    for item in contributions:
        rule = item["rule_id"]
        phrase = None
        if rule == "SF-META-002" and fields:
            top = max(fields, key=lambda f: f.get("weight", 0))
            label = _field_label(top["field"])
            kind = top.get("classification", "")
            if kind.endswith("_text"):
                how = {"base64": "base64", "hex": "hex", "plain": "plain text"}.get(top.get("encoding"), "text")
                phrase = f"Hidden message in {label} ({how})"
            elif kind.endswith("_binary"):
                phrase = f"Encoded data in {label}, looks encrypted"
            elif kind == "oversized":
                phrase = f"Oversized {label} field"
            elif kind == "random_looking":
                phrase = f"Random looking {label} field"
        elif rule in ("SF-APP-001", "SF-MAG-001"):
            sig = (appended.get("embedded_signature") or {}).get("type")
            names = [i["name"] for i in appended.get("archive_listing") or []]
            if sig:
                phrase = f"{sig} hidden after the image" + (f" ({', '.join(names[:2])})" if names else "")
            else:
                phrase = f"{appended.get('trailing_bytes', 0):,} extra bytes after the image end"
        elif rule == "SF-ENT-001":
            phrase = "Encrypted looking data after the image"
        elif rule == "SF-LSB-001":
            phrase = "Pixel pattern suggests hidden data"
        elif rule == "SF-REC-001":
            pixel = any(p.get("method") == "rgb_lsb_techsteg1" for p in payloads)
            phrase = "Message hidden in the pixels" if pixel else None
        elif rule == "SF-TYPE-001":
            actual, shown = ext.get("actual_format"), ext.get("extension")
            phrase = f"{actual} image disguised as {shown}" if shown else f"{actual} image with no extension"
        elif rule == "SF-STRUCT-002":
            phrase = "Damaged image structure"
        elif rule == "SF-META-001" and not fields:
            phrase = "Unusual metadata field"
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    if not phrases and entry.get("score"):
        phrases = [r.split(". ")[0] for r in (entry.get("top_reasons") or [])[:1]]
    return phrases[:limit]


def tidy(path: str) -> str:
    """Show the home folder as ~ so paths stay short."""
    home = str(Path.home())
    raw = str(path)
    if home and home not in ("/", "") and (raw == home or raw.startswith(home + os.sep)):
        return "~" + raw[len(home):]
    return raw


def _split(entry: dict) -> tuple[str, str]:
    raw = tidy(str(entry.get("path") or entry.get("filename") or ""))
    head, sep, tail = raw.replace("\\", "/").rpartition("/")
    return (head if sep else ""), (tail or raw)


def _path_text(entry: dict, width: int = 44) -> Text:
    folder, name = _split(entry)
    text = Text(name, style="bold")
    if folder:
        if len(folder) > width:
            folder = "…" + folder[-(width - 1):]
        text.append("\n" + folder + "/", style="dim")
    return text


def _short_path(entry: dict) -> str:
    folder, name = _split(entry)
    if not folder:
        return name
    return f"{name}  ({folder if len(folder) <= 40 else '…' + folder[-39:]})"


def _summary_chips(levels: dict) -> Text:
    chips = Text()
    for key in ("high", "suspicious", "low", "none"):
        symbol, word, style = LEVELS[key]
        count = levels.get(key, 0)
        chips.append(f" {symbol} {count:,} {word} ", style=style if count else "dim")
        chips.append("  ")
    return chips


def render(report: dict, whole_computer: bool, elapsed: float) -> None:
    summary = report.get("summary") or {}
    ranking = report.get("ranking") or []
    flagged = [e for e in ranking if (e.get("score") or 0) > 0]
    clean = [e for e in ranking if not (e.get("score") or 0) > 0]

    console.print()
    if summary.get("interrupted"):
        console.print("[bold yellow]Stopped early.[/] [yellow]The results below cover what was scanned before Ctrl+C.[/]\n")
    if not ranking:
        console.print("[bold]No images found there.[/]")
        _footnotes(report, summary, elapsed)
        return

    title = Text()
    if len(ranking) == 1:
        if flagged:
            title.append("This image shows signs of hidden data", style="bold")
        else:
            title.append("This image looks clean", style="bold green")
    elif flagged:
        title.append(f"{len(flagged):,} of {len(ranking):,} images", style="bold")
        title.append(" show signs of hidden data")
    else:
        title.append(f"All {len(ranking):,} images look clean", style="bold green")
    console.print(title)
    console.print(_summary_chips(summary.get("levels") or {}))
    console.print()

    show_clean = not whole_computer and len(ranking) <= SHOW_ALL_UP_TO
    rows = ranking if show_clean else flagged
    if rows:
        table = Table(box=box.SIMPLE_HEAVY, show_edge=False, pad_edge=False, expand=True, header_style="bold dim")
        table.add_column("#", justify="right", style="dim", no_wrap=True, width=4)
        table.add_column("Level", no_wrap=True, width=13)
        table.add_column("File", ratio=2)
        table.add_column("Why", ratio=3)
        # File column gets 2/5 of what is left after # and Level; keep the end of long folder paths.
        file_width = max(16, int((console.width - 4 - 13 - 6) * 2 / 5) - 2)
        for index, entry in enumerate(rows, start=1):
            reasons = short_reasons(entry)
            why = Text(" · ".join(reasons)) if reasons else Text("Nothing unusual found", style="dim")
            table.add_row(str(index), level_text(entry.get("level")), _path_text(entry, file_width), why)
        console.print(table)
    if clean and not show_clean:
        console.print(f"[dim]{len(clean):,} clean images not listed.[/]")

    _message_boxes(flagged)
    _fingerprints(rows if rows else [], report)
    _footnotes(report, summary, elapsed, whole_computer)


def _message_boxes(flagged: list) -> None:
    boxes = []
    for entry in flagged:
        for message in entry.get("messages") or []:
            text = (message.get("text") or "").strip()
            if not text:
                continue
            if len(text) > 400:
                text = text[:400] + "…"
            encoding = message.get("encoding") or "utf-8"
            how = "decoded from " + encoding.split(" ->")[0] if encoding not in ("utf-8", "plain") else "plain text"
            where = message.get("where") or ""
            boxes.append(
                Panel(
                    Text(f"“{text}”", style="bold"),
                    title=Text(_short_path(entry), style="bold"),
                    title_align="left",
                    subtitle=Text(f"{where} · {how}", style="dim"),
                    subtitle_align="left",
                    border_style="magenta",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )
    if not boxes:
        return
    console.print()
    console.print(Text(f"Hidden messages recovered ({len(boxes)})", style="bold magenta"))
    for panel in boxes[:MAX_MESSAGE_BOXES]:
        console.print(panel)
    if len(boxes) > MAX_MESSAGE_BOXES:
        console.print(f"[dim]…and {len(boxes) - MAX_MESSAGE_BOXES} more. Save the results to see them all.[/]")


def _fingerprints(entries: list, report: dict | None = None) -> None:
    """SHA256 of every photo in the table, then one case fingerprint for the whole scan."""
    case = (report or {}).get("case_fingerprint") or {}
    if not entries and not case:
        return
    console.print()
    console.print(Text("File fingerprints (SHA256)", style="bold blue"))
    console.print(
        Text(
            "A unique code calculated from each file. If even one pixel changes, the code changes. "
            "Each file was fingerprinted before and after the scan.",
            style="dim",
        )
    )
    for entry in entries:
        console.print()
        integrity = entry.get("integrity") or {}
        same = integrity.get("unchanged", True)
        digest = entry.get("sha256") or integrity.get("sha256_at_intake") or ""
        line = Text("  ")
        line.append(_split(entry)[1], style="bold")
        line.append("   ")
        line.append("✓ not changed by this scan" if same else "✗ CHANGED during the scan", style="green" if same else "bold red")
        console.print(line, overflow="ellipsis", no_wrap=True)
        console.print(Text("  " + digest, style="cyan"), overflow="fold")
    if case:
        total = case.get("files", 0)
        unlisted = total - len(entries)
        console.print()
        title = Text("  Case fingerprint", style="bold")
        title.append(f"   all {total:,} image{'s' if total != 1 else ''} together", style="dim")
        console.print(title)
        console.print(Text("  " + case["sha256"], style="bold cyan"), overflow="fold")
        note = "One code for the whole set. If any photo changes, is renamed, added, or removed, this code changes."
        if unlisted > 0:
            note += f" It also covers the {unlisted:,} clean images not listed above."
        console.print(Text("  " + note, style="dim"))


def comparison(result: dict, previous: dict) -> None:
    """What changed since an earlier saved scan."""
    when = previous.get("when") or ""
    try:
        when = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone().strftime("%b %d, %Y %I:%M %p")
    except ValueError:
        pass
    console.print()
    header = Text("Compared with ", style="bold")
    header.append(Path(previous["file"]).name, style="bold")
    if when:
        header.append(f"  (scan from {when})", style="dim")
    console.print(header)
    if result["same"]:
        console.print(Text.assemble(("  ✓ ", "bold green"), ("Nothing changed. ", "bold green"),
                                    (f"The case fingerprint matches and all {result['unchanged']:,} files are identical.", "green")))
        return
    console.print(Text.assemble(("  ✗ ", "bold red"), ("Something changed. ", "bold red"),
                                ("The case fingerprint is different:", "red")))
    console.print(Text(f"    before  {result['case_before']}", style="dim"), overflow="fold")
    console.print(Text(f"    now     {result['case_now']}", style="dim"), overflow="fold")
    console.print()
    rows = []
    for item in result["changed"]:
        rows.append((Text("✗ CHANGED ", style="bold red"), item["path"],
                     f"contents are different now (was {item['was'][:12]}…, now {item['now'][:12]}…)"))
    for path in result["missing"]:
        rows.append((Text("! MISSING ", style="bold yellow"), path, "was in the earlier scan, not found now"))
    for path in result["new"]:
        rows.append((Text("+ NEW     ", style="bold cyan"), path, "not in the earlier scan"))
    for item in result["renamed"]:
        rows.append((Text("↻ RENAMED ", style="bold magenta"), f"{item['from']} → {item['to']}", "same contents, new name"))
    for label, path, why in rows[:200]:
        line = Text("  ")
        line.append_text(label)
        line.append(" " + tidy(path), style="bold")
        console.print(line)
        console.print(Text("              " + why, style="dim"))
    if len(rows) > 200:
        console.print(f"[dim]  …and {len(rows) - 200:,} more. Save the results to see them all.[/]")
    if result["unchanged"]:
        console.print(Text(f"  {result['unchanged']:,} other files are unchanged.", style="dim"))


def _footnotes(report: dict, summary: dict, elapsed: float, whole_computer: bool = False) -> None:
    lines = []
    stats = []
    images = summary.get("scanned", 0)
    stats.append(f"{images:,} image{'s' if images != 1 else ''} checked")
    other = summary.get("other_files") or 0
    if other:
        stats.append(f"{other:,} other file{'s' if other != 1 else ''} skipped")
    problems = summary.get("problems") or 0
    if problems:
        stats.append(f"{problems:,} could not be read")
    stats.append(f"{elapsed:.1f}s")
    lines.append(Text(" · ".join(stats), style="dim"))

    integrity = report.get("integrity") or {}
    if images:
        if integrity.get("all_unchanged", True):
            lines.append(Text.assemble(("✓ ", "green"), ("Evidence unchanged: ", "green"), ("every file hashed before and after the scan", "dim")))
        else:
            lines.append(Text("✗ A file changed during the scan. Save the results to see which one.", style="bold red"))

    duplicates = [d for d in (report.get("correlations") or {}).get("duplicate_files", []) if len(d.get("files", [])) > 1]
    if duplicates and not whole_computer:
        names = "; ".join(" = ".join(d["files"][:3]) for d in duplicates[:3])
        more = f" (+{len(duplicates) - 3} more)" if len(duplicates) > 3 else ""
        lines.append(Text(f"Identical files: {names}{more}", style="dim"))
    lines.append(Text("A level is a lead for an examiner to review, not proof.", style="dim italic"))
    console.print()
    for line in lines:
        console.print(line)


def explanation(text: str | None, error: str | None) -> None:
    console.print()
    if error:
        console.print(f"[yellow]Gemini:[/] {error}")
        return
    console.print(Panel(Text(text or ""), title="Gemini explains", title_align="left", border_style="green", box=box.ROUNDED))


# Saving


def default_name(kind: str = "json") -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"metadex-report-{stamp}.html" if kind == "html" else f"metadex-results-{stamp}.json"


FORMATS = {".json": "json", ".html": "html", ".htm": "html", ".txt": "txt"}


def save(data, name: str, context: dict | None = None) -> Path:
    """Save as JSON (default), an HTML report (.html), or a plain text report (.txt), chosen by the file name."""
    path = Path(name).expanduser()
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        kind = "json"
        path = path.with_name(path.name + ".json")
    if path.exists():
        stem, suffix, n = path.stem, path.suffix, 2
        while path.exists():
            path = path.with_name(f"{stem}-{n}{suffix}")
            n += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    context = context or {}
    args = dict(
        label=context.get("label", "Photos"),
        when=context.get("when") or datetime.now(),
        whole_computer=context.get("whole_computer", False),
    )
    if kind == "json":
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    elif kind == "html":
        from metadex.html_report import build as build_html

        with console.status("[dim]Building the HTML report…[/]", spinner="dots"):
            path.write_text(build_html(data, elapsed=context.get("elapsed"), **args), encoding="utf-8")
    else:
        from metadex.report import build as build_text

        path.write_text(build_text(data, **args), encoding="utf-8")
    return path.resolve()


def saved(path: Path) -> None:
    size = path.stat().st_size
    shown = f"{size / 1024 / 1024:,.1f} MB" if size >= 1024 * 1024 else (f"{size / 1024:,.0f} KB" if size >= 1024 else f"{size} bytes")
    console.print(Text.assemble(("✓ ", "green"), ("Saved to ", "green"), (tidy(str(path)), "bold"), (f"  ({shown})", "dim")))
    if path.suffix.lower() in (".html", ".htm"):
        console.print(Text("  Open it in any web browser. On a Mac: open " + _quote(tidy(str(path))), style="dim"))


def _quote(text: str) -> str:
    return f'"{text}"' if " " in text else text


CHOICES = {
    "1": "json", "json": "json", "j": "json",
    "2": "html", "html": "html", "h": "html", "report": "html",
    "3": "both", "both": "both", "b": "both", "y": "both", "yes": "both", "yeah": "both", "yep": "both",
    "": "no", "n": "no", "no": "no", "nope": "no", "skip": "no", "0": "no",
}


def _choose() -> str:
    console.print("[bold]Save these results?[/]")
    console.print("  [bold]1[/]  JSON   [dim]all the data, for tools and for --compare later[/]")
    console.print("  [bold]2[/]  HTML   [dim]a visual report you open in a browser[/]")
    console.print("  [bold]3[/]  Both")
    while True:
        answer = console.input("[bold]Type 1, 2, or 3, or press Enter to skip:[/] ").strip().lower()
        if answer in CHOICES:
            return CHOICES[answer]
        console.print("[yellow]  Just type 1, 2, or 3 (or json, html, both), or press Enter to skip.[/]")


def ask_to_save(data, context: dict | None = None) -> None:
    console.print()
    try:
        kind = _choose()
        if kind == "no":
            console.print("[dim]  Not saved.[/]")
            return
        stamp_name = default_name("html" if kind == "html" else "json")
        default = stamp_name if kind != "both" else stamp_name.rsplit(".", 1)[0].replace("metadex-results", "metadex-report")
        hint = " [dim](without .json or .html)[/]" if kind == "both" else ""
        name = Prompt.ask(f"File name{hint}", default=default, console=console).strip() or default
    except (EOFError, KeyboardInterrupt):
        console.print()
        return
    base, suffix = (name.rsplit(".", 1) + [""])[:2] if "." in Path(name).name else (name, "")
    suffix = "." + suffix.lower() if suffix else ""
    if kind == "both":
        stem = base if suffix in FORMATS else name
        saved(save(data, stem + ".json", context))
        saved(save(data, stem + ".html", context))
        return
    want = ".html" if kind == "html" else ".json"
    if suffix not in FORMATS:
        name += want
    saved(save(data, name, context))
