"""Test _find_exact_matches + _build_specific_fallback (ported từ notebook) trong pipeline."""
from __future__ import annotations

import pytest

# pipeline.py import transformers (qua llm.py) ở top-level → skip nếu env nhẹ chưa cài.
pytest.importorskip("transformers", reason="pipeline tests require transformers")

from app.rag import pipeline as pl  # noqa: E402
from app.rag.schemas import SearchResultSchema  # noqa: E402


def _r(name: str, **kw) -> SearchResultSchema:
    return SearchResultSchema(
        point_id="1", collection="places_danang", score=0.5, entity_name=name, **kw
    )


def test_find_exact_matches_base_name():
    docs = [_r("Chợ Cồn"), _r("Chợ Hàn")]
    out = pl._find_exact_matches("chợ cồn mở cửa mấy giờ?", docs)
    assert [r.entity_name for r in out] == ["Chợ Cồn"]


def test_find_exact_matches_branch_disambiguation():
    docs = [
        _r("Highlands Coffee - Trần Phú"),
        _r("Highlands Coffee - Bạch Đằng"),
    ]
    out = pl._find_exact_matches("review highlands coffee trần phú", docs)
    assert [r.entity_name for r in out] == ["Highlands Coffee - Trần Phú"]


def test_find_exact_matches_none_when_not_mentioned():
    docs = [_r("Bà Nà Hills")]
    out = pl._find_exact_matches("gợi ý quán cà phê đẹp", docs)
    assert out == []


def test_build_specific_fallback_lists_alternatives():
    docs = [_r("Novotel Danang", address="36 Bạch Đằng", rating=9.1)]
    msg = pl._build_specific_fallback("khách sạn ABC", docs)
    assert "Novotel Danang" in msg
    assert "36 Bạch Đằng" in msg
    assert "9.1/10" in msg


def test_build_specific_fallback_respects_max_alternatives(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MAX_ALTERNATIVES", 2)
    docs = [_r(f"Nơi {i}", address=f"Số {i}") for i in range(5)]
    msg = pl._build_specific_fallback("xyz", docs)
    assert msg.count("- Nơi") == 2


def test_build_specific_fallback_empty():
    msg = pl._build_specific_fallback("không có gì", [])
    assert "chưa tìm thấy" in msg.lower()


# ── _merge_filters: mở rộng key + luật min(max_price) + list ────────────────

def test_merge_filters_max_price_takes_min():
    out = pl._merge_filters({"max_price": 2_000_000}, {"max_price": 1_000_000})
    assert out["max_price"] == 1_000_000


def test_merge_filters_list_fe_wins():
    out = pl._merge_filters({"cuisine": ["hải sản"]}, {"cuisine": ["lẩu"]})
    assert out["cuisine"] == ["hải sản"]


def test_merge_filters_empty_list_does_not_override():
    out = pl._merge_filters({"cuisine": []}, {"cuisine": ["lẩu"]})
    assert out["cuisine"] == ["lẩu"]


def test_merge_filters_analyzer_fills_when_fe_absent():
    out = pl._merge_filters(None, {"district": "son tra", "star_rating": 4})
    assert out["district"] == "son tra"
    assert out["star_rating"] == 4


def test_merge_filters_keys_track_chatfilters():
    """_merge_filters lặp theo ChatFilters.model_fields → mọi field schema đều được trộn."""
    from app.rag.schemas import ChatFilters
    fe = {k: None for k in ChatFilters.model_fields}
    fe["price_level"] = "low"
    out = pl._merge_filters(fe, {})
    assert out["price_level"] == "low"


# ── Wiring SPECIFIC_SEARCH trong answer_stream: không khớp đúng tên → gợi ý ──

async def test_specific_search_no_exact_emits_alternatives(monkeypatch):
    from unittest.mock import MagicMock
    from app import config
    from app.rag.intent import QueryIntent
    from app.rag.schemas import SearchResultSchema

    monkeypatch.setattr(config, "USE_GEMINI_GENERATION", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)

    pipeline = pl.RAGPipeline.__new__(pl.RAGPipeline)
    pipeline.encoder = MagicMock()
    pipeline.llm = MagicMock()
    pipeline.client = MagicMock()
    pipeline.reranker = None
    analyzer = MagicMock()
    analyzer.analyze = lambda q: {
        "needs_rag": True,
        "intent": QueryIntent.SPECIFIC_SEARCH,
        "entity": ["Khách sạn ABC"],
        "rewritten_query": "Khách sạn ABC",
        "filters": {},
        "source": "stub",
    }
    pipeline.analyzer = analyzer

    near = SearchResultSchema(
        point_id="1", collection="accommodation_hotels_danang", score=0.9,
        entity_name="Novotel Danang", address="36 Bạch Đằng", rating=9.1,
    )

    async def _retrieve(**_kw):
        return [near]

    async def _local_should_not_run(*_a, **_kw):
        raise AssertionError("synthesis should not run on no-exact specific search")
        yield  # pragma: no cover

    async def _noop_log(*_a, **_kw):
        return None

    monkeypatch.setattr(pl, "retrieve_by_intent", _retrieve)
    monkeypatch.setattr(pl, "generate_streaming", _local_should_not_run)
    monkeypatch.setattr(pl, "log_missed_query", _noop_log)

    events = []
    async for e in pipeline.answer_stream("tìm khách sạn ABC", history=[]):
        events.append(e)

    types = [e["type"] for e in events]
    assert types[-1] == "done"
    assert "sources" in types
    token_texts = [e["text"] for e in events if e["type"] == "token"]
    # Phát đúng thông điệp gợi ý "có phải bạn muốn tìm..." chứa địa điểm gần đúng.
    assert any("Novotel Danang" in t for t in token_texts)


async def test_specific_search_exact_match_narrows_and_synthesizes(monkeypatch):
    from unittest.mock import MagicMock
    from app import config
    from app.rag.intent import QueryIntent
    from app.rag.schemas import SearchResultSchema

    monkeypatch.setattr(config, "USE_GEMINI_GENERATION", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)

    pipeline = pl.RAGPipeline.__new__(pl.RAGPipeline)
    pipeline.encoder = MagicMock()
    pipeline.llm = MagicMock()
    pipeline.client = MagicMock()
    pipeline.reranker = None
    analyzer = MagicMock()
    analyzer.analyze = lambda q: {
        "needs_rag": True,
        "intent": QueryIntent.SPECIFIC_SEARCH,
        "entity": ["Novotel Danang"],
        "rewritten_query": "Novotel Danang",
        "filters": {},
        "source": "stub",
    }
    pipeline.analyzer = analyzer

    hit = SearchResultSchema(
        point_id="1", collection="accommodation_hotels_danang", score=0.9,
        entity_name="Novotel Danang", address="36 Bạch Đằng", rating=9.1,
    )

    async def _retrieve(**_kw):
        return [hit]

    async def _local(*_a, **_kw):
        yield "câu trả lời tổng hợp"

    monkeypatch.setattr(pl, "retrieve_by_intent", _retrieve)
    monkeypatch.setattr(pl, "generate_streaming", _local)

    events = []
    async for e in pipeline.answer_stream("Novotel Danang có tốt không?", history=[]):
        events.append(e)

    token_texts = [e["text"] for e in events if e["type"] == "token"]
    assert token_texts == ["câu trả lời tổng hợp"]  # khớp đúng tên → synthesize bình thường
