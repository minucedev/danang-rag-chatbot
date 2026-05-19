from __future__ import annotations
from typing import List, Optional
from app.rag.intent import QueryIntent, CollectionRegistry
from app.rag.schemas import SearchResultSchema
from app.utils.slugify_vn import slugify_vn

# Boost large enough to float a query-named place above the per-candidate
# stack (rating .5 + district .15 + intent .25 + completeness .2).
NAME_MATCH_BOOST = 0.6

# Generic words stripped from an entity name before matching it to the query.
# 'da'/'nang'/'danang' MUST stay here: every place ends in "Đà Nẵng", so
# without stripping them the name core would substring-match almost any query.
_GENERIC = {
    "khach", "san", "nha", "hang", "quan", "hotel", "resort", "homestay",
    "villa", "motel", "the", "khu", "nghi", "duong", "da", "nang", "danang",
}

# Recommendation/list cues (slugified, space-padded). Their presence means the
# user wants a list, not a focused answer about one named place.
_RECO_CUES = (
    " goi y", " de xuat", " gioi thieu", " tot nhat", " danh sach", " liet ke",
    " nao", " recommend", " list", " top ", " cac ", " nhung ", " o dau", " gan ",
)


def _name_matches(name: str, q_slug: str) -> bool:
    """True if the entity's distinctive name (generics stripped) is in q_slug.

    Contiguous substring on slug — data names are long official forms
    ("Khách sạn Mường Thanh Luxury Đà Nẵng") while users type the short form.
    Length guards (core ≥4 chars, ≥1 multi-char token) reject a too-short
    leftover that would spuriously substring-match an unrelated query.
    """
    core = " ".join(t for t in slugify_vn(name).split() if t not in _GENERIC)
    return len(core) >= 4 and any(len(t) >= 2 for t in core.split()) and core in q_slug


def rerank_results(
    results: List[SearchResultSchema],
    query: str,
    intent: QueryIntent,
) -> List[SearchResultSchema]:
    q_slug = slugify_vn(query)

    for r in results:
        score = r.score
        score *= CollectionRegistry.get_weight(r.collection, intent)

        # Rating boost (use parent rating for reviews)
        rating = r.parent_rating or r.rating
        if rating is not None:
            score += min(0.5, rating / 20)

        # District match boost (slug ↔ slug so diacritics don't break the match)
        if r.district and slugify_vn(r.district) in q_slug:
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

        if _name_matches(r.get_display_name(), q_slug):
            score += NAME_MATCH_BOOST

        r.score = score

    results.sort(key=lambda x: x.score, reverse=True)
    return results


def _has_reco_cue(q_slug: str) -> bool:
    padded = f" {q_slug} "
    return any(cue in padded for cue in _RECO_CUES)


def find_specific_match(
    results: List[SearchResultSchema], query: str
) -> Optional[SearchResultSchema]:
    """Return the place a 'specific lookup' query targets, else None.

    None when the query carries a recommendation cue (user wants a list) or no
    result's name appears in it. `results` must already be reranked, so the
    name-boosted target is at the front.
    """
    q_slug = slugify_vn(query)
    if _has_reco_cue(q_slug):
        return None
    for r in results:
        if _name_matches(r.get_display_name(), q_slug):
            return r
    return None
