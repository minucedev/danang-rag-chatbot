from __future__ import annotations
from typing import List
from app.rag.intent import QueryIntent, CollectionRegistry
from app.rag.schemas import SearchResultSchema
from app.utils.nfc import normalize_nfc


def rerank_results(
    results: List[SearchResultSchema],
    query: str,
    intent: QueryIntent,
) -> List[SearchResultSchema]:
    query_lower = normalize_nfc(query).lower()

    for r in results:
        score = r.score
        score *= CollectionRegistry.get_weight(r.collection, intent)

        # Rating boost (use parent rating for reviews)
        rating = r.parent_rating or r.rating
        if rating is not None:
            score += min(0.5, rating / 20)

        # District match boost
        if r.district and r.district.lower() in query_lower:
            score += 0.15

        # Intent-specific boosts
        if intent == QueryIntent.PRICE_SEARCH and r.min_price is not None:
            score += 0.2
        if intent == QueryIntent.ROOM_SEARCH and r.capacity is not None:
            score += 0.25
        if intent == QueryIntent.REVIEW_SEARCH and r.content:
            score += min(0.2, len(r.content) / 1000)

        # Completeness boost
        info = 0.0
        if rating is not None:
            info += 0.05
        if r.min_price is not None:
            info += 0.05
        if r.address:
            info += 0.03
        if r.district:
            info += 0.03
        score += min(0.2, info)

        r.score = score

    results.sort(key=lambda x: x.score, reverse=True)
    return results
