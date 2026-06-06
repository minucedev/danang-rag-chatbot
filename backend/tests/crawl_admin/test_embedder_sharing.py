"""Bảo vệ MỤC ĐÍCH cốt lõi của việc gộp crawl-admin vào backend: KHÔNG nạp BGE-M3 lần 2.

_get_embedder() có 3 tầng ưu tiên: (1) embedder được inject/cache → (2) encoder của
RAGPipeline đang chạy → (3) fallback nạp mới (CLI/test). Nếu tầng 1/2 hỏng mà rơi xuống
tầng 3 trong process backend → nạp thêm ~2GB → OOM máy 4GB. Test chốt tầng 1+2 không nạp mới.
"""
from __future__ import annotations

from app.crawl_admin import ingest


def test_injected_embedder_wins_without_loading(monkeypatch):
    """set_shared_embedder() → _get_embedder() trả đúng instance đó, KHÔNG nạp model mới."""
    monkeypatch.setattr(ingest, "_embedder", None)  # reset cache module-global

    import sentence_transformers
    def _boom(*a, **k):
        raise AssertionError("KHÔNG được nạp SentenceTransformer khi đã inject embedder")
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _boom)

    sentinel = object()
    ingest.set_shared_embedder(sentinel)
    assert ingest._get_embedder() is sentinel


def test_falls_back_to_pipeline_encoder(monkeypatch):
    """Chưa inject nhưng RAGPipeline đang chạy → dùng pipeline.encoder, KHÔNG nạp mới."""
    monkeypatch.setattr(ingest, "_embedder", None)

    import sentence_transformers
    def _boom(*a, **k):
        raise AssertionError("KHÔNG được nạp model khi đã có pipeline.encoder")
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _boom)

    import app.rag.pipeline as pl
    fake_encoder = object()
    fake_pipeline = type("FakePipeline", (), {"encoder": fake_encoder})()
    monkeypatch.setattr(pl, "_pipeline_instance", fake_pipeline, raising=False)

    assert ingest._get_embedder() is fake_encoder
