# metadex

Find hidden data in photos from Node.js. This command talks to the local Metadex checker (`http://127.0.0.1:8741`), so install the Python package and run `metadex serve` first.

## Install

Download the npm package from the Metadex website, then install it:

```bash
npm install -g ~/Downloads/metadex-0.8.1.tgz
```

## Use

```bash
metadex                  # scan the folder you are in, and every folder inside it
metadex ~/Pictures       # scan one folder
metadex photo.jpg        # scan one photo
metadex --all            # scan the whole computer (Ctrl+C stops and shows results so far)
```

Options: `--explain` asks Gemini, through the checker, to explain the top finding. `--json` prints the full result. `--no-recursive` stays in the top folder.

`--all` walks every local drive here and asks the checker to scan each folder that holds files, skipping system, app, and code folders. Only flagged photos are listed.

`scan` is still accepted as a first word. `--sensors` was removed; if it is given, it is ignored with a note.

A folder is read by the checker on the same computer. A single photo is uploaded to it. To use a checker at another address:

```bash
export METADEX_API=http://127.0.0.1:8741
```
