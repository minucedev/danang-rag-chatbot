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

# pipeline.py import transformers/torch ở top-level (qua llm.py) → skip nếu env nhẹ
# chưa cài (CI không GPU). Khi có thì chạy đầy đủ.
pytest.importorskip("transformers", reason="pipeline tests require transformers")

from app import config  # noqa: E402
from app.rag import pipeline as pl_module  # noqa: E402
from app.rag.gemini_fallback import GeminiFallbackError  # noqa: E402
from app.rag.intent import QueryIntent  # noqa: E402


def _build_pipeline_stub(monkeypatch, *, results, gemini, local, use_gemini_primary=False):
    """Common setup: returns a RAGPipeline with all heavy deps mocked.

    `gemini` / `local` là async-generator factories (nhận messages, stop_event, ... và yield text).
    `use_gemini_primary` pin `config.USE_GEMINI_GENERATION` để test độc lập với .env:
    False → nhánh fallback cũ (Gemini chỉ khi 0 kết quả); True → Gemini primary."""
    monkeypatch.setattr(config, "USE_GEMINI_GENERATION", use_gemini_primary)
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


# ── Gemini primary (USE_GEMINI_GENERATION=True): trả lời khi 0 kết quả ──────
# Pin use_gemini_primary=True để test nhánh mới (pipeline.py §4.1).

async def test_gemini_primary_empty_results_emits_disclaimer_then_answer(monkeypatch):
    """0 kết quả + Gemini primary → disclaimer kiến thức chung rồi tới token Gemini."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", True)

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen(["gen-answer"]),
        local=_async_gen_raises(AssertionError("local should not run")),
        use_gemini_primary=True,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    token_texts = [e["text"] for e in events if e["type"] == "token"]

    # Disclaimer phát TRƯỚC token Gemini đầu tiên, đúng 1 lần, không có "fallback" event.
    assert token_texts[0] == pl_module._NO_DATA_DISCLAIMER
    assert token_texts[1] == "gen-answer"
    assert token_texts.count(pl_module._NO_DATA_DISCLAIMER) == 1
    assert "fallback" not in [e["type"] for e in events]
    assert events[-1]["type"] == "done"


async def test_gemini_primary_empty_results_disclaimer_off(monkeypatch):
    """Flag tắt → không phát disclaimer, chỉ token Gemini."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", False)

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen(["gen-answer"]),
        local=_async_gen_raises(AssertionError("local should not run")),
        use_gemini_primary=True,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    token_texts = [e["text"] for e in events if e["type"] == "token"]

    assert pl_module._NO_DATA_DISCLAIMER not in token_texts
    assert token_texts == ["gen-answer"]


async def test_gemini_primary_with_results_no_disclaimer(monkeypatch):
    """Có kết quả nội bộ → dùng prompt grounded, KHÔNG phát disclaimer kiến thức chung."""
    from app.rag.schemas import SearchResultSchema
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", True)

    result = SearchResultSchema(
        point_id="1", collection="places_danang", score=0.9,
        entity_name="Bà Nà Hills", address="Đà Nẵng",
    )
    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[result],
        gemini=_async_gen(["grounded-answer"]),
        local=_async_gen_raises(AssertionError("local should not run")),
        use_gemini_primary=True,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    token_texts = [e["text"] for e in events if e["type"] == "token"]

    assert pl_module._NO_DATA_DISCLAIMER not in token_texts
    assert token_texts == ["grounded-answer"]


async def test_gemini_primary_empty_fail_before_token_no_double_disclaimer(monkeypatch):
    """Regression: Gemini fail TRƯỚC token đầu → KHÔNG dính disclaimer kiến thức chung
    (đã defer), chỉ có disclaimer 'không khả dụng' rồi local LLM trả lời."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_PREFIX_DISCLAIMER", True)

    pipeline = _build_pipeline_stub(
        monkeypatch,
        results=[],
        gemini=_async_gen_raises(GeminiFallbackError("401", status_code=401)),
        local=_async_gen(["local-answer"]),
        use_gemini_primary=True,
    )

    events = await _drain(pipeline.answer_stream("q", history=[]))
    token_texts = [e["text"] for e in events if e["type"] == "token"]

    # _NO_DATA_DISCLAIMER (deferred) không bao giờ phát vì Gemini chưa ra token nào.
    assert pl_module._NO_DATA_DISCLAIMER not in token_texts
    assert any("không khả dụng" in t for t in token_texts)
    assert any(t == "local-answer" for t in token_texts)
    assert events[-1]["type"] == "done"
