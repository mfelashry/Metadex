<h1 align="center">Metadex</h1>

<p align="center">Every image has a story. Look closer.</p>

<p align="center">
Metadex reads the metadata, hidden text, and encoded notes stored in a photo.<br>
It turns that into a report a person can actually read.
</p>

<p align="center">
  <img src="docs/preview.png" alt="METADEX" width="720">
</p>

A flag is a reason to look. It is not a verdict.

## Why it's useful

- Upload a folder
- Read EXIF and comments
- Decode base64 notes
- Ask about the case
- Search a case by describing what is in the picture

## How it works

<p align="center"><strong>IMAGE → METADATA → STRUCTURE → REPORT</strong></p>

## Getting started

Website:

```sh
npm install
npm run dev
```

Terminal:

```sh
python3 -m pip install -e packages/metadex-py
metadex ./photo.jpg
metadex ~/Pictures
metadex serve
```

Open **Image search** in the site header. The page talks to the forensic API at `VITE_STILLFRAME_API` (default `http://127.0.0.1:8741`). Copy `.env.example` to `.env` when that URL is not local.

Image search ranks a case with a local OpenCLIP model. A similarity score is not a probability and not a danger score. A forensic indicator is a reason to look, not proof of an attack. The built-in demo case is drawn on the server, so the presentation does not download photos. Install the search extra and, on a GPU machine, the CUDA build of PyTorch before expecting real embeddings. Tests use a stand-in encoder and do not download weights.

```sh
python3 -m pip install -e "packages/metadex-py[search,test]"
python3 -m pytest -q packages/metadex-py/tests
```

For a Vultr GPU host, follow [docs/vultr-gpu.md](docs/vultr-gpu.md). Folder scanning stays off on that host. Upload is the only way images get in.

## Stack

<p align="center">
  <img alt="React" src="https://img.shields.io/badge/React-149ECA?logo=react&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white">
  <img alt="Gemini" src="https://img.shields.io/badge/Gemini-8E75B2?logo=googlegemini&logoColor=white">
</p>

## Contributors

<table align="center">
  <tr>
    <td align="center">
      <a href="https://www.linkedin.com/in/melashry/">
        <img src="docs/me.png" width="96" height="96" alt="Mohamed Elashry">
      </a>
      <br>
      <a href="https://www.linkedin.com/in/melashry/"><strong>Mohamed Elashry</strong></a>
      <br>
      Frontend
    </td>
    <td align="center">
      <a href="https://www.linkedin.com/in/hamzaelashry/">
        <img src="docs/he.png" width="96" height="96" alt="Hamza Elashry">
      </a>
      <br>
      <a href="https://www.linkedin.com/in/hamzaelashry/"><strong>Hamza Elashry</strong></a>
      <br>
      Python and backend
    </td>
  </tr>
</table>

<p align="center">Metadex. Look closer.</p>
