"""Tests cho exact_name_search + _fuzzy_name_score (retrieval.py) — fallback SPECIFIC_SEARCH.

Mock `client.scroll` (async, trả (points, next_offset)) để khỏi cần Qdrant thật.
"""
from __future__ import annotations
import types

import pytest

from app.rag.retrieval import exact_name_search, _fuzzy_name_score


def _point(pid, entity_name="", place_name=""):
    return types.SimpleNamespace(
        id=pid, payload={"entity_name": entity_name, "place_name": place_name}
    )


class _FakeClient:
    """scroll() trả cùng danh sách points cho mọi collection."""

    def __init__(self, points):
        self._points = points
        self.scroll_calls = 0

    async def scroll(self, **_kw):
        self.scroll_calls += 1
        return (list(self._points), None)


class _RaisingClient:
    async def scroll(self, **_kw):  # pragma: no cover — không được gọi
        raise AssertionError("scroll should not be called")


# ── _fuzzy_name_score ──────────────────────────────────────────────────────

def test_fuzzy_name_score_accent_insensitive():
    # slugify_vn("Bà Nà Hills") == "ba na hills" → khớp tuyệt đối
    assert _fuzzy_name_score("ba na hills", "Bà Nà Hills") == pytest.approx(1.0)


def test_fuzzy_name_score_unrelated_is_low():
    assert _fuzzy_name_score("ba na hills", "Cầu Rồng") < 0.4


# ── exact_name_search ──────────────────────────────────────────────────────

async def test_filters_candidates_below_threshold():
    client = _FakeClient([
        _point("1", entity_name="Novotel Danang Premier Han River"),
        _point("2", entity_name="Highlands Coffee"),
    ])
    out = await exact_name_search("Novotel Danang", client, limit=5)
    assert len(out) == 1
    assert "Novotel" in out[0].entity_name


async def test_dedups_same_point_across_collections():
    # Cùng point id trả về từ cả 3 collection → chỉ xuất hiện 1 lần.
    client = _FakeClient([_point("dup", entity_name="Novotel Danang")])
    out = await exact_name_search("Novotel Danang", client, limit=5)
    assert client.scroll_calls == 3  # 3 collection
    assert len(out) == 1
    assert out[0].point_id == "dup"


async def test_empty_tokens_returns_empty_without_scroll():
    # Tất cả từ < 3 ký tự → không có search token → trả [] và KHÔNG gọi scroll.
    out = await exact_name_search("ab cd", _RaisingClient(), limit=5)
    assert out == []


async def test_respects_limit():
    client = _FakeClient([
        _point(str(i), entity_name=f"Novotel Danang {i}") for i in range(10)
    ])
    out = await exact_name_search("Novotel Danang", client, limit=3)
    assert len(out) == 3


async def test_ranks_best_match_first():
    # Điểm fuzzy khác nhau → kết quả tốt nhất phải đứng đầu (pin sort descending).
    client = _FakeClient([
        _point("weak", entity_name="Novotel Danang Premier Han River Hotel and Spa"),
        _point("best", entity_name="Novotel Danang"),
    ])
    out = await exact_name_search("Novotel Danang", client, limit=5)
    assert out[0].point_id == "best"


async def test_tied_scores_do_not_crash():
    # Regression: 2 point điểm bằng nhau từng gây TypeError khi sort so sánh point.
    client = _FakeClient([
        _point("a", entity_name="Novotel Danang"),
        _point("b", entity_name="Novotel Danang"),
    ])
    out = await exact_name_search("Novotel Danang", client, limit=5)
    assert {r.point_id for r in out} == {"a", "b"}
