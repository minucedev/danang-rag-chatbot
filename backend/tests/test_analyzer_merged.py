"""Test LLMQueryAnalyzer sau khi gộp Router + Extractor (output giàu: needs_rag,
entity, rich filters). Mock create_chat_completion để không cần load LLM thật."""
from __future__ import annotations

from app.rag.analyzer import LLMQueryAnalyzer
from app.rag.intent import QueryIntent


class _StubLLM:
    def __init__(self, content: str):
        self._content = content

    def create_chat_completion(self, **_kw):
        return {"choices": [{"message": {"content": self._content}}]}


def _analyze(content: str, query: str = "q") -> dict:
    return LLMQueryAnalyzer(_StubLLM(content)).analyze(query)


def test_needs_rag_false_maps_to_chitchat():
    out = _analyze(
        '{"needs_rag": false, "intent": "place_search", "entity": [], '
        '"rewritten_query": "", "filters": {}}'
    )
    assert out["needs_rag"] is False
    assert out["intent"] == QueryIntent.CHITCHAT


def test_specific_search_entities_parsed():
    out = _analyze(
        '{"needs_rag": true, "intent": "specific_search", '
        '"entity": ["Novotel Đà Nẵng", "A La Carte"], '
        '"rewritten_query": "Novotel A La Carte", "filters": {}}'
    )
    assert out["intent"] == QueryIntent.SPECIFIC_SEARCH
    assert out["entity"] == ["Novotel Đà Nẵng", "A La Carte"]


def test_rich_filters_cleaned_and_coerced():
    content = (
        '{"needs_rag": true, "intent": "hotel_search", "entity": [], '
        '"rewritten_query": "khách sạn", "filters": {'
        '"district": "son tra", "star_rating": "4", "price_level": "sang trọng", '
        '"cuisine": "hải sản, lẩu", "has_discount": "có", "max_price": "2 triệu", '
        '"room_view": ["sea view"]}}'
    )
    f = _analyze(content)["filters"]
    assert f["district"] == "son tra"
    assert f["star_rating"] == 4
    assert f["price_level"] == "high"
    assert f["cuisine"] == ["hải sản", "lẩu"]
    assert f["has_discount"] is True
    assert f["max_price"] == 2_000_000
    assert f["room_view"] == ["sea view"]


def test_invalid_district_dropped():
    out = _analyze(
        '{"needs_rag": true, "intent": "place_search", "entity": [], '
        '"rewritten_query": "x", "filters": {"district": "quan 1"}}'
    )
    assert out["filters"]["district"] is None


def test_semantic_query_alias_maps_to_rewritten():
    out = _analyze(
        '{"needs_rag": true, "intent": "place_search", "entity": [], '
        '"semantic_query": "chợ đêm", "filters": {}}'
    )
    assert out["rewritten_query"] == "chợ đêm"


def test_fallback_on_bad_json_has_full_shape():
    out = _analyze("hoàn toàn không phải JSON")
    assert out["source"] == "LLM_Fallback"
    assert out["needs_rag"] is True
    assert out["intent"] == QueryIntent.GENERAL
    assert out["entity"] == []
    # filter rỗng đầy đủ key → downstream không KeyError
    assert "cuisine" in out["filters"]
    assert out["filters"]["district"] is None


def test_filters_always_have_all_keys():
    out = _analyze(
        '{"needs_rag": true, "intent": "restaurant_search", "entity": [], '
        '"rewritten_query": "quán ăn", "filters": {"cuisine": ["mì quảng"]}}'
    )
    f = out["filters"]
    for key in ("district", "min_rating", "max_price", "min_price", "star_rating",
                "price_level", "has_discount", "tags", "bed_type", "room_view"):
        assert key in f
    assert f["cuisine"] == ["mì quảng"]
