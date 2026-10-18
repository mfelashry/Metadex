"""Tests for the terminal command: default folder, paths, --all, removed --sensors."""
import json
import os
from pathlib import Path

import pytest

from app.evidence import build_evidence
from app import sweep as sweep_module
from metadex.cli import main


@pytest.fixture
def case(tmp_path):
    files = {f["filename"]: f["data"] for f in build_evidence()}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "trip" / "day2").mkdir(parents=True)
    (tmp_path / "trip" / "day2" / "beach.jpg").write_bytes(files["profile_photo.jpg"])
    (tmp_path / "trip" / "receipt.txt").write_bytes(files["IMG_2066.jpg"])  # a photo hiding under .txt
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "skip.jpg").write_bytes(files["profile_photo.jpg"])
    return tmp_path


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    # Tables wrap at the test's 80 columns; join lines and strip box borders so phrases can be matched.
    flat = " ".join(out.out.replace("│", " ").split())
    return code, flat, out.err


def test_no_arguments_scans_the_current_folder_and_subfolders(case, capsys, monkeypatch):
    monkeypatch.chdir(case)
    code, out, _ = run(capsys)
    assert code == 0
    assert "METADEX" in out
    assert "9 of 13 images show signs of hidden data" in out
    assert "beach.jpg" in out and "trip/day2/" in out.replace(os.sep, "/").replace(" ", "")
    assert "receipt.txt" in out  # found by its bytes, not its name
    assert "JPEG image disguised as .txt" in out
    assert "Package moves Friday. Use the second phone." in out
    assert "Evidence unchanged" in out
    assert "skip.jpg" not in out  # hidden folders are left alone
    assert "Save these results" not in out  # no question when output is not a terminal


def test_path_and_old_scan_word_give_the_same_result(case, capsys):
    _, plain, _ = run(capsys, str(case), "--json")
    _, old, _ = run(capsys, "scan", str(case), "--json")
    a, b = json.loads(plain), json.loads(old)
    assert [e["path"] for e in a["ranking"]] == [e["path"] for e in b["ranking"]]
    assert a["summary"]["scanned"] == 13


def test_no_limit_of_500_files(tmp_path, capsys):
    data = build_evidence()[0]["data"]
    for i in range(520):
        (tmp_path / f"img_{i:04d}.jpg").write_bytes(data)
    _, out, _ = run(capsys, str(tmp_path), "--json")
    assert json.loads(out)["summary"]["scanned"] == 520


def test_no_recursive(case, capsys):
    _, out, _ = run(capsys, str(case), "--no-recursive", "--json")
    names = [e["path"] for e in json.loads(out)["ranking"]]
    assert "beach.jpg" not in " ".join(names)
    assert len(names) == 11


def test_single_photo(case, capsys):
    code, out, _ = run(capsys, str(case / "IMG_2066.jpg"))
    assert code == 0
    assert "drop point: north gate, 21:00" in out


def test_sensors_option_is_removed_but_old_commands_still_run(case, capsys):
    code, out, err = run(capsys, "scan", str(case / "profile_photo.jpg"), "--sensors", "place-readings.json")
    assert code == 0
    assert "--sensors is no longer needed" in err
    assert "This image shows signs of hidden data" in out
    assert "Package moves Friday" in out
    assert "Device" not in out


def test_scan_leaves_files_untouched(case, capsys):
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.rglob("*") if p.is_file()}
    _, out, _ = run(capsys, str(case), "--json")
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.rglob("*") if p.is_file()}
    assert before == after
    assert json.loads(out)["integrity"]["all_unchanged"] is True


def test_errors(capsys, tmp_path):
    code, _, err = run(capsys, str(tmp_path / "missing"))
    assert code == 1 and "No such file or folder" in err
    with pytest.raises(SystemExit):
        main(["--all", str(tmp_path)])


def test_all_lists_only_flagged_and_skips_system_and_code_folders(case, capsys, monkeypatch):
    (case / "node_modules" / "pkg").mkdir(parents=True)
    (case / "node_modules" / "pkg" / "x.png").write_bytes(build_evidence()[6]["data"])
    (case / "Shop.app").mkdir()
    (case / "Shop.app" / "icon.jpg").write_bytes(build_evidence()[3]["data"])
    (case / "system").mkdir()
    (case / "system" / "logo.jpg").write_bytes(build_evidence()[3]["data"])
    monkeypatch.setattr(sweep_module, "whole_computer_roots", lambda: [str(case)])
    monkeypatch.setattr(sweep_module, "_system_prefixes", lambda: [os.path.normcase(str(case / "system"))])
    code, out, _ = run(capsys, "--all")
    assert code == 0
    assert "the whole computer" in out
    assert "node_modules" not in out and "Shop.app" not in out and "logo.jpg" not in out
    assert "receipt.txt" in out
    assert "Clean" in out and "clean images not listed" in out  # clean ones are counted, not listed
    assert "IMG_2057.jpg" not in out


def test_all_survives_ctrl_c_and_reports_what_it_found(case, monkeypatch, capsys):
    real = sweep_module.analyze_bytes
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(sweep_module, "analyze_bytes", flaky)
    monkeypatch.setattr(sweep_module, "whole_computer_roots", lambda: [str(case)])
    monkeypatch.setattr(sweep_module, "_system_prefixes", lambda: [])
    code, out, _ = run(capsys, "--all", "--json")
    body = json.loads(out)
    assert code == 0
    assert body["summary"]["interrupted"] is True
    assert body["summary"]["scanned"] == 3
    assert body["summary"]["headline"].endswith("(stopped early)")


def test_folder_named_scan_is_still_a_folder(tmp_path, capsys, monkeypatch):
    (tmp_path / "scan").mkdir()
    (tmp_path / "scan" / "a.jpg").write_bytes(build_evidence()[3]["data"])
    monkeypatch.chdir(tmp_path)
    _, out, _ = run(capsys, "scan")
    assert "a.jpg" in out


def test_save_option_writes_json_by_default(case, capsys, tmp_path):
    target = tmp_path / "out" / "results"
    code, out, _ = run(capsys, str(case), "--save", str(target))
    assert code == 0 and "Saved to" in out
    saved = tmp_path / "out" / "results.json"
    assert json.loads(saved.read_text())["summary"]["scanned"] == 13
    run(capsys, str(case), "--save", str(target))  # never overwrites an earlier file
    assert (tmp_path / "out" / "results-2.json").exists()


def test_fingerprints_show_in_the_terminal(case, capsys):
    import hashlib

    code, out, _ = run(capsys, str(case))
    assert code == 0
    assert "File fingerprints (SHA256)" in out
    for name in ("profile_photo.jpg", "IMG_2057.jpg", "holiday_card.png"):
        assert hashlib.sha256((case / name).read_bytes()).hexdigest() in out.replace(" ", "")
    assert "✓ not changed by this scan" in out
    assert out.index("File fingerprints") < out.index("Evidence unchanged")


def test_txt_name_writes_a_readable_report(case, capsys, tmp_path):
    target = tmp_path / "out" / "results.txt"
    code, out, _ = run(capsys, str(case), "--save", str(target))
    assert code == 0
    saved = target
    assert saved.exists() and "Saved to" in out
    text = saved.read_text(encoding="utf-8")
    assert "METADEX REPORT" in text
    assert "9 of 13 photos show signs of hidden data." in text
    # every flagged photo: name, full location, severity, plain findings, readable or not
    assert "1. " in text and "Location:   " + str(case) in text
    assert "Severity:   HIGH" in text and "Severity:   LOW" in text
    assert 'Message: "Package moves Friday. Use the second phone."' in text
    assert "disguised with base64 encoding" in text
    assert "Could we read it?  YES" in text
    assert "Could we read it?  NO" in text  # encrypted looking payload
    assert "Could we read it?  NOT OPENED" in text  # hidden ZIP is never opened
    assert "Could we read it?  NOTHING TO READ" in text  # renamed file only
    assert 'really a JPEG photo' in text
    # fingerprints at the end, for every listed photo
    tail = text[text.index("FILE FINGERPRINTS"):]
    import hashlib
    for name in ("profile_photo.jpg", "IMG_2057.jpg"):
        assert hashlib.sha256((case / name).read_bytes()).hexdigest() in tail
    assert text.index("FILE FINGERPRINTS") > text.index("CLEAN PHOTOS") > text.index("PHOTOS WITH FINDINGS")
    assert "codes match" in tail


def test_save_as_json_still_possible(case, capsys, tmp_path):
    target = tmp_path / "raw.json"
    run(capsys, str(case / "IMG_2066.jpg"), "--save", str(target))
    assert json.loads(target.read_text())["summary"]["scanned"] == 1


def test_single_photo_report_wording(case, capsys, tmp_path):
    target = tmp_path / "one.txt"
    run(capsys, str(case / "IMG_2041.jpg"), "--save", str(target))
    text = " ".join(target.read_text().split())
    assert "This photo looks clean." in text
    assert "The photo " + str(case / "IMG_2041.jpg") in text


def _answers(monkeypatch, ui, choice_inputs, names):
    choice_inputs, names = iter(choice_inputs), iter(names)
    monkeypatch.setattr(ui.console, "input", lambda *a, **k: next(choice_inputs))
    monkeypatch.setattr(ui.Prompt, "ask", classmethod(lambda cls, *a, **k: next(names)))


@pytest.mark.parametrize("typed,expected", [("1", [".json"]), ("json", [".json"]), ("2", [".html"]), ("html", [".html"]),
                                            ("3", [".json", ".html"]), ("y", [".json", ".html"]), ("yes", [".json", ".html"])])
def test_save_prompt_answers(typed, expected, monkeypatch, tmp_path, capsys):
    from metadex import ui

    _answers(monkeypatch, ui, [typed], [str(tmp_path / "out")])
    ui.ask_to_save({"summary": {"scanned": 0}, "ranking": []}, {"label": "Test"})
    assert sorted(p.suffix for p in tmp_path.iterdir()) == sorted(expected)


def test_save_prompt_retries_on_nonsense_and_skips_on_enter(monkeypatch, tmp_path, capsys):
    from metadex import ui

    monkeypatch.chdir(tmp_path)
    _answers(monkeypatch, ui, ["json/html", "maybe", ""], [])
    ui.ask_to_save({"a": 1})
    out = capsys.readouterr().out
    assert out.count("Just type 1, 2, or 3") == 2 and "Not saved" in out
    assert list(tmp_path.iterdir()) == []

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(ui.console, "input", interrupted)
    ui.ask_to_save({"a": 1})  # no crash
    assert list(tmp_path.iterdir()) == []


def test_case_fingerprint_is_shown_saved_and_stable(case, capsys, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    _, out, _ = run(capsys, str(case), "--save", str(first))
    run(capsys, str(case), "--save", str(second))
    a, b = json.loads(first.read_text()), json.loads(second.read_text())
    assert a["case_fingerprint"]["sha256"] == b["case_fingerprint"]["sha256"]
    assert a["case_fingerprint"]["files"] == 13 == len(a["fingerprints"])
    assert "Case fingerprint" in out and a["case_fingerprint"]["sha256"] in out.replace(" ", "")


def test_compare_finds_every_kind_of_change(case, capsys, tmp_path):
    before = tmp_path / "before.json"
    run(capsys, str(case), "--save", str(before))

    _, out, _ = run(capsys, str(case), "--compare", str(before))
    assert "Nothing changed" in out

    with open(case / "IMG_2057.jpg", "ab") as fh:
        fh.write(b"x")
    (case / "logo_draft.png").unlink()
    (case / "holiday_card.png").rename(case / "xmas.png")
    (case / "trip" / "new_photo.jpg").write_bytes((case / "IMG_2041.jpg").read_bytes())

    _, out, _ = run(capsys, str(case), "--compare", str(before), "--json")
    result = json.loads(out)["comparison"]
    assert result["same"] is False
    assert [c["path"] for c in result["changed"]] == ["IMG_2057.jpg"]
    assert result["missing"] == ["logo_draft.png"]
    assert result["new"] == ["trip/new_photo.jpg"]
    assert result["renamed"] == [{"from": "holiday_card.png", "to": "xmas.png", "sha256": result["renamed"][0]["sha256"]}]
    assert result["unchanged"] == 10
    assert result["case_before"] != result["case_now"]

    _, text, _ = run(capsys, str(case), "--compare", str(before))
    for word in ("Something changed", "CHANGED", "MISSING", "NEW", "RENAMED", "IMG_2057.jpg", "logo_draft.png"):
        assert word in text


def test_compare_works_with_json_saved_before_case_fingerprints_existed(case, capsys, tmp_path):
    before = tmp_path / "old.json"
    run(capsys, str(case), "--save", str(before))
    data = json.loads(before.read_text())
    data.pop("fingerprints"), data.pop("case_fingerprint")
    before.write_text(json.dumps(data))
    _, out, _ = run(capsys, str(case), "--compare", str(before))
    assert "Nothing changed" in out


def test_compare_bad_file(capsys, tmp_path, case):
    bad = tmp_path / "x.json"
    bad.write_text("{not json")
    code, _, err = run(capsys, str(case), "--compare", str(bad))
    assert code == 1 and "not a metadex" in err
    code, _, err = run(capsys, str(case), "--compare", str(tmp_path / "missing.json"))
    assert code == 1 and "No earlier scan file" in err


def test_html_report(case, capsys, tmp_path):
    import hashlib

    before = tmp_path / "before.json"
    run(capsys, str(case), "--save", str(before))
    (case / "logo_draft.png").unlink()
    target = tmp_path / "report.html"
    code, out, _ = run(capsys, str(case), "--compare", str(before), "--save", str(target))
    assert code == 0 and "Saved to" in out and "Open it in any web browser" in out
    page = target.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "8 of 12 photos show signs of hidden data." in page
    assert "Package moves Friday. Use the second phone." in page
    assert "Yes, we read it" in page and "Found, not opened" in page and "Nothing to read" in page
    assert "Every check we ran on this photo" in page
    assert "Case fingerprint" in page and "Something changed since before.json" in page and "Missing" in page
    assert hashlib.sha256((case / "IMG_2057.jpg").read_bytes()).hexdigest() in page
    assert "data:image/jpeg;base64," in page  # photo previews are embedded
    assert "data:image/png;base64," in page  # logo is embedded
    assert "Words used in this report" in page


def test_html_report_escapes_hidden_messages(tmp_path, capsys):
    from PIL import Image

    img = Image.new("RGB", (64, 64), (200, 100, 50))
    exif = Image.Exif()
    exif[0x010E] = '<script>alert("x")</script><img src=x onerror=alert(1)>'
    img.save(tmp_path / "evil.jpg", "JPEG", exif=exif.tobytes())
    target = tmp_path / "r.html"
    run(capsys, str(tmp_path / "evil.jpg"), "--save", str(target))
    page = target.read_text(encoding="utf-8")
    assert "<script>alert" not in page and "onerror=alert(1)>" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
