# Metadex

Metadex is a local image-forensics viewer with a browser interface and a terminal checker. It accepts images or a folder, ranks findings, and shows recovered text. Gemini can explain the checker’s finding categories on request; image bytes, file names, and recovered text are not sent to Gemini.

## Run the website

```sh
npm install
npm run dev -- --host 127.0.0.1 --port 8080
```

Install the Python wheel from the website’s **From the terminal** section, then start the local checker in another terminal:

```sh
python3 -m pip install ~/Downloads/metadex-0.2.0-py3-none-any.whl
metadex serve
```

The checker listens on `127.0.0.1:8741`. Without it, browser uploads use a smaller local fallback analysis. To enable the optional Gemini explanation button, set `GEMINI_API_KEY` in the checker’s environment before `metadex serve`. Never place the key in browser code.

## Terminal scans

The Python package scans locally without running the website or server:

```sh
metadex scan ~/Pictures
metadex scan ./photo.jpg --json
```

An alternative Node terminal client is available as `metadex-0.2.0.tgz`. It talks to the Python checker, so start `metadex serve` first. The website also offers a source ZIP containing both packages.

## Checks

```sh
npm test
npx tsc --noEmit
npm run build
```
