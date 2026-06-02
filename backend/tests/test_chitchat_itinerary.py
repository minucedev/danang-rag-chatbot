"""Test CHITCHAT và ITINERARY_SEARCH pipeline paths."""
from __future__ import annotations
import threading
from unittest.mock import MagicMock

import pytest

# pipeline.py import transformers/torch ở top-level → skip nếu env nhẹ chưa cài.
pytest.importorskip("transformers", reason="pipeline tests require transformers")

from app import config  # noqa: E402
from app.rag import pipeline as pl_module  # noqa: E402
from app.rag.intent import QueryIntent  # noqa: E402


def _make_stub(monkeypatch, intent: QueryIntent, retrieve_results=None):
    """Build pipeline stub với intent cụ thể."""
    # Pin về local generator để test độc lập với .env (tránh gọi Gemini thật).
    monkeypatch.setattr(config, "USE_GEMINI_GENERATION", False)
    pipeline = pl_module.RAGPipeline.__new__(pl_module.RAGPipeline)
    pipeline.encoder = MagicMock()
    pipeline.llm = MagicMock()
    pipeline.client = MagicMock()
    pipeline.reranker = None

    analyzer = MagicMock()
    analyzer.analyze = lambda q: {
        "intent": intent,
        "rewritten_query": q,
        "filters": {"district": None, "min_rating": None, "max_price": None, "min_price": None},
        "source": "stub",
    }
    pipeline.analyzer = analyzer

    async def _retrieve(**_kw):
        return list(retrieve_results or [])

    monkeypatch.setattr(pl_module, "retrieve_by_intent", _retrieve)

    tokens_generated = []

    async def _local_gen(messages, llm, stop, **_kw):
        tokens_generated.append("called")
        yield "ok"

    monkeypatch.setattr(pl_module, "generate_streaming", _local_gen)

    return pipeline, tokens_generated


async def _drain(gen):
    out = []
    async for e in gen:
        out.append(e)
    return out


# ── CHITCHAT ──────────────────────────────────────────────────────────────

async def test_chitchat_yields_empty_sources(monkeypatch):
    pipeline, _ = _make_stub(monkeypatch, QueryIntent.CHITCHAT)
    events = await _drain(pipeline.answer_stream("Bạn là ai?", []))
    sources_event = next(e for e in events if e.get("type") == "sources")
    assert sources_event["items"] == []
    assert sources_event["total"] == 0


async def test_chitchat_skips_qdrant_retrieve(monkeypatch):
    retrieve_called = {"v": False}

    pipeline = pl_module.RAGPipeline.__new__(pl_module.RAGPipeline)
    pipeline.encoder = MagicMock()
    pipeline.llm = MagicMock()
    pipeline.client = MagicMock()
    pipeline.reranker = None

    analyzer = MagicMock()
    analyzer.analyze = lambda q: {
        "intent": QueryIntent.CHITCHAT, "rewritten_query": q,
        "filters": {k: None for k in ("district", "min_rating", "max_price", "min_price")},
        "source": "stub",
    }
    pipeline.analyzer = analyzer

    async def _retrieve_should_not_be_called(**_kw):
        retrieve_called["v"] = True
        return []

    monkeypatch.setattr(pl_module, "retrieve_by_intent", _retrieve_should_not_be_called)

    async def _local(*_a, **_kw):
        yield "reply"

    monkeypatch.setattr(pl_module, "generate_streaming", _local)

    await _drain(pipeline.answer_stream("Bạn là ai?", []))
    assert retrieve_called["v"] is False


async def test_chitchat_emits_token_and_done(monkeypatch):
    pipeline, _ = _make_stub(monkeypatch, QueryIntent.CHITCHAT)
    events = await _drain(pipeline.answer_stream("Xin chào!", []))
    types = [e["type"] for e in events]
    assert "intent" in types
    assert "sources" in types
    assert "token" in types
    assert "done" in types
    assert types[-1] == "done"


async def test_chitchat_intent_event_has_correct_value(monkeypatch):
    pipeline, _ = _make_stub(monkeypatch, QueryIntent.CHITCHAT)
    events = await _drain(pipeline.answer_stream("Hỏi chung", []))
    intent_event = next(e for e in events if e.get("type") == "intent")
    assert intent_event["value"] == "chitchat"
    assert intent_event["display"] == "Trò chuyện"


# ── ITINERARY_SEARCH ───────────────────────────────────────────────────────

async def test_itinerary_yields_sources_and_token(monkeypatch):
    from app.rag.schemas import SearchResultSchema
    fake_result = SearchResultSchema(
        point_id="1", collection="places_danang", score=0.9,
        entity_name="Bà Nà Hills", address="Đà Nẵng",
    )
    pipeline, tokens = _make_stub(
        monkeypatch, QueryIntent.ITINERARY_SEARCH, retrieve_results=[fake_result]
    )
    events = await _drain(pipeline.answer_stream("lịch trình 2 ngày Đà Nẵng", []))
    types = [e["type"] for e in events]
    assert "sources" in types
    assert "token" in types
    assert "done" in types
    assert tokens  # LLM generate được gọi


async def test_itinerary_intent_event(monkeypatch):
    pipeline, _ = _make_stub(monkeypatch, QueryIntent.ITINERARY_SEARCH)
    events = await _drain(pipeline.answer_stream("lịch trình", []))
    intent_event = next(e for e in events if e.get("type") == "intent")
    assert intent_event["value"] == "itinerary_search"
    assert intent_event["display"] == "Lịch trình"
