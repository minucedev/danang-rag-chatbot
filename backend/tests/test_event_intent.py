"""Chốt tất định cho intent sự kiện: câu hỏi kiểu 'sự kiện gần đây' PHẢI ra event_search dù
analyzer (model nhỏ 0.5B) phân loại nhầm. Mock LLM trả intent SAI rồi kiểm override theo từ khóa."""
from __future__ import annotations

from app.rag.analyzer import LLMQueryAnalyzer
from app.rag.intent import QueryIntent


class _StubLLM:
    def __init__(self, content: str):
        self._content = content

    def create_chat_completion(self, **_kw):
        return {"choices": [{"message": {"content": self._content}}]}


def _analyze(content: str, query: str) -> dict:
    return LLMQueryAnalyzer(_StubLLM(content)).analyze(query)


_WRONG_GENERAL = '{"needs_rag": true, "intent": "general", "entity": [], "rewritten_query": "x", "filters": {}}'
_WRONG_CHITCHAT = '{"needs_rag": false, "intent": "chitchat", "entity": [], "rewritten_query": "", "filters": {}}'


def test_recent_events_forced_to_event_search():
    out = _analyze(_WRONG_GENERAL, "các sự kiện gần đây ở Đà Nẵng có gì?")
    assert out["intent"] == QueryIntent.EVENT_SEARCH
    assert out["needs_rag"] is True


def test_override_beats_chitchat_coercion():
    # LLM trả needs_rag=false (→ vốn bị ép chitchat); override phải bật lại event_search.
    out = _analyze(_WRONG_CHITCHAT, "tối nay có lễ hội gì không?")
    assert out["intent"] == QueryIntent.EVENT_SEARCH
    assert out["needs_rag"] is True


def test_unaccented_keyword_forced():
    out = _analyze(_WRONG_GENERAL, "da nang co su kien gi sap toi khong")
    assert out["intent"] == QueryIntent.EVENT_SEARCH


def test_activity_phrasing_forced():
    out = _analyze(_WRONG_GENERAL, "cuối tuần này có hoạt động gì vui không?")
    assert out["intent"] == QueryIntent.EVENT_SEARCH


def test_specific_search_not_overridden():
    # Hỏi đích danh 1 sự kiện cụ thể → giữ specific_search (không bị chốt từ khóa cướp).
    content = ('{"needs_rag": true, "intent": "specific_search", '
               '"entity": ["Lễ hội pháo hoa quốc tế Đà Nẵng"], '
               '"rewritten_query": "le hoi phao hoa", "filters": {}}')
    out = _analyze(content, "Lễ hội pháo hoa quốc tế Đà Nẵng năm nay khi nào?")
    assert out["intent"] == QueryIntent.SPECIFIC_SEARCH


def test_non_event_query_not_forced():
    content = ('{"needs_rag": true, "intent": "hotel_search", "entity": [], '
               '"rewritten_query": "khách sạn", "filters": {"district": "son tra"}}')
    out = _analyze(content, "khách sạn 4 sao ở Sơn Trà")
    assert out["intent"] == QueryIntent.HOTEL_SEARCH
