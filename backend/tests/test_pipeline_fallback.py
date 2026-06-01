"""Pin SSE event ordering của `RAGPipeline.answer_stream` quanh nhánh Gemini fallback.

Stub strategy:
- Construct `RAGPipeline` qua `__new__` để bypass `LLMQueryAnalyzer(llm)` (cần load Llama).
- Monkeypatch `pl_module.retrieve_by_intent`, `generate_gemini_streaming`,
  `generate_streaming` (đều là module-level import → patch namespace pl_module).
- `pipeline.analyzer.analyze` là sync (chạy qua `run_in_executor`) → dùng `lambda`.
"""
from __future__ import annotations
import threading
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

# pipeline.py imports llama_cpp ở top-level; skip cả file nếu dep chưa cài (môi
# trường dev/CI nhẹ chưa cần GPU runtime). Khi llama-cpp-python có mặt thì chạy đầy đủ.
pytest.importorskip("llama_cpp", reason="pipeline tests require llama-cpp-python")

from app import config  # noqa: E402
from app.rag import pipeline as pl_module  # noqa: E402
from app.rag.gemini_fallback import GeminiFallbackError  # noqa: E402
from app.rag.intent import QueryIntent  # noqa: E402


def _build_pipeline_stub(monkeypatch, *, results, gemini, local):
    """Common setup: returns a RAGPipeline with all heavy deps mocked.

    `gemini` / `local` là async-generator factories (nhận messages, stop_event, ... và yield text)."""
    pipeline = pl_module.RAGPipeline.__new__(pl_module.RAGPipeline)
    pipeline.encoder = MagicMock()
    pipeline.llm = MagicMock()
    pipeline.client = MagicMock()

    analyzer = MagicMock()
    analyzer.analyze = lambda q: {
        "intent": QueryIntent.GENERAL,
        "rewritten_query": q,
        "filters": {},
        "source": "stub",
    }
    pipeline.analyzer = analyzer
    pipeline.reranker = None  # reranker=None → skip rerank path

    async def _retrieve(**_kw):
        return list(results)

    monkeypatch.setattr(pl_module, "retrieve_by_intent", _retrieve)
    monkeypatch.setattr(pl_module, "generate_gemini_streaming", gemini)
    monkeypatch.setattr(pl_module, "generate_streaming", local)

    # rerank+dedup pass-through (đều là pure func; với results=[] đầu ra cũng [])
    return pipeline


def _async_gen(items):
    """Trả về async-gen factory yield `items` rồi dừng."""
    async def _factory(*_a, **_kw):
        for it in items:
            yield it
    return _factory


def _async_gen_then_raise(items, exc):
    async def _factory(*_a, **_kw):
        for it in items:
            yield it
        raise exc
    return _factory


def _async_gen_raises(exc):
    async def _factory(*_a, **_kw):
        raise exc
        yield  # pragma: no cover — make it a generator
    return _factory


async def _drain(gen) -> list[dict]:
    out = []
    async for e in gen:
        out.append(e)
    return out


# ── Case 1: Gemini OK → fallback + disclaimer + tokens + done ──────────────

async def test_fallback_success_emits_full_sequence(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", True)

    local_called = {"v": False}
    async def _local_should_not_run(*_a, **_kw):
        local_called["v"] = True
        if False:
            yield ""
    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen(["alpha", "beta"]),
        local=_local_should_not_run,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    types = [e["type"] for e in events]

    # intent → sources → fallback → token(disclaimer) → token(alpha) → token(beta) → done
    assert types == ["intent", "sources", "fallback", "token", "token", "token", "done"]
    assert "AI tổng quát" in events[3]["text"]
    assert events[4]["text"] == "alpha"
    assert events[5]["text"] == "beta"
    assert events[2]["provider"] == "gemini"
    assert local_called["v"] is False  # KHÔNG được rơi xuống local LLM


# ── Case 2: Gemini fail TRƯỚC chunk đầu → silently fall through xuống local ──

async def test_fallback_fail_before_commit_uses_local_silently(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen_raises(GeminiFallbackError("401 unauth", status_code=401)),
        local=_async_gen(["local-answer"]),
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    types = [e["type"] for e in events]

    # KHÔNG có `fallback` event (chưa commit); local LLM trả lời
    assert "fallback" not in types
    assert "error" not in types
    assert types[-1] == "done"
    assert any(e.get("text") == "local-answer" for e in events if e["type"] == "token")


# ── Case 3: Gemini fail SAU chunk đầu → error + done, KHÔNG mix với local ───

async def test_fallback_fail_after_commit_emits_error_and_done(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", True)

    local_called = {"v": False}
    async def _local_should_not_run(*_a, **_kw):
        local_called["v"] = True
        if False:
            yield ""

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen_then_raise(
            ["partial"], GeminiFallbackError("500 stream broke", status_code=500)
        ),
        local=_local_should_not_run,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    types = [e["type"] for e in events]

    # intent, sources, fallback, token(disclaimer), token(partial), error, done
    assert "fallback" in types
    assert "error" in types
    assert types[-1] == "done"
    assert local_called["v"] is False  # KHÔNG fall through


# ── Case 4: Không có API key → bỏ qua Gemini hoàn toàn ──────────────────────

async def test_no_api_key_skips_gemini(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen_raises(AssertionError("gemini should not be called")),
        local=_async_gen(["local-only"]),
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    types = [e["type"] for e in events]

    assert "fallback" not in types
    assert any(e.get("text") == "local-only" for e in events if e["type"] == "token")
