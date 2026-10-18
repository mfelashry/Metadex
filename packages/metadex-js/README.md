# metadex

Scan a photo or a whole folder from Node.js. This command talks to the local Metadex checker (`http://127.0.0.1:8741`). Install the Python package and run `metadex serve` first.

## Install

Download the npm package from the Metadex website, then install it:

```bash
npm install -g ~/Downloads/metadex-0.2.0.tgz
```

Then:

```bash
metadex scan ~/Pictures
metadex scan ./photo.jpg
metadex scan ./photo.jpg --json
```

A folder is read on the computer that is running the checker. A single image is uploaded. The Python wheel includes the checker; this Node package is an alternative terminal client.

```bash
export METADEX_API=http://127.0.0.1:8741
```

The command prints the level and the file name. It does not print a score.
