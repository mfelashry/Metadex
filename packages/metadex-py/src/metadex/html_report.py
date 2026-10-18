"""A single file HTML report in the Metadex website style.

Everything is inside one .html file: styles, the logo, and small previews of
the photos, so it can be emailed or opened on any computer without the
original pictures. Every file name, path, and recovered message is escaped,
because hidden messages are untrusted text.
"""

from __future__ import annotations

import base64
import html
import io
import os
from datetime import datetime
from importlib import resources

from metadex.report import SEVERITY, _how, _where, plain_findings

MAX_PREVIEWS = 200
MAX_CLEAN_SHOWN = 300

LEVEL_MARK = {"high": "▲ High", "suspicious": "◆ Suspicious", "low": "● Low", "none": "○ Clean"}

RULE_NAMES = {
    "SF-STRUCT-002": "File structure is intact",
    "SF-APP-001": "No extra data after the end of the picture",
    "SF-MAG-001": "No second file hidden after the picture",
    "SF-ENT-001": "No scrambled data after the picture",
    "SF-LSB-001": "Pixel colors look natural",
    "SF-META-001": "Information tags look normal",
    "SF-META-002": "No messages hidden in the information tags",
    "SF-TYPE-001": "File name matches what the file really is",
    "SF-REC-001": "Hidden content that could be read",
}
RESULT_WORDS = {
    "clear": ("Passed", "ok"),
    "indicator": ("Problem found", "bad"),
    "recovered": ("Hidden content read", "bad"),
    "anomaly": ("Problem found", "bad"),
    "not_applicable": ("Not used for this file type", "na"),
    "not_assessed": ("Not checked", "na"),
    "info": ("Info", "na"),
}

GLOSSARY = [
    ("Information tags (EXIF)", "Notes a phone or camera stores inside a photo, like the camera model and the date. You cannot see them in the picture, which is why they can be used to hide messages."),
    ("Base64 and hex", "Ways of writing text as a jumble of letters and numbers. They make a message look like nonsense, but anyone with the right tool can turn it back. They are a disguise, not a lock."),
    ("Encrypted", "Locked with a secret key. Without the key the content cannot be read, so the tool can only report that it is there."),
    ("Extra data after the picture", "Every photo file has a marker that says where the picture ends. Anything stored after that marker is invisible when you open the photo."),
    ("Pixel pattern", "Data can be hidden by changing the tiniest bit of each pixel's color. The eye cannot see it, but it leaves a statistical pattern."),
    ("Fingerprint (SHA256)", "A 64 character code calculated from everything inside a file. Change one pixel and the code changes completely. Matching codes prove a file is identical."),
    ("Case fingerprint", "One code made from the fingerprints of every photo in the scan. If any photo changes, is added, removed, or renamed, it changes."),
]


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _logo() -> str:
    try:
        data = resources.files("metadex").joinpath("assets/brand-m.png").read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ""


def _preview(path: str, size: int) -> str:
    """A small JPEG preview as a data URL. Read only; returns "" if the file cannot be read."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.thumbnail((size, size))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _size(n) -> str:
    if not n:
        return ""
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def _camera(entry: dict) -> list[str]:
    report = entry.get("report") or {}
    rows = ((report.get("image_analysis") or {}).get("metadata") or {}).get("evidence", {}).get("exif") or []
    tags = {r.get("tag"): r.get("value") for r in rows}
    facts = []
    camera = " ".join(v for v in (tags.get("Make"), tags.get("Model")) if v)
    if camera:
        facts.append(f"Taken with {camera}")
    when = tags.get("DateTime")
    if when:
        facts.append(f"Date in the photo: {when}")
    return facts


def read_status(entry: dict) -> dict:
    """Could the hidden content be read? Returns state, title, explanation, messages."""
    from metadex.report import HIDDEN_CONTENT_RULES

    messages = [m for m in entry.get("messages") or [] if (m.get("text") or "").strip()]
    report = entry.get("report") or {}
    fired = {c["rule_id"] for c in (report.get("suspicion") or {}).get("contributions") or []}
    appended = ((report.get("image_analysis") or {}).get("appended_data") or {}).get("evidence") or {}
    if messages:
        return {"state": "yes", "title": "Yes, we read it", "explanation": "", "messages": messages}
    if not (fired & HIDDEN_CONTENT_RULES):
        return {"state": "nothing", "title": "Nothing to read",
                "explanation": "No hidden content was found in this file, only the problem described above.", "messages": []}
    if "SF-MAG-001" in fired:
        sig = (appended.get("embedded_signature") or {}).get("type") or "file"
        names = [i["name"] for i in appended.get("archive_listing") or []]
        inside = f" It lists these files inside: {', '.join(names[:8])}." if names else ""
        return {"state": "closed", "title": "Found, not opened",
                "explanation": f"A hidden {sig} was found. For safety it was not opened.{inside} "
                               "An examiner can extract it with forensic tools on an isolated computer.", "messages": []}
    return {"state": "no", "title": "Found, but could not be read",
            "explanation": "Signs of hidden data are there, but the content could not be read. "
                           "It may be encrypted or hidden with a method this tool does not decode.", "messages": []}


def _checks(entry: dict) -> str:
    rules = (entry.get("report") or {}).get("rules") or []
    rows = []
    for rule in rules:
        if rule.get("id") not in RULE_NAMES:
            continue
        word, kind = RESULT_WORDS.get(rule.get("result"), (rule.get("result", ""), "na"))
        rows.append(
            f'<tr><td>{_e(RULE_NAMES[rule["id"]])}</td><td><span class="result {kind}">{_e(word)}</span></td>'
            f'<td class="muted">{_e(rule.get("detail"))}</td></tr>'
        )
    if not rows:
        return ""
    return ('<table class="checks"><thead><tr><th>Check</th><th>Result</th><th>Details</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _tags(entry: dict) -> str:
    fields = ((entry.get("report") or {}).get("image_analysis") or {}).get("metadata_messages", {}).get("fields") or []
    if not fields:
        return ""
    rows = []
    for field in fields[:30]:
        value = field.get("decoded") or field.get("preview") or ""
        flag = '<span class="result bad">Suspicious</span>' if field.get("flagged") else '<span class="result ok">Normal</span>'
        name = "Comment section" if field.get("field") == "COM" else field.get("field")
        rows.append(f"<tr><td>{_e(name)}</td><td class=\"mono wrap\">{_e(value[:300])}</td><td>{flag}</td></tr>")
    return ('<table class="checks"><thead><tr><th>Information tag</th><th>What it says</th><th></th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _photo_card(entry: dict, index: int, image: str) -> str:
    level = entry.get("level") or "none"
    status = read_status(entry)
    findings = plain_findings(entry) or [" ".join((entry.get("top_reasons") or ["Signs of hidden data."])[:1])]
    integrity = entry.get("integrity") or {}
    facts = [entry.get("format"), _size(entry.get("size_bytes"))]
    if entry.get("width") and entry.get("height"):
        facts.append(f'{entry["width"]} × {entry["height"]} pixels')
    facts = " · ".join(_e(f) for f in facts if f)
    camera = "".join(f"<li>{_e(f)}</li>" for f in _camera(entry))
    messages = ""
    for message in status["messages"]:
        where = _where(message)
        also = message.get("also_in") or []
        extra = f" The same message is also in {len(also)} other place{'s' if len(also) > 1 else ''}." if also else ""
        messages += (f'<blockquote><p>{_e(" ".join(message["text"].split()))}</p>'
                     f'<footer>Found {_e(where)}. {_e(_how(message))}{_e(extra)}</footer></blockquote>')
    explanation = f'<p class="muted">{_e(status["explanation"])}</p>' if status["explanation"] else ""
    pic = f'<img class="hero" src="{image}" alt="{_e(entry.get("filename"))}">' if image else '<div class="hero empty">Preview not available</div>'
    same = integrity.get("unchanged", True)
    return f"""
<article class="photo" id="photo-{index}">
  {pic}
  <div class="photo-heading">
    <h3>{_e(entry.get("filename"))}</h3>
    <span class="level level-{_e(level)}">{_e(LEVEL_MARK.get(level, level))}</span>
  </div>
  <p class="location">{_e(entry.get("full_path"))}</p>
  <p class="facts">{facts}</p>
  {f'<ul class="camera">{camera}</ul>' if camera else ''}
  <section>
    <h4>What we found</h4>
    <ul class="findings">{''.join(f'<li>{_e(f)}</li>' for f in findings)}</ul>
  </section>
  <section>
    <h4>Could we read it? <span class="read read-{status['state']}">{_e(status['title'])}</span></h4>
    {messages}{explanation}
  </section>
  <section class="print-keep">
    <h4>Fingerprint</h4>
    <p class="mono wrap">{_e(entry.get("sha256"))}</p>
    <p class="muted small">{'✓ Not changed by this scan: the fingerprint was the same before and after.' if same else '✗ This file changed while it was being scanned.'}</p>
  </section>
  <details>
    <summary>Every check we ran on this photo</summary>
    {_checks(entry)}
    {_tags(entry)}
  </details>
</article>"""


def _comparison(result: dict | None) -> str:
    if not result:
        return ""
    name = os.path.basename(result.get("compared_with") or "an earlier scan")
    if result["same"]:
        body = (f'<p class="big ok-text">✓ Nothing changed.</p><p>The case fingerprint matches <strong>{_e(name)}</strong> '
                f'and all {result["unchanged"]:,} files are identical.</p>')
    else:
        rows = []
        for item in result["changed"]:
            rows.append(("✗ Changed", item["path"], "The contents are different now."))
        for path in result["missing"]:
            rows.append(("! Missing", path, "Was in the earlier scan, not found now."))
        for path in result["new"]:
            rows.append(("+ New", path, "Was not in the earlier scan."))
        for item in result["renamed"]:
            rows.append(("↻ Renamed", f'{item["from"]} → {item["to"]}', "Same contents, new name."))
        table = "".join(f'<tr><td><strong>{_e(a)}</strong></td><td class="wrap">{_e(b)}</td><td class="muted">{_e(c)}</td></tr>' for a, b, c in rows)
        body = (f'<p class="big bad-text">✗ Something changed since {_e(name)}.</p>'
                f'<p class="muted mono wrap">Before: {_e(result["case_before"])}<br>Now: {_e(result["case_now"])}</p>'
                f'<table class="checks"><thead><tr><th>Change</th><th>File</th><th>Meaning</th></tr></thead><tbody>{table}</tbody></table>'
                f'<p class="muted">{result["unchanged"]:,} other files are unchanged.</p>')
    return f'<section class="block" id="compare"><p class="eyebrow">Compared with an earlier scan</p>{body}</section>'


def build(data, label: str, when: datetime, whole_computer: bool, elapsed: float | None = None) -> str:
    from metadex import __version__

    reports = data if isinstance(data, list) else [data]
    ranking, problems = [], []
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
    ranking.sort(key=lambda e: (-(e.get("score") or 0), -order.get(e.get("level") or "none", 0), e["full_path"]))
    flagged = [e for e in ranking if (e.get("score") or 0) > 0]
    clean = [e for e in ranking if not (e.get("score") or 0) > 0]
    counts = {k: sum(1 for e in ranking if (e.get("level") or "none") == k) for k in SEVERITY}
    readable = sum(len(e.get("messages") or []) for e in flagged)
    unchanged = all((e.get("integrity") or {}).get("unchanged", True) for e in ranking)
    interrupted = any((r.get("summary") or {}).get("interrupted") for r in reports)
    case = (reports[0].get("case_fingerprint") or {}) if len(reports) == 1 else {}
    comparison = reports[0].get("comparison") if len(reports) == 1 else None
    total = len(ranking)

    if total == 0:
        headline = "No photos were found."
    elif total == 1:
        headline = "This photo shows signs of hidden data." if flagged else "This photo looks clean."
    elif flagged:
        headline = f"{len(flagged):,} of {total:,} photos show signs of hidden data."
    else:
        headline = f"All {total:,} photos look clean."

    meta = [label, when.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")]
    if elapsed is not None:
        meta.append(f"took {elapsed:.1f} seconds")

    # Summary cards
    cards = [
        (f"{total:,}", "photos checked"),
        (f"{len(flagged):,}", "with findings"),
        (f"{readable:,}", "hidden messages read"),
        ("✓" if unchanged else "✗", "evidence unchanged" if unchanged else "a file changed during the scan"),
    ]
    cards_html = "".join(f'<div class="card"><strong>{_e(a)}</strong><span>{_e(b)}</span></div>' for a, b in cards)

    # Severity
    bar = "".join(
        f'<span class="seg seg-{k}" style="flex:{counts[k]}" title="{_e(SEVERITY[k][0])}: {counts[k]}"></span>'
        for k in SEVERITY if counts[k]
    )
    sev_rows = "".join(
        f'<li><span class="level level-{k}">{_e(LEVEL_MARK[k])}</span><strong>{counts[k]:,}</strong><span class="muted">{_e(SEVERITY[k][1])}</span></li>'
        for k in SEVERITY
    )

    # Photos with findings: side list + cards
    previews_left = MAX_PREVIEWS
    side, cards_list = [], []
    for i, entry in enumerate(flagged, start=1):
        image = ""
        if previews_left > 0:
            image = _preview(entry["full_path"], 600)
            previews_left -= 1
        thumb = f'<img src="{image}" alt="">' if image else '<span class="thumb-empty"></span>'
        side.append(
            f'<a href="#photo-{i}">{thumb}<span><strong>{_e(entry.get("filename"))}</strong>'
            f'<small>{_e(LEVEL_MARK.get(entry.get("level") or "none"))}</small></span></a>'
        )
        cards_list.append(_photo_card(entry, i, image))
    findings_html = ""
    if flagged:
        findings_html = f"""
<section class="block" id="findings">
  <p class="eyebrow">Photos with findings, most serious first</p>
  <div class="split">
    <nav class="side" aria-label="Photos with findings">{''.join(side)}</nav>
    <div class="cards">{''.join(cards_list)}</div>
  </div>
</section>"""

    clean_html = ""
    if clean:
        if whole_computer or len(clean) > MAX_CLEAN_SHOWN:
            inner = f"<p>{len(clean):,} photos looked clean. They are not shown one by one.</p>"
        else:
            tiles = []
            for entry in clean:
                image = _preview(entry["full_path"], 220) if previews_left > 0 else ""
                previews_left -= 1
                pic = f'<img src="{image}" alt="">' if image else '<span class="thumb-empty"></span>'
                tiles.append(f'<figure>{pic}<figcaption>{_e(entry.get("filename"))}</figcaption></figure>')
            inner = f'<div class="grid">{"".join(tiles)}</div>'
        clean_html = f'<section class="block" id="clean"><p class="eyebrow">Clean photos: nothing unusual found</p>{inner}</section>'

    listed = flagged + ([] if (whole_computer or len(clean) > MAX_CLEAN_SHOWN) else clean)
    fp_rows = "".join(
        f'<tr><td class="wrap">{_e(e.get("filename"))}</td><td class="mono wrap">{_e(e.get("sha256"))}</td>'
        f'<td>{"✓ same" if (e.get("integrity") or {}).get("unchanged", True) else "✗ changed"}</td></tr>'
        for e in listed
    )
    case_html = ""
    if case:
        hidden = case.get("files", 0) - len(listed)
        more = f" It also covers the {hidden:,} clean photos not listed above." if hidden > 0 else ""
        case_html = (f'<div class="case"><p class="eyebrow">Case fingerprint: all {case.get("files", 0):,} photos together</p>'
                     f'<p class="mono wrap big">{_e(case.get("sha256"))}</p>'
                     f'<p class="muted">One code for the whole set. If any photo changes, is renamed, added, or removed, this code changes.{_e(more)}</p></div>')
    fingerprints_html = f"""
<section class="block" id="fingerprints">
  <p class="eyebrow">File fingerprints (SHA256)</p>
  <p>A fingerprint is a code calculated from everything inside a file. If even one pixel changes, the code changes completely.
  Every photo was fingerprinted before and after the scan{', and the codes match: this scan did not change any file.' if unchanged else '. At least one file changed while it was being scanned.'}</p>
  {case_html}
  {f'<table class="checks fp"><thead><tr><th>Photo</th><th>Fingerprint</th><th>After the scan</th></tr></thead><tbody>{fp_rows}</tbody></table>' if fp_rows else ''}
  <p class="muted small">Check a fingerprint yourself. Mac: <code>shasum -a 256 "photo name"</code> · Windows PowerShell: <code>Get-FileHash "photo name"</code></p>
</section>"""

    problems_html = ""
    if problems:
        items = "".join(f'<li><span class="wrap">{_e(p.get("filename"))}</span> <span class="muted">{_e(p.get("reason"))}</span></li>' for p in problems[:100])
        more = f"<p class=\"muted\">…and {len(problems) - 100:,} more.</p>" if len(problems) > 100 else ""
        problems_html = f'<section class="block"><p class="eyebrow">Files we could not check</p><ul class="plain">{items}</ul>{more}</section>'

    glossary = "".join(f"<div><dt>{_e(a)}</dt><dd>{_e(b)}</dd></div>" for a, b in GLOSSARY)
    stopped = '<p class="notice">The scan was stopped early, so this report covers only the photos checked before it stopped.</p>' if interrupted else ""
    logo = _logo()
    brand = f'<img class="brand-mark" src="{logo}" alt=""><span>ETADEX</span>' if logo else "<span>METADEX</span>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Metadex report · {_e(headline)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="app-shell" id="shell">
<header class="site-nav">
  <span class="brand" aria-label="Metadex">{brand}</span>
  <div class="nav-controls">
    <button class="pill" type="button" onclick="window.print()">Print or save as PDF</button>
    <button class="pill" type="button" id="theme">Dark mode</button>
  </div>
</header>
<main>
  <section class="hero-block">
    <p class="eyebrow">Hidden data scan report</p>
    <h1>{_e(headline)}</h1>
    <p class="meta">{' · '.join(_e(m) for m in meta)}</p>
    {stopped}
    <div class="cards-row">{cards_html}</div>
  </section>
  {_comparison(comparison)}
  <section class="block">
    <p class="eyebrow">How serious is each finding?</p>
    <div class="bar" aria-hidden="true">{bar}</div>
    <ul class="severity">{sev_rows}</ul>
  </section>
  {findings_html}
  {clean_html}
  {problems_html}
  {fingerprints_html}
  <section class="block">
    <p class="eyebrow">Words used in this report</p>
    <dl class="glossary">{glossary}</dl>
  </section>
</main>
<footer class="page-footer">
  <p>This report lists leads for a person to review. A finding is a reason to look closer, not proof that anyone did something wrong. No file was opened, run, or changed.</p>
  <p class="muted small">Made by Metadex {_e(__version__)} on {_e(when.strftime("%Y-%m-%d %H:%M"))}.</p>
</footer>
</div>
<script>
(function () {{
  var shell = document.getElementById("shell");
  var saved = null;
  try {{ saved = localStorage.getItem("metadex-report-theme"); }} catch (e) {{}}
  var dark = saved ? saved === "dark" : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var button = document.getElementById("theme");
  function apply() {{
    shell.setAttribute("data-theme", dark ? "dark" : "light");
    button.textContent = dark ? "Light mode" : "Dark mode";
  }}
  apply();
  button.addEventListener("click", function () {{
    dark = !dark;
    apply();
    try {{ localStorage.setItem("metadex-report-theme", dark ? "dark" : "light"); }} catch (e) {{}}
  }});
}})();
</script>
</body>
</html>
"""


CSS = """
:root { font-family: "Fredoka", ui-rounded, system-ui, sans-serif; font-synthesis: none; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; min-width: 320px; background: #fff; }
.app-shell { --bg: #fff; --fg: #151515; --muted: #696969; --soft: #f6f6f6; --line: #e2e2e2; --subtle: #999;
  min-height: 100vh; background: var(--bg); color: var(--fg); transition: background .35s, color .35s; }
.app-shell[data-theme="dark"] { --bg: #000; --fg: #f7f7f7; --muted: #aaa; --soft: #0d0d0d; --line: #303030; --subtle: #777; }
.app-shell[data-theme="dark"] .brand-mark { filter: invert(1); }
body:has(.app-shell[data-theme="dark"]) { background: #000; }
a { color: inherit; text-decoration: none; }
.site-nav { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between;
  min-height: 66px; padding: 0 max(5vw, 16px); background: var(--bg); border-bottom: 1px solid var(--line); }
.brand { display: inline-flex; align-items: center; font-size: 30px; font-weight: 700; letter-spacing: -.045em; line-height: 1; }
.brand-mark { height: 1.2em; width: auto; margin-right: .04em; transform: translateY(-.04em); }
.nav-controls { display: flex; gap: 8px; }
.pill { padding: 8px 14px; border: 1px solid var(--line); border-radius: 99px; background: transparent; color: var(--fg); font: inherit; font-size: 13px; cursor: pointer; }
.pill:hover { background: var(--soft); border-color: var(--fg); }
main { max-width: 1120px; margin: 0 auto; padding: 0 max(5vw, 16px) 40px; }
.eyebrow { margin: 0 0 12px; color: var(--muted); font-size: 12px; font-weight: 600; letter-spacing: .02em; text-transform: uppercase; }
.hero-block { padding: 46px 0 10px; }
h1 { margin: 0; font-size: clamp(30px, 4.4vw, 48px); font-weight: 600; line-height: 1.1; letter-spacing: -.02em; }
.meta { margin: 12px 0 0; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.notice { margin: 16px 0 0; padding: 12px 16px; border: 1px solid var(--fg); border-radius: 12px; }
.cards-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 28px; }
.card { display: flex; flex-direction: column; gap: 4px; padding: 18px; border: 1px solid var(--line); border-radius: 18px; }
.card strong { font-size: 30px; font-weight: 600; line-height: 1; }
.card span { color: var(--muted); font-size: 13px; }
.block { margin-top: 44px; }
.bar { display: flex; height: 12px; overflow: hidden; border: 1px solid var(--line); border-radius: 99px; }
.seg-high { background: var(--fg); } .seg-suspicious { background: var(--muted); }
.seg-low { background: var(--subtle); opacity: .55; } .seg-none { background: var(--soft); }
.severity { display: grid; gap: 10px; margin: 16px 0 0; padding: 0; list-style: none; }
.severity li { display: grid; grid-template-columns: 150px 60px 1fr; align-items: center; gap: 10px; font-size: 15px; }
.level { display: inline-block; justify-self: start; padding: 6px 11px; border: 1px solid var(--line); border-radius: 99px; font-size: 12px; font-weight: 500; white-space: nowrap; }
.level-high { background: var(--fg); border-color: var(--fg); color: var(--bg); }
.level-suspicious { border-color: var(--fg); }
.level-none { color: var(--muted); }
.split { display: grid; grid-template-columns: minmax(200px, 280px) minmax(0, 1fr); gap: clamp(20px, 3vw, 44px); }
.side { position: sticky; top: 82px; align-self: start; display: grid; gap: 4px; max-height: calc(100vh - 100px); overflow: auto;
  padding: 8px; border: 1px solid var(--line); border-radius: 18px; }
.side a { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 11px; }
.side a:hover { background: var(--soft); }
.side img, .side .thumb-empty { flex: none; width: 46px; height: 46px; object-fit: cover; border-radius: 8px; background: var(--soft); }
.side span { display: flex; flex-direction: column; min-width: 0; }
.side strong { overflow: hidden; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.side small { margin-top: 2px; color: var(--muted); font-size: 11px; }
.cards { display: grid; gap: 22px; }
.photo { padding: 22px; border: 1px solid var(--line); border-radius: 22px; scroll-margin-top: 80px; }
.hero { display: block; width: 100%; max-height: 420px; object-fit: contain; background: var(--soft); border-radius: 16px; }
.hero.empty { display: grid; place-items: center; height: 120px; color: var(--muted); font-size: 13px; }
.photo-heading { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-top: 18px; }
.photo-heading h3 { min-width: 0; margin: 0; font-size: clamp(22px, 2.6vw, 30px); font-weight: 600; line-height: 1.15; overflow-wrap: anywhere; }
.location { margin: 8px 0 0; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.facts { margin: 6px 0 0; font-size: 13px; }
.camera { margin: 8px 0 0; padding: 0; list-style: none; color: var(--muted); font-size: 13px; }
.photo section { margin-top: 24px; }
h4 { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 10px; font-size: 17px; font-weight: 600; }
.findings { margin: 0; padding-left: 20px; font-size: 16px; line-height: 1.55; }
.findings li + li { margin-top: 8px; }
.read { padding: 4px 10px; border-radius: 99px; border: 1px solid var(--line); font-size: 12px; font-weight: 500; }
.read-yes { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.read-no, .read-closed { border-color: var(--fg); }
blockquote { margin: 10px 0; padding: 14px 18px; border: 1px solid var(--line); border-left: 3px solid var(--fg); border-radius: 10px; background: var(--soft); }
blockquote p { margin: 0; font-size: 18px; line-height: 1.45; overflow-wrap: anywhere; }
blockquote footer { margin-top: 8px; color: var(--muted); font-size: 12px; }
details { margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
summary { color: var(--fg); font-weight: 600; cursor: pointer; }
table.checks { width: 100%; margin-top: 14px; border-collapse: collapse; font-size: 13px; }
.checks th { padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--muted); font-weight: 500; text-align: left; }
.checks td { padding: 9px 10px; border-bottom: 1px solid var(--line); color: var(--fg); vertical-align: top; }
.checks td.muted { color: var(--muted); }
.result { display: inline-block; padding: 3px 9px; border: 1px solid var(--line); border-radius: 99px; font-size: 11px; white-space: nowrap; }
.result.bad { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.result.na { color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
.grid figure { margin: 0; }
.grid img, .grid .thumb-empty { display: block; width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 12px; background: var(--soft); }
.grid figcaption { margin-top: 6px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.case { margin: 18px 0; padding: 18px; border: 1px solid var(--fg); border-radius: 18px; }
.case .big { margin: 0; font-size: 16px; }
.big { font-size: 20px; font-weight: 600; }
.ok-text, .bad-text { margin: 0 0 6px; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 13px; }
.wrap { overflow-wrap: anywhere; word-break: break-word; }
.fp td.mono { font-size: 12px; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
code { padding: 1px 5px; border: 1px solid var(--line); border-radius: 5px; font-size: 12px; }
.plain { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.6; }
.glossary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 0; }
.glossary div { padding: 16px; border: 1px solid var(--line); border-radius: 16px; }
.glossary dt { font-weight: 600; }
.glossary dd { margin: 6px 0 0; color: var(--muted); font-size: 14px; line-height: 1.5; }
p { line-height: 1.55; }
.page-footer { max-width: 1120px; margin: 30px auto 0; padding: 24px max(5vw, 16px) 40px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
@media (max-width: 760px) {
  .cards-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .split { grid-template-columns: 1fr; }
  .side { position: static; max-height: 260px; }
  .severity li { grid-template-columns: 120px 44px 1fr; }
  .glossary { grid-template-columns: 1fr; }
  .nav-controls .pill:first-child { display: none; }
}
@media print {
  .site-nav { position: static; } .nav-controls, .side { display: none; }
  .split { grid-template-columns: 1fr; } .photo { break-inside: avoid; }
  details { display: block; } details > * { display: block; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } .app-shell { transition: none; } }
"""
