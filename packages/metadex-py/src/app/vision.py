"""One OpenCLIP model for the evidence-search feature.

Images and queries are encoded on this machine. Nothing is sent to Gemini or
any other hosted model. Tests inject an encoder so the suite never downloads
weights or requires a GPU.
"""
from __future__ import annotations

import math
import os
import threading

_lock = threading.Lock()
_load_lock = threading.Lock()
_infer_lock = threading.Lock()

_state = "not_loaded"  # not_loaded | loading | ready | failed
_error: str | None = None
_device: str | None = None
_cuda_available: bool | None = None
_runtime = None
_override = None


class EncoderError(Exception):
    """The search model cannot run. The message is safe to show to an examiner."""


def resolve_device(requested: str | None, cuda_available: bool) -> str:
    """Pick cpu or cuda. Never report cuda unless that device will actually run."""
    choice = (requested or "auto").strip().lower()
    if choice not in {"auto", "cpu", "cuda"}:
        raise EncoderError("METADEX_DEVICE must be auto, cpu, or cuda.")
    if choice == "cpu":
        return "cpu"
    if choice == "cuda":
        if not cuda_available:
            raise EncoderError(
                "GPU setup failed: METADEX_DEVICE=cuda but PyTorch cannot see a CUDA device. "
                "Install the NVIDIA driver and the CUDA build of PyTorch, then restart the service. "
                "To run without a GPU, set METADEX_DEVICE=cpu. The status endpoint will keep saying CPU."
            )
        return "cuda"
    return "cuda" if cuda_available else "cpu"


def model_name() -> str:
    return os.environ.get("METADEX_CLIP_MODEL", "ViT-B-32").strip() or "ViT-B-32"


def pretrained_name() -> str:
    return os.environ.get("METADEX_CLIP_PRETRAINED", "openai").strip() or "openai"


def status() -> dict:
    with _lock:
        state = _state
        device = _device
        error = _error
        cuda = _cuda_available
        if _override is not None:
            device = getattr(_override, "device", "cpu") or "cpu"
            state = "ready"
            error = None
            cuda = bool(getattr(_override, "cuda_available", device == "cuda"))
        using_gpu = state == "ready" and device == "cuda"
        if _override is None:
            shown_model = model_name()
            shown_pretrained = pretrained_name()
        else:
            shown_model = getattr(_override, "model_name", "test-encoder")
            shown_pretrained = getattr(_override, "pretrained", "test")
        return {
            "state": state,
            "device": device if state == "ready" else None,
            "using_gpu": using_gpu,
            "cuda_available": bool(cuda),
            "model": shown_model,
            "pretrained": shown_pretrained,
            "error": error,
        }


def set_encoder(encoder) -> None:
    """Install a stand-in encoder. Production code never calls this."""
    global _override
    with _lock:
        _override = encoder


def clear_encoder() -> None:
    global _override
    with _lock:
        _override = None


def reset_for_tests() -> None:
    """Drop a loaded runtime so a unit test can exercise load failures."""
    global _state, _error, _device, _cuda_available, _runtime, _override
    with _lock:
        _state = "not_loaded"
        _error = None
        _device = None
        _cuda_available = None
        _runtime = None
        _override = None


def _import_stack():
    import open_clip
    import torch

    return open_clip, torch


def load() -> None:
    """Load OpenCLIP once. Later calls reuse the same weights and device."""
    global _state, _error
    if _override is not None:
        return
    with _load_lock:
        if _runtime is not None and _state == "ready":
            return
        with _lock:
            _state = "loading"
            _error = None
        try:
            _load_runtime()
        except EncoderError as exc:
            _mark_failed(str(exc))
            raise


def _mark_failed(message: str) -> None:
    global _state, _error, _runtime
    with _lock:
        _state = "failed"
        _error = message
        _runtime = None


def _load_runtime() -> None:
    global _runtime, _device, _cuda_available, _state, _error
    try:
        open_clip, torch = _import_stack()
    except ImportError as exc:
        raise EncoderError(
            "The image-search model is not installed. Install the search extra "
            "(open-clip-torch) and a PyTorch build that matches this machine. "
            f"Import failed: {exc}."
        ) from exc
    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception as exc:
        raise EncoderError(f"GPU setup failed while checking CUDA: {exc}.") from exc
    try:
        device = resolve_device(os.environ.get("METADEX_DEVICE", "auto"), cuda_available)
    except EncoderError:
        with _lock:
            _cuda_available = cuda_available
        raise
    name = model_name()
    pretrained = pretrained_name()
    cache = os.environ.get("METADEX_CLIP_CACHE", "").strip() or None
    try:
        model, _preprocess_train, preprocess = open_clip.create_model_and_transforms(
            name,
            pretrained=pretrained,
            cache_dir=cache,
        )
        tokenizer = open_clip.get_tokenizer(name)
        model.eval()
        model.to(device)
    except EncoderError:
        raise
    except Exception as exc:
        raise EncoderError(
            f"OpenCLIP weights could not be loaded ({name}, {pretrained}). {exc}. "
            "On the first run the server needs to reach the model host, or METADEX_CLIP_CACHE "
            "must already contain the weights. Search stays unavailable until this succeeds."
        ) from exc
    runtime = _OpenClipEncoder(model, preprocess, tokenizer, device, torch)
    with _lock:
        _runtime = runtime
        _device = device
        _cuda_available = cuda_available
        _state = "ready"
        _error = None


class _OpenClipEncoder:
    def __init__(self, model, preprocess, tokenizer, device: str, torch_module):
        self.model = model
        self.preprocess = preprocess
        self.tokenizer = tokenizer
        self.device = device
        self._torch = torch_module

    def encode_image(self, image) -> list[float]:
        tensor = self.preprocess(image).unsqueeze(0).to(self.device)
        with self._torch.no_grad():
            features = self.model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].detach().float().cpu().tolist()

    def encode_text(self, text: str) -> list[float]:
        tokens = self.tokenizer([text]).to(self.device)
        with self._torch.no_grad():
            features = self.model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].detach().float().cpu().tolist()


def _require_encoder():
    if _override is not None:
        return _override
    load()
    with _lock:
        runtime = _runtime
        error = _error
    if runtime is None:
        raise EncoderError(error or "The image-search model is not loaded.")
    return runtime


def normalize(vector: list[float]) -> list[float]:
    if not vector:
        raise EncoderError("The model returned an empty embedding.")
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0:
        raise EncoderError("The model returned a zero embedding.")
    return [float(value) / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Dot product of two normalized embeddings. Relative similarity, not a probability."""
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    return float(sum(left[index] * right[index] for index in range(length)))


def _as_vector(raw) -> list[float]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise EncoderError("The image encoder returned an empty embedding.")
    try:
        return normalize([float(value) for value in raw])
    except (TypeError, ValueError) as exc:
        raise EncoderError("The image encoder returned a non-numeric embedding.") from exc


def embed_image(image) -> list[float]:
    encoder = _require_encoder()
    rgb = image.convert("RGB")
    try:
        with _infer_lock:
            raw = encoder.encode_image(rgb)
    except EncoderError:
        raise
    except Exception as exc:
        raise EncoderError(f"Image encoding failed: {exc}.") from exc
    return _as_vector(raw)


def embed_text(text: str) -> list[float]:
    encoder = _require_encoder()
    try:
        with _infer_lock:
            raw = encoder.encode_text(text)
    except EncoderError:
        raise
    except Exception as exc:
        raise EncoderError(f"Text encoding failed: {exc}.") from exc
    return _as_vector(raw)
