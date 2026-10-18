<h1 align="center">METADEX</h1>

<p align="center">Every image has a story.</p>

<p align="center">
  <img alt="Website + Terminal" src="https://img.shields.io/badge/Platform-Website_%2B_Terminal-111111">
  <img alt="React" src="https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="Gemini" src="https://img.shields.io/badge/Gemini-8E75B2?logo=googlegemini&logoColor=white">
</p>

A photo is not just the picture. The file can carry a comment, a place, a date, a name, or a line that was encoded so it would not show up when you open the image. Metadex reads that. You drop a photo or a folder, or you point the terminal at it, and you get the notes back in plain words.

A flag is a reason to look closer. It is not a verdict.

## The idea

People hide plans in the boring parts of a photo. A caption. An author field. A comment saved twice, once in words and once encoded. Metadex is the place you look when the picture itself is not the whole story.

The website and the `metadex` command share one checker. The site is how you look through a batch. The terminal is how you scan a file, a folder, or keep going from the machine you are already on.

## How it works

1. **Bring the photos.** On the site, choose images or a folder. In the terminal, pass a file or a folder.
2. **Read what the file stored.** The checker pulls comments, camera details, places, dates, and encoded lines, then ranks what looks off.
3. **Read it back.** The report shows the recovered line. Gemini can explain those notes. It does not invent a finding that the checker did not recover, and the photo bytes stay on your computer.

## Snapshot

<p align="center">
  <img src="docs/preview.png" alt="Metadex homepage" width="920">
</p>

## Getting started

The website:

```sh
npm install
npm run dev -- --host 127.0.0.1 --port 8080
```

The terminal checker, from this repo:

```sh
python3 -m pip install -e packages/metadex-py
metadex ./photo.jpg
metadex ~/Pictures
```

Or install the wheel the site offers:

```sh
python3 -m pip install ~/Downloads/metadex-0.8.1-py3-none-any.whl
metadex ./photo.jpg
metadex ~/Pictures
```

`metadex` with no path scans the folder you are in. `metadex --all` walks the computer and lists only flagged photos. `metadex serve` starts the checker the website talks to, on `127.0.0.1:8741`.

Set `GEMINI_API_KEY` in the environment before `metadex serve` or `metadex --explain` if you want Gemini. Keep the key on the machine. Do not put it in the browser.

## Stack

<p align="center">
  <img alt="React" src="https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white">
  <img alt="TanStack" src="https://img.shields.io/badge/TanStack_Start-Router-111111">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-checker-009688?logo=fastapi&logoColor=white">
  <img alt="Pillow" src="https://img.shields.io/badge/Pillow-images-111111">
  <img alt="Gemini" src="https://img.shields.io/badge/Gemini-explains_notes-8E75B2?logo=googlegemini&logoColor=white">
</p>

The site is React, TypeScript, and Vite. The checker is Python. Gemini only explains notes the checker already recovered.

## Contributors

<a href="https://www.linkedin.com/in/melashry/">
  <img src="https://avatars.githubusercontent.com/u/316233960?v=4" width="96" height="96" alt="Mohamed Elashry">
</a>

**[Mohamed Elashry](https://www.linkedin.com/in/melashry/)**  
Frontend

**[Hamza Elashry](https://www.linkedin.com/in/hamzaelashry/)**  
Python and backend

## Checks

```sh
npm test
npx tsc --noEmit
```
