"""Test runner: guard 1-lượt + pipeline None, happy-path, và cô lập câu lỗi."""
from __future__ import annotations

import pytest

from app.metrics import runner, store


class _StubPipeline:
    async def answer_stream(self, query, history, **kwargs):
        yield {"type": "intent", "value": "hotel_search", "display": "Khách sạn"}
        yield {"type": "sources", "items": [{"collection": "accommodation_hotels_danang"}], "total": 1}
        yield {"type": "token", "text": "Khách sạn Mỹ Khê có địa chỉ ở Sơn Trà, mức giá 900 nghìn VND, đánh giá tốt."}
        yield {"type": "done"}


class _ErrorPipeline:
    async def answer_stream(self, query, history, **kwargs):
        yield {"type": "intent", "value": "hotel_search", "display": "Khách sạn"}
        yield {"type": "sources", "items": [], "total": 0}
        yield {"type": "error", "message": "lỗi giả lập"}


_GEN_ITEM = {
    "id": "H01", "category": "Khách sạn", "query": "Khách sạn nào gần biển?",
    "expected_intent": "hotel_search", "expected_collections": ["accommodation_hotels_danang"],
    "keywords": ["khách sạn", "giá"], "gold_answer": "Một số khách sạn ven biển.",
}
_ITIN_ITEM = {
    "id": "IT01", "category": "Lịch trình", "query": "Kế hoạch 2 ngày",
    "expected_intent": "itinerary_search", "expected_collections": ["places_danang"],
    "keywords": ["ngày"], "gold_answer": "Ngày 1...",
    "eval_criteria": {"has_daily_structure": True, "min_days_mentioned": 1},
}


@pytest.fixture
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")


async def test_guard_single_run(monkeypatch):
    """Đang chạy → trả None và KHÔNG đụng state lượt đang chạy."""
    monkeypatch.setitem(runner._state, "running", True)
    assert await runner.run_eval("both", False) is None
    assert runner._state["running"] is True  # không bị reset bởi guard


async def test_guard_pipeline_none(monkeypatch):
    monkeypatch.setattr(runner, "_get_pipeline", lambda: None)
    assert await runner.run_eval("both", False) is None
    assert runner._state["running"] is False


async def test_happy_path(monkeypatch, tmp_runs):
    monkeypatch.setattr(runner, "_get_pipeline", lambda: _StubPipeline())
    monkeypatch.setattr(runner, "BENCHMARK", [_GEN_ITEM])
    monkeypatch.setattr(runner, "BENCHMARK_ITINERARY", [_ITIN_ITEM])

    result = await runner.run_eval("both", enable_judge=False)

    assert result is not None
    assert result["errored_ids"] == []
    assert len(result["retrieval_rows"]) == 2  # general + itinerary
    assert len(result["itinerary_rows"]) == 1
    assert result["report_card"]
    assert runner._state["running"] is False
    # đã lưu xuống đĩa, đọc lại được
    assert store.get_run(result["id"]) is not None


async def test_errored_query_excluded(monkeypatch, tmp_runs):
    monkeypatch.setattr(runner, "_get_pipeline", lambda: _ErrorPipeline())
    monkeypatch.setattr(runner, "BENCHMARK", [_GEN_ITEM])
    monkeypatch.setattr(runner, "BENCHMARK_ITINERARY", [])

    result = await runner.run_eval("general", enable_judge=False)

    assert result is not None
    assert result["errored_ids"] == ["H01"]
    assert result["retrieval_rows"] == []  # câu lỗi không vào metric
    assert result["generation_rows"] == []
