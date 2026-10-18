# Vultr GPU setup for evidence search

This is the setup for the machine that runs OpenCLIP. It has not been deployed for you. Nothing in this repository contains a Vultr password, API key, or server address.

Image search runs on that machine. The browser uploads only the images you choose. The server does not scan its own disk unless you explicitly turn folder scan on, and you should not do that on a public host. Image bytes, filenames, and recovered text are not sent to Gemini.

After it is up, `GET /health` must show the device that is actually in use. `"device": "cuda"` and `"using_gpu": true` means the GPU ran. `"device": "cpu"` means CPU. Do not describe a CPU run as GPU inference.

## 1. Create the instance

1. In the Vultr dashboard, deploy a **Cloud GPU** instance. An NVIDIA GPU with at least 8 GB of memory is enough for the default `ViT-B-32` model.
2. Choose Ubuntu 22.04. Use a Vultr image that already has the NVIDIA driver if one is offered. Otherwise install the driver in the next step.
3. Add your SSH key. Do not commit the private key or put it in this repo.
4. Note the public IPv4 address. You will use it only in your own shell and in `.env`, which is gitignored.

## 2. Confirm the GPU

SSH in, then:

```bash
nvidia-smi
```

You should see the GPU name and a driver version. If the command is missing, install the driver from Ubuntu’s driver packages or Vultr’s GPU guide, then reboot and run `nvidia-smi` again. Do not continue until that command works. PyTorch cannot use a GPU the driver cannot see.

## 3. Run the API with Docker

Install Docker and the NVIDIA container toolkit on the instance (Docker’s and NVIDIA’s current Ubuntu instructions). Then, from a clone of this repository on the server:

```bash
docker build -f deploy/Dockerfile.gpu -t metadex-search .
docker run --gpus all --name metadex-search \
  -p 8741:8741 \
  -e METADEX_CORS_ORIGINS="https://YOUR_FRONTEND_ORIGIN" \
  -e METADEX_PRELOAD_MODEL=1 \
  -e METADEX_DEVICE=auto \
  -e STILLFRAME_ALLOW_FOLDER_SCAN=0 \
  -v metadex-cases:/tmp/metadex-cases \
  -e METADEX_CASE_DIR=/tmp/metadex-cases \
  metadex-search
```

Replace `https://YOUR_FRONTEND_ORIGIN` with the real site origin, for example your Lovable URL or `http://127.0.0.1:5173` if the browser is on your laptop and the API is reached directly. The origin is the page the browser is on, not the API host. No trailing slash.

Leave `STILLFRAME_ALLOW_FOLDER_SCAN` unset or `0`. That keeps `/api/scan-folder` from reading paths on the server.

The first start downloads OpenCLIP weights. Later starts reuse the container cache if you also mount a volume for it:

```bash
-e METADEX_CLIP_CACHE=/models \
-v metadex-models:/models
```

Check readiness:

```bash
curl -s http://127.0.0.1:8741/health
```

You want `"state": "ready"`, `"device": "cuda"`, and `"using_gpu": true`. If the state is `failed`, the `error` string is what to fix (missing weights, or CUDA requested when PyTorch cannot see the GPU). If the device is `cpu`, the process is not using the GPU. Reinstall the CUDA PyTorch wheel inside the image rather than telling the demo it ran on GPU.

Open TCP `8741` only if the browser will call the instance directly. Restrict the firewall to your IP if you can. Prefer HTTPS in front of the container for a public demo (Caddy or nginx with a certificate). Point `VITE_STILLFRAME_API` at that HTTPS origin.

## 4. Run without Docker

On the same Ubuntu GPU instance:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv
python3 -m venv ~/metadex-venv
source ~/metadex-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
python -m pip install --upgrade-strategy only-if-needed -e "./packages/metadex-py[search]"
```

`only-if-needed` keeps the CUDA build of PyTorch from being replaced by a CPU wheel.

```bash
export METADEX_PRELOAD_MODEL=1
export METADEX_DEVICE=auto
export STILLFRAME_ALLOW_FOLDER_SCAN=0
export METADEX_CORS_ORIGINS="https://YOUR_FRONTEND_ORIGIN"
cd packages/metadex-py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8741
```

Confirm CUDA from the same venv:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
```

Then check `/health` as above.

## 5. Point the website at the API

On the machine where you run the frontend:

```bash
cp .env.example .env
```

Set:

```bash
VITE_STILLFRAME_API=https://YOUR_API_ORIGIN
```

Restart `npm run dev`, or rebuild if the site is hosted. The value is baked in at dev/build time.

Open **Image search**. The status line must match `/health`. For the demo, choose **Open the demo case**, wait until indexing finishes, then search `a red backpack` and `a person near a window`. One image is a clean meadow. One image has a synthetic JPEG comment and trailing bytes. Delete the case when you are done. Cases also expire (default six hours).

## 6. What not to do

- Do not set `STILLFRAME_ALLOW_FOLDER_SCAN=1` on the Vultr host.
- Do not commit `.env`, API keys, or SSH keys.
- Do not send evidence to a hosted chat model. The explain endpoint, if you use it, still sends only finding labels, and image search does not call it.
- Do not claim the service is deployed until `/health` on your instance says the model is ready.
