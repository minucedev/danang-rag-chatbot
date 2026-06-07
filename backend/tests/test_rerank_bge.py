"""Test BGE cross-encoder reranker — rerank.py."""
from __future__ import annotations
import math
from unittest.mock import MagicMock

import numpy as np
import pytest


def _sigmoid(x: float) -> float:
    """Logit → probability, khớp với cách rerank.py chuẩn hoá điểm cross-encoder."""
    return 1.0 / (1.0 + math.exp(-x))

from app.rag.intent import QueryIntent
from app.rag.rerank import rerank_results
from app.rag.schemas import SearchResultSchema


def _make_result(name: str, score: float = 0.5) -> SearchResultSchema:
    r = SearchResultSchema(
        point_id="1",
        collection="places_danang",
        score=score,
        entity_name=name,
        content=f"Nội dung về {name}",
        address="Đà Nẵng",
    )
    return r


def _mock_reranker(scores: list[float]):
    """Trả về mock CrossEncoder với predict() trả numpy array."""
    m = MagicMock()
    m.predict.return_value = np.array(scores)
    return m


def _mock_reranker_scalar(score: float):
    """Simulate CrossEncoder.predict() trả scalar khi chỉ 1 pair."""
    m = MagicMock()
    m.predict.return_value = np.float32(score)
    return m


async def test_basic_reranking_sorts_by_score():
    results = [_make_result("A"), _make_result("B"), _make_result("C")]
    reranker = _mock_reranker([0.1, 0.9, 0.5])
    out = await rerank_results(results, "query", reranker, top_k=3, score_threshold=0.0)
    assert [r.entity_name for r in out] == ["B", "C", "A"]


async def test_top_k_limits_output():
    results = [_make_result(f"Place{i}") for i in range(10)]
    reranker = _mock_reranker(list(range(10, 0, -1)))
    out = await rerank_results(results, "query", reranker, top_k=3, score_threshold=0.0)
    assert len(out) == 3
    assert out[0].entity_name == "Place0"


async def test_threshold_filters_low_scores():
    # Threshold chỉ áp dụng cho SPECIFIC_SEARCH. Logits → sigmoid:
    # sigmoid(0.8)≈0.690 (qua), sigmoid(0.1)≈0.525 (dưới 0.6 → bị lọc).
    results = [_make_result("Good"), _make_result("Bad")]
    reranker = _mock_reranker([0.8, 0.1])
    out = await rerank_results(
        results, "query", reranker, top_k=5, score_threshold=0.6,
        intent=QueryIntent.SPECIFIC_SEARCH,
    )
    assert len(out) == 1
    assert out[0].entity_name == "Good"


async def test_below_threshold_fallback_for_general_intent():
    """Khi không có kết quả nào vượt threshold + intent là GENERAL → trả ranked[:top_k]."""
    results = [_make_result("A"), _make_result("B")]
    reranker = _mock_reranker([0.1, 0.2])
    out = await rerank_results(
        results, "query", reranker, top_k=2, score_threshold=0.9,
        intent=QueryIntent.GENERAL,
    )
    assert len(out) == 2  # fallback: trả ranked dù below threshold


async def test_general_intent_ignores_threshold_with_mixed_scores():
    """GENERAL: threshold bị BỎ QUA hoàn toàn — kể cả khi có kết quả dưới ngưỡng vẫn trả đủ.
    sigmoid(2.0)≈0.881 (trên 0.6) và sigmoid(-2.0)≈0.119 (dưới 0.6) → cả hai vẫn được trả."""
    results = [_make_result("High"), _make_result("Low")]
    reranker = _mock_reranker([2.0, -2.0])
    out = await rerank_results(
        results, "query", reranker, top_k=5, score_threshold=0.6,
        intent=QueryIntent.GENERAL,
    )
    assert [r.entity_name for r in out] == ["High", "Low"]  # không lọc, giữ thứ tự điểm


async def test_sigmoid_normalization_on_array_with_negative_logits():
    """Mảng nhiều logit (gồm âm) → mỗi điểm = sigmoid(logit); heuristic no-op khi không filter."""
    results = [_make_result("Neg"), _make_result("Pos")]
    reranker = _mock_reranker([-2.0, 2.0])
    out = await rerank_results(results, "query", reranker, top_k=5, score_threshold=0.0)
    assert out[0].entity_name == "Pos"  # sigmoid đơn điệu → giữ đúng thứ tự
    assert abs(out[0].score - _sigmoid(2.0)) < 1e-6
    assert abs(out[1].score - _sigmoid(-2.0)) < 1e-6


async def test_below_threshold_no_fallback_for_specific_search():
    """SPECIFIC_SEARCH: không trả junk khi below threshold — exact_name_search sẽ xử lý."""
    results = [_make_result("Unrelated")]
    reranker = _mock_reranker([0.1])
    # sigmoid(0.1)≈0.525 < 0.6 → dưới ngưỡng → trả []
    out = await rerank_results(
        results, "Novotel Đà Nẵng", reranker, top_k=5, score_threshold=0.6,
        intent=QueryIntent.SPECIFIC_SEARCH,
    )
    assert out == []


async def test_scalar_return_single_pair_no_crash():
    """CrossEncoder trả scalar float khi 1 pair — không crash; logit → sigmoid."""
    results = [_make_result("Single")]
    reranker = _mock_reranker_scalar(0.7)
    out = await rerank_results(results, "query", reranker, top_k=5, score_threshold=0.0)
    assert len(out) == 1
    assert abs(out[0].score - _sigmoid(0.7)) < 1e-6


async def test_reranker_predict_failure_returns_unranked():
    """Nếu predict() raise → degrade gracefully, trả results[:top_k] unranked."""
    results = [_make_result("A"), _make_result("B"), _make_result("C")]
    reranker = MagicMock()
    reranker.predict.side_effect = RuntimeError("CUDA OOM")
    out = await rerank_results(results, "query", reranker, top_k=2, score_threshold=0.0)
    assert len(out) == 2  # trả top_k, không crash


async def test_empty_results_returns_empty():
    reranker = _mock_reranker([])
    out = await rerank_results([], "query", reranker)
    assert out == []


# ── Heuristics (ported từ notebook) — chạy cả khi reranker=None ─────────────

def _r(name, collection="places_danang", score=0.5, **kw):
    return SearchResultSchema(
        point_id="1", collection=collection, score=score, entity_name=name, **kw
    )


async def test_heuristic_district_boost_without_reranker():
    """reranker=None: dùng điểm cosine làm base, +0.3 cho doc khớp quận."""
    a = _r("A", district="son tra")
    b = _r("B", district="hai chau")
    extracted = {"filters": {"district": "son tra"}}
    out = await rerank_results(
        [b, a], "q", None, top_k=5, score_threshold=0.0, extracted=extracted
    )
    assert out[0].entity_name == "A"
    assert abs(out[0].score - 0.8) < 1e-6  # 0.5 + 0.3


async def test_heuristic_cuisine_mismatch_penalty():
    seafood = _r("Hải sản Bé Mặn", collection="restaurants_danang", cuisine="hải sản")
    pizza = _r("Pizza 4P", collection="restaurants_danang", cuisine="pizza")
    extracted = {"filters": {"cuisine": ["hải sản"]}}
    out = await rerank_results(
        [pizza, seafood], "quán hải sản", None,
        top_k=5, score_threshold=-10.0, extracted=extracted,
    )
    # pizza: -0.8 (mismatch rule) -0.15 (cuisine) ; seafood: +0.25
    assert out[0].entity_name == "Hải sản Bé Mặn"
    assert abs(out[0].score - 0.75) < 1e-6
    assert abs(out[1].score - (-0.45)) < 1e-6


async def test_heuristic_star_rating_penalty():
    lo = _r("Hotel Lo", collection="accommodation_hotels_danang", star_rating=3)
    hi = _r("Hotel Hi", collection="accommodation_hotels_danang", star_rating=5)
    extracted = {"filters": {"star_rating": 4}}
    out = await rerank_results(
        [lo, hi], "khách sạn", None,
        top_k=5, score_threshold=-10.0, extracted=extracted,
    )
    assert out[0].entity_name == "Hotel Hi"
    assert abs(out[0].score - 0.7) < 1e-6   # 0.5 + 0.2
    assert abs(out[1].score - 0.25) < 1e-6  # 0.5 - 0.25


async def test_heuristic_rating_boost_tiers():
    """review_count>5 → min(0.4, r/20); ngược lại → min(0.15, r/40)."""
    many = _r("Many", rating=8.0, review_count=10)
    few = _r("Few", rating=8.0, review_count=3)
    out = await rerank_results(
        [few, many], "q", None, top_k=5, score_threshold=-10.0
    )
    assert abs(many.score - 0.9) < 1e-6   # 0.5 + 0.4
    assert abs(few.score - 0.65) < 1e-6   # 0.5 + 0.15
    assert out[0].entity_name == "Many"


async def test_heuristic_noop_when_no_filters_and_no_rating():
    """Không filter + không rating → giữ nguyên base (đảm bảo backward-compat)."""
    a = _r("A", score=0.4)
    out = await rerank_results([a], "q", None, top_k=5, score_threshold=0.0)
    assert abs(out[0].score - 0.4) < 1e-6


async def test_heuristic_stacks_on_cross_encoder_score():
    """Có reranker: heuristic CỘNG lên điểm cross-encoder (đã sigmoid), không ghi đè."""
    seafood = _r("Hải sản X", collection="restaurants_danang", cuisine="hải sản")
    reranker = _mock_reranker([0.5])
    extracted = {"filters": {"cuisine": ["hải sản"]}}
    out = await rerank_results(
        [seafood], "quán hải sản", reranker,
        top_k=5, score_threshold=-10.0, extracted=extracted,
    )
    assert abs(out[0].score - (_sigmoid(0.5) + 0.25)) < 1e-6  # sigmoid(0.5) + 0.25 (cuisine)


async def test_review_without_cuisine_not_penalized():
    """Review nhà hàng thiếu cuisine → KHÔNG bị trừ điểm oan khi có filter cuisine."""
    review = _r("Nhận xét hay", collection="restaurant_reviews_danang")  # cuisine=None
    out = await rerank_results(
        [review], "quán hải sản", None, top_k=5, score_threshold=-10.0,
        extracted={"filters": {"cuisine": ["hải sản"]}},
    )
    assert abs(out[0].score - 0.5) < 1e-6  # giữ nguyên base, không -0.15
