"""Test BGE cross-encoder reranker — rerank.py."""
from __future__ import annotations
from unittest.mock import MagicMock

import numpy as np
import pytest

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
    results = [_make_result("Good"), _make_result("Bad")]
    reranker = _mock_reranker([0.8, 0.1])
    out = await rerank_results(results, "query", reranker, top_k=5, score_threshold=0.5)
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


async def test_below_threshold_no_fallback_for_specific_search():
    """SPECIFIC_SEARCH: không trả junk khi below threshold — exact_name_search sẽ xử lý."""
    results = [_make_result("Unrelated")]
    reranker = _mock_reranker([0.1])
    out = await rerank_results(
        results, "Novotel Đà Nẵng", reranker, top_k=5, score_threshold=0.5,
        intent=QueryIntent.SPECIFIC_SEARCH,
    )
    assert out == []


async def test_scalar_return_single_pair_no_crash():
    """CrossEncoder trả scalar float khi 1 pair — không crash."""
    results = [_make_result("Single")]
    reranker = _mock_reranker_scalar(0.7)
    out = await rerank_results(results, "query", reranker, top_k=5, score_threshold=0.0)
    assert len(out) == 1
    assert abs(out[0].score - 0.7) < 0.001


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
