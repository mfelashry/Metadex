# metadex

Find hidden data in photos from the terminal. The Python package includes the local checker.

## Install

Download the wheel from the Metadex website, then install it:

```bash
python3 -m pip install ~/Downloads/metadex-0.8.1-py3-none-any.whl
```

If you had an older version installed, this replaces it.

## Use

```bash
metadex                  # scan the folder you are in, and every folder inside it
metadex ~/Pictures       # scan one folder (or several: metadex ~/Pictures ~/Downloads)
metadex photo.jpg        # scan one photo
metadex --all            # scan the whole computer
metadex serve            # start the website checker on 127.0.0.1:8741
```

On Windows the same commands work, for example `metadex .\photo.png` or `metadex C:\Users\you\Pictures`.

While it runs you see a progress bar (percent done, files, images, and how many are flagged). When it finishes you get a table of the photos ranked from most to least suspicious, with a short reason for each, then a box for every hidden message it decoded. After the messages it lists every photo's fingerprint (its SHA256 hash), taken before the scan and checked again after it, so you can see that nothing was changed, and then one case fingerprint: a single code for the whole set of photos. If any photo changes, is renamed, added, or removed, the case fingerprint changes. To check a folder against an earlier scan, run `metadex <folder> --compare earlier.json`; it lists every file that changed, went missing, is new, or was renamed. At the end it asks whether to save the results: type `1` for JSON, `2` for HTML, `3` (or `yes`) for both, or press Enter to skip. JSON saves the full data. HTML saves a report in the Metadex website style that anyone can read: a summary, how serious each finding is, a card for every photo with its preview, location, what was found in plain words, the decoded message (or why it could not be read), its fingerprint, and every check that ran, then the case fingerprint, the comparison with an earlier scan if you used `--compare`, and a short glossary. The HTML file is self contained (previews and logo are inside it), has a light and dark mode, and can be printed or saved as a PDF from the browser. `--save results.json` or `--save report.html` saves without asking. Files are found by their bytes, not their names, so a photo renamed to `.txt` is still checked. There is no file limit.

`--all` scans every local drive. System and app folders (for example `/System`, `/Applications`, `~/Library`, `C:\Windows`, `Program Files`, `AppData`), code folders (`node_modules`, `.git`, virtual environments), and other hidden folders are skipped so the scan finishes in reasonable time. The trash is still scanned. A progress line shows how far it has got, only flagged photos are listed, and Ctrl+C stops early and prints what was found so far. On a Mac, the terminal may ask for permission to read Desktop, Documents, and Downloads; folders it cannot read are counted and skipped.

Options:

| Option | What it does |
| --- | --- |
| `--all` | Scan the whole computer |
| `--explain` | Ask Gemini to explain the top finding. Set `GEMINI_API_KEY` first. Only the level and finding categories are sent: no photo bytes, file names, or recovered text. |
| `--save FILE` | Save without asking: `.json` for the data, `.html` for the visual report (`.txt` for plain text) |
| `--compare FILE` | Compare with the JSON saved from an earlier scan of the same folder and list what changed |
| `--json` | Print the full result as JSON instead of the table |
| `--no-recursive` | Only the top folder, not the folders inside it |

`scan` is still accepted as a first word, so older commands such as `metadex scan ~/Pictures` keep working. `--sensors` was removed; if it is given, it is ignored with a note.

Files are opened read only and hashed again after each check, so a scan never changes the evidence.

## Tests

```bash
python3 -m pip install pytest httpx
python3 -m pytest -q tests
```
