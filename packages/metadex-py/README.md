# metadex

Scan a photo or a whole folder from the terminal. The Python package includes the local checker.

## Install

Download the wheel from the Metadex website, then install it:

```bash
python3 -m pip install ~/Downloads/metadex-0.2.0-py3-none-any.whl
```

Then:

```bash
metadex scan ~/Pictures
metadex scan ./photo.jpg
metadex scan ./photo.jpg --json
metadex serve
```

`scan` runs locally without a server. `serve` starts the website checker at `127.0.0.1:8741`. Set `GEMINI_API_KEY` in the server environment to enable on-demand explanations; photo bytes and recovered text are not sent to Gemini.

The command prints one line per photo: the level, then the file name. It does not print a score.
