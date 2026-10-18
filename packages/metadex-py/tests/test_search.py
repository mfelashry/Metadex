"""Evidence image search: indexing, ranking, forensics, failures, and deletion.

The encoder is a stand-in. These tests do not download OpenCLIP weights or use a GPU.
"""
import io
import time
from pathlib import Path

import pytest
from PIL import Image

from app import cases, vision
from app.analyze import MAX_BYTES
from app.search_demo import BACKPACK_SIZE, LOCKER_MESSAGE, LOCKER_SIZE, MEADOW_SIZE, WINDOW_SIZE


class FakeEncoder:
    def __init__(self):
        self.image_calls = 0
        self.text_calls = 0
        self.device = "cpu"
        self.cuda_available = False
        self.model_name = "test-encoder"
        self.pretrained = "test"

    def encode_image(self, image):
        self.image_calls += 1
        table = {
            BACKPACK_SIZE: [1.0, 0.0, 0.0],
            WINDOW_SIZE: [0.0, 1.0, 0.0],
            MEADOW_SIZE: [0.0, 0.0, 1.0],
            LOCKER_SIZE: [0.2, 0.2, 0.2],
            (32, 32): [3.0, 0.0, 0.0],
            (16, 16): [0.0, 3.0, 0.0],
        }
        return list(table.get(image.size, [0.1, 0.1, 0.1]))

    def encode_text(self, text):
        self.text_calls += 1
        query = text.lower()
        if "backpack" in query:
            return [1.0, 0.0, 0.0]
        if "window" in query or "person" in query:
            return [0.0, 1.0, 0.0]
        if "meadow" in query or "field" in query:
            return [0.0, 0.0, 1.0]
        return [0.0, 0.0, 0.2]


def _png(size, color=(20, 40, 60)):
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _assert_private(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"path", "dir", "filesystem_path", "absolute_path", "embedding", "_rgb"}
            _assert_private(item)
    elif isinstance(value, list):
        for item in value:
            _assert_private(item)
    elif isinstance(value, str):
        lowered = value.lower()
        assert "metadex-cases" not in lowered
        assert "\\" not in value or value.startswith("/api/")


def _wait(client, case_id, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/cases/{case_id}")
        if response.status_code == 404:
            return response
        last = response.json()
        if last["status"] in {"ready", "failed"}:
            return response
        time.sleep(0.05)
    raise AssertionError(last)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("METADEX_CASE_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("METADEX_PRELOAD_MODEL", "0")
    monkeypatch.delenv("STILLFRAME_ALLOW_FOLDER_SCAN", raising=False)
    encoder = FakeEncoder()
    vision.set_encoder(encoder)
    cases.reset_for_tests()
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client, encoder
    vision.clear_encoder()
    cases.reset_for_tests()


def test_normalize_and_cosine_are_relative_similarity():
    red = vision.normalize([3, 0, 0])
    green = vision.normalize([0, 4, 0])
    assert vision.cosine(red, red) == pytest.approx(1)
    assert vision.cosine(red, green) == pytest.approx(0)


def test_device_selection_never_invents_a_gpu():
    assert vision.resolve_device("auto", False) == "cpu"
    assert vision.resolve_device("cpu", True) == "cpu"
    assert vision.resolve_device("auto", True) == "cuda"
    assert vision.resolve_device("auto", False, True) == "mps"
    assert vision.resolve_device("cpu", False, True) == "cpu"
    assert vision.embed_batch_size("cpu") >= 16
    assert vision.embed_batch_size("mps") >= 32
    with pytest.raises(vision.EncoderError, match="GPU setup failed"):
        vision.resolve_device("cuda", False)
    with pytest.raises(vision.EncoderError, match="Apple GPU"):
        vision.resolve_device("mps", False, False)


def test_embed_images_batches_one_forward_pass():
    class BatchEncoder:
        def __init__(self):
            self.batches = []
            self.device = "mps"

        def encode_images(self, images):
            self.batches.append(len(images))
            return [[1.0, 0.0, 0.0] for _ in images]

        def encode_image(self, _image):
            raise AssertionError("images should be encoded together")

    encoder = BatchEncoder()
    vision.set_encoder(encoder)
    try:
        from PIL import Image as PILImage

        vectors = vision.embed_images([PILImage.new("RGB", (8, 8), (0, 0, 0)) for _ in range(3)])
    finally:
        vision.clear_encoder()
    assert encoder.batches == [3]
    assert len(vectors) == 3
    assert vectors[0][0] == pytest.approx(1)


def test_missing_weights_are_reported(monkeypatch):
    vision.reset_for_tests()

    def boom():
        raise ImportError("no module named open_clip")

    monkeypatch.setattr(vision, "_import_stack", boom)
    with pytest.raises(vision.EncoderError, match="not installed"):
        vision.load()
    body = vision.status()
    assert body["state"] == "failed"
    assert body["using_gpu"] is False
    assert body["device"] is None
    assert body["error"]
    vision.reset_for_tests()


def test_case_list_is_not_a_missing_route(api):
    client, _encoder = api
    empty = client.get("/api/cases")
    assert empty.status_code == 200
    assert empty.json() == []
    created = client.post("/api/cases/demo")
    assert created.status_code == 200
    listed = client.get("/api/cases")
    assert listed.status_code == 200
    assert created.json()["id"] in {item["id"] for item in listed.json()}
    _assert_private(listed.json())


def test_health_reports_the_actual_device(api):
    client, _encoder = api
    body = client.get("/health").json()
    assert body["service"] == "stillframe"
    assert body["search"]["state"] == "ready"
    assert body["search"]["device"] == "cpu"
    assert body["search"]["using_gpu"] is False
    status = client.get("/api/search/status").json()
    assert status["device"] == "cpu"
    assert status["using_gpu"] is False


def test_demo_indexes_ranks_and_keeps_embeddings(api):
    client, encoder = api
    created = client.post("/api/cases/demo")
    assert created.status_code == 200
    case_id = created.json()["id"]
    ready = _wait(client, case_id)
    body = ready.json()
    assert body["status"] == "ready"
    assert body["source"] == "demo"
    assert body["indexed_count"] == 4
    assert body["using_gpu"] is False
    assert body["device"] == "cpu"
    assert "a red backpack" in body["suggested_queries"]
    _assert_private(body)
    names = {item["filename"] for item in body["files"]}
    assert names == {"red-backpack.png", "person-by-window.png", "clean-meadow.jpg", "locker-note.jpg"}

    images_after_index = encoder.image_calls
    first = client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"})
    assert first.status_code == 200
    ranking = first.json()
    assert ranking["results"][0]["filename"] == "red-backpack.png"
    assert ranking["using_gpu"] is False
    assert ranking["device"] == "cpu"
    assert "not a probability" in ranking["score_meaning"]
    assert "not evidence" in ranking["disclaimer"]
    assert ranking["results"][0]["similarity"] == pytest.approx(1)
    assert ranking["results"][0]["similarity"] > ranking["results"][1]["similarity"]

    second = client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"})
    assert [item["filename"] for item in second.json()["results"]] == [item["filename"] for item in ranking["results"]]
    assert encoder.image_calls == images_after_index
    assert encoder.text_calls == 2

    window = client.post(f"/api/cases/{case_id}/search", json={"query": "a person near a window"})
    assert window.json()["results"][0]["filename"] == "person-by-window.png"

    by_name = {item["filename"]: item for item in body["files"]}
    meadow = by_name["clean-meadow.jpg"]["forensic_summary"]
    locker = by_name["locker-note.jpg"]["forensic_summary"]
    assert meadow["indicator_count"] == 0
    assert meadow["appended"]["present"] is False
    assert meadow["recovered_payloads"] == []
    assert locker["appended"]["present"] is True
    assert locker["appended"]["trailing_bytes"] > 0
    assert any(LOCKER_MESSAGE in payload["preview"] for payload in locker["recovered_payloads"])
    assert "not, by itself, proof" in locker["disclaimer"]

    detail = client.get(f"/api/cases/{case_id}/items/{by_name['locker-note.jpg']['id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    _assert_private(detail_body)
    assert any(LOCKER_MESSAGE in message["text"] for message in detail_body["messages"])
    assert detail_body["integrity"]["unchanged"] is True

    preview = client.get(ranking["results"][0]["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert preview.headers["cache-control"] == "no-store"
    assert preview.headers["content-type"].startswith("image/jpeg")

    calls = encoder.image_calls
    cases.drop_memory_for_tests()
    again = client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"})
    assert again.status_code == 200
    assert again.json()["results"][0]["filename"] == "red-backpack.png"
    assert encoder.image_calls == calls


def test_uploaded_images_rank_by_cosine(api):
    client, _encoder = api
    created = client.post(
        "/api/cases",
        files=[
            ("images", ("green.png", _png((16, 16), (0, 180, 0)), "image/png")),
            ("images", ("red.png", _png((32, 32), (200, 10, 10)), "image/png")),
        ],
        data={"name": "Color case"},
    )
    case_id = created.json()["id"]
    body = _wait(client, case_id).json()
    assert body["indexed_count"] == 2
    found = client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"})
    results = found.json()["results"]
    assert results[0]["filename"] == "red.png"
    assert results[0]["similarity"] == pytest.approx(1)
    assert results[1]["similarity"] == pytest.approx(0)


def test_bad_uploads_do_not_fail_the_case(api, monkeypatch):
    client, _encoder = api
    small = _png((8, 8))
    monkeypatch.setattr("app.main.MAX_BYTES", len(small))
    monkeypatch.setattr("app.analyze.MAX_BYTES", len(small))
    monkeypatch.setattr("app.main.MAX_UPLOAD_FILES", 6)
    created = client.post(
        "/api/cases",
        files=[
            ("images", ("ok.png", small, "image/png")),
            ("images", ("notes.txt", b"not an image", "text/plain")),
            ("images", ("empty.png", b"", "image/png")),
            ("images", ("broken.png", b"\x89PNG\r\n\x1a\nnot-really", "image/png")),
            ("images", ("huge.jpg", b"\xff\xd8\xff" + b"a" * (len(small) + 20), "image/jpeg")),
            ("images", ("../../secret.png", small, "image/png")),
            ("images", ("extra.png", small, "image/png")),
        ],
    )
    assert created.status_code == 200
    body = _wait(client, created.json()["id"]).json()
    assert body["status"] == "ready"
    reasons = {item["filename"]: item["reason"] for item in body["file_errors"]}
    assert "PNG, JPEG, and BMP" in reasons["notes.txt"]
    assert "Empty" in reasons["empty.png"]
    assert "Malformed" in reasons["broken.png"]
    assert "exceeds" in reasons["huge.jpg"].lower()
    assert "at most 6" in reasons["extra.png"]
    assert "secret.png" not in reasons
    assert body["indexed_count"] == 2
    assert any(item["filename"] == "secret.png" and item["status"] == "indexed" for item in body["files"])
    assert all(item["filename"] != "../../secret.png" for item in body["files"])
    root = Path(api_case_dir())
    assert not list(root.rglob("secret.png"))
    _assert_private(body)


def api_case_dir():
    import os

    return os.environ["METADEX_CASE_DIR"]


def test_case_byte_budget_is_per_file(api, monkeypatch):
    client, _encoder = api
    monkeypatch.setattr(cases, "max_total_bytes", lambda: len(_png((32, 32))) + 10)
    small = _png((32, 32))
    created = client.post(
        "/api/cases",
        files=[
            ("images", ("first.png", small, "image/png")),
            ("images", ("second.png", small, "image/png")),
        ],
    )
    body = _wait(client, created.json()["id"]).json()
    assert body["indexed_count"] == 1
    assert any("case size limit" in item["reason"] for item in body["file_errors"])


def test_delete_removes_files_previews_and_embeddings(api):
    client, _encoder = api
    case_id = client.post("/api/cases/demo").json()["id"]
    _wait(client, case_id)
    folder = Path(api_case_dir()) / case_id
    assert folder.is_dir()
    assert any(folder.rglob("preview.jpg"))
    assert any(folder.rglob("manifest.json"))
    deleted = client.delete(f"/api/cases/{case_id}")
    assert deleted.status_code == 204
    assert not folder.exists()
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"}).status_code == 404


def test_expired_case_is_deleted(api):
    client, _encoder = api
    case_id = client.post("/api/cases/demo").json()["id"]
    _wait(client, case_id)
    folder = Path(api_case_dir()) / case_id
    cases.force_expire(case_id)
    assert not folder.exists()
    missing = client.get(f"/api/cases/{case_id}")
    assert missing.status_code == 404
    assert "expired" in missing.json()["detail"]["message"]


def test_folder_scan_is_not_public(api, tmp_path, monkeypatch):
    client, _encoder = api
    blocked = client.post("/api/scan-folder", json={"path": str(tmp_path)})
    assert blocked.status_code == 403
    assert "disabled" in blocked.json()["detail"]["message"]
    monkeypatch.setenv("STILLFRAME_ALLOW_FOLDER_SCAN", "1")
    (tmp_path / "room.png").write_bytes(_png((16, 16)))
    allowed = client.post("/api/scan-folder", json={"path": str(tmp_path), "recursive": False})
    assert allowed.status_code == 200
    assert allowed.json()["summary"]["scanned"] == 1


def test_model_failure_is_actionable(api):
    client, _encoder = api

    class Broken:
        device = "cpu"
        cuda_available = False
        model_name = "test-encoder"

        def encode_image(self, _image):
            raise vision.EncoderError(
                "GPU setup failed: METADEX_DEVICE=cuda but PyTorch cannot see a CUDA device."
            )

        def encode_text(self, _text):
            raise vision.EncoderError(
                "GPU setup failed: METADEX_DEVICE=cuda but PyTorch cannot see a CUDA device."
            )

    vision.set_encoder(Broken())
    case_id = client.post("/api/cases/demo").json()["id"]
    body = _wait(client, case_id).json()
    assert body["status"] == "failed"
    assert body["using_gpu"] is False
    assert "GPU setup failed" in body["model_error"]
    assert any(item["forensic_summary"] for item in body["files"])
    denied = client.post(f"/api/cases/{case_id}/search", json={"query": "a red backpack"})
    assert denied.status_code == 409
    assert "GPU setup failed" in denied.json()["detail"]["message"]


def test_real_byte_limit_constant_is_unchanged():
    assert MAX_BYTES == 10 * 1024 * 1024
