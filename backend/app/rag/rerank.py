from __future__ import annotations
import asyncio
from typing import List, Optional

import numpy as np
from sentence_transformers import CrossEncoder

from app import config
from app.rag.intent import QueryIntent
from app.rag.schemas import SearchResultSchema


def _doc_text(r: SearchResultSchema) -> str:
    parts = [r.get_display_name()]
    if r.content:
        parts.append(r.content[:300])
    if r.district:
        parts.append(r.district)
    if r.address:
        parts.append(r.address)
    return " ".join(p for p in parts if p)


async def rerank_results(
    results: List[SearchResultSchema],
    query: str,
    reranker: CrossEncoder,
    top_k: int = config.TOP_K_RERANK,
    score_threshold: float = config.RERANK_SCORE_THRESHOLD,
    intent: Optional[QueryIntent] = None,
) -> List[SearchResultSchema]:
    """Rerank bằng BGE cross-encoder.

    `reranker.predict()` là blocking — chạy qua run_in_executor.
    SPECIFIC_SEARCH không dùng below-threshold fallback vì exact_name_search sẽ xử lý.
    """
    if not results:
        return []

    pairs = [[query, _doc_text(r)] for r in results]

    loop = asyncio.get_running_loop()
    try:
        raw = await loop.run_in_executor(
            None, lambda: reranker.predict(pairs, show_progress_bar=False)
        )
        # CrossEncoder trả về scalar float khi chỉ có 1 pair
        scores: list[float] = raw.tolist() if np.ndim(raw) > 0 else [float(raw)]
    except Exception as exc:
        print(f"[reranker] predict failed ({type(exc).__name__}: {exc}), returning unranked")
        return results[:top_k]

    for result, score in zip(results, scores):
        result.score = float(score)

    ranked = sorted(results, key=lambda r: r.score, reverse=True)
    filtered = [r for r in ranked if r.score >= score_threshold]

    if not filtered:
        # SPECIFIC_SEARCH: không trả junk — exact_name_search sẽ fallback
        if intent == QueryIntent.SPECIFIC_SEARCH:
            return []
        return ranked[:top_k]
    return filtered[:top_k]
