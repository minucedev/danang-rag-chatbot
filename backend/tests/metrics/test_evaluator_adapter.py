"""Test adapter run_query gom đúng event từ answer_stream (stub pipeline, không GPU)."""
from __future__ import annotations

from app.metrics.evaluator import run_query


class _StubPipeline:
    """Giả lập RAGPipeline.answer_stream: phát chuỗi event như pipeline thật."""

    async def answer_stream(self, query, history, **kwargs):
        yield {"type": "intent", "value": "hotel_search", "display": "Khách sạn"}
        yield {"type": "sources", "items": [
            {"collection": "accommodation_hotels_danang", "entity_name": "KS A"},
            {"collection": "accommodation_reviews_danang"},
        ], "total": 2}
        yield {"type": "token", "text": "Khách sạn "}
        yield {"type": "token", "text": "Mỹ Khê giá tốt."}
        yield {"type": "done"}


class _EmptyPipeline:
    async def answer_stream(self, query, history, **kwargs):
        yield {"type": "intent", "value": "chitchat", "display": "Trò chuyện"}
        yield {"type": "sources", "items": [], "total": 0}
        yield {"type": "token", "text": "Chào bạn!"}
        yield {"type": "done"}


class _ErrorPipeline:
    async def answer_stream(self, query, history, **kwargs):
        yield {"type": "intent", "value": "hotel_search", "display": "Khách sạn"}
        yield {"type": "sources", "items": [{"collection": "accommodation_hotels_danang"}], "total": 1}
        yield {"type": "error", "message": "Gemini bị gián đoạn giữa chừng."}


async def test_run_query_collects_events():
    res = await run_query(_StubPipeline(), "Khách sạn nào gần biển?")

    assert res["intent"] == "hotel_search"
    assert [d["collection"] for d in res["docs"]] == [
        "accommodation_hotels_danang", "accommodation_reviews_danang"]
    assert res["answer"] == "Khách sạn Mỹ Khê giá tốt."
    assert res["error"] is None
    assert res["latency_retrieval"] is not None
    assert res["latency_total"] >= 0


async def test_run_query_empty_sources():
    res = await run_query(_EmptyPipeline(), "Bạn tên gì?")
    assert res["intent"] == "chitchat"
    assert res["docs"] == []
    assert res["answer"] == "Chào bạn!"
    assert res["error"] is None


async def test_run_query_captures_pipeline_error():
    """Event 'error' phải được giữ lại (message) thay vì im lặng coi là câu trả lời rỗng."""
    res = await run_query(_ErrorPipeline(), "Khách sạn nào gần biển?")
    assert res["error"] == "Gemini bị gián đoạn giữa chừng."
    assert res["answer"] == ""  # chưa có token nào trước khi lỗi
