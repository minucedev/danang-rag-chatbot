"""Recommendation logic — ported from `PBL_ lấy dữ liệu/src/chat/highlightFilter.ts`.

Tinh thần PBL: lọc highlight theo UserProfile (interests, tripDates, budget),
relax nếu candidates < MIN_KEPT, score `confidence*0.6 + rank*0.4`, top-N.

Khác biệt với PBL: backend không có events; bù lại có 3 collection chính
(places / restaurants / hotels) trong Qdrant, dùng `scroll()` để lấy candidate
pool theo filter (không cần vector query vì recommend không kèm câu hỏi cụ thể).
"""
from __future__ import annotations
import asyncio
import math
import re
from typing import List, Optional

from qdrant_client import AsyncQdrantClient

from app import config
from app.rag.retrieval import _build_filter, _norm_tags
from app.rag.schemas import (
    Interest,
    RecommendItem,
    RecommendResponse,
    SearchResultSchema,
    UserProfile,
)


# ─── Hằng số map (port của INTEREST_TO_CATEGORIES bên PBL) ────────────────

INTEREST_TO_COLLECTIONS: dict[str, list[str]] = {
    "beach":     [config.COLLECTION_PLACES],
    "food":      [config.COLLECTION_RESTAURANTS],
    "cafe":      [config.COLLECTION_RESTAURANTS],
    "culture":   [config.COLLECTION_PLACES],
    "nightlife": [config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS],
    "family":    [config.COLLECTION_PLACES],
    "adventure": [config.COLLECTION_PLACES],
    "shopping":  [config.COLLECTION_PLACES],
}

# Ngưỡng giá theo budget_level (VND). `None` = không cap.
BUDGET_MAX_RESTAURANT = {"low": 300_000, "mid": 800_000, "high": None}
BUDGET_MAX_HOTEL      = {"low": 1_000_000, "mid": 2_500_000, "high": None}

MIN_KEPT = 5                       # giống PBL highlightFilter.ts
TOP_N_DEFAULT = 10
SCROLL_LIMIT_PER_COLLECTION = 50

_HOTEL_COLLECTIONS = {config.COLLECTION_ACCOMMODATION_HOTELS, config.COLLECTION_ACCOMMODATION_ROOMS}


# ─── Helpers ──────────────────────────────────────────────────────────────

def _collections_for_interests(interests: list[str]) -> set[str]:
    """interests → tập collections cần quét. Rỗng → [places, restaurants] (giống PBL: không
    có interest thì giữ tất cả)."""
    if not interests:
        return {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}
    out: set[str] = set()
    for it in interests:
        out.update(INTEREST_TO_COLLECTIONS.get(it, []))
    return out or {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}


def _max_price_for(collection: str, budget_level: Optional[str]) -> Optional[float]:
    if not budget_level:
        return None
    if collection in _HOTEL_COLLECTIONS:
        cap = BUDGET_MAX_HOTEL.get(budget_level)
    else:
        cap = BUDGET_MAX_RESTAURANT.get(budget_level)
    return float(cap) if cap is not None else None


def _payload_to_schema(point_id: str, collection: str, payload: dict) -> SearchResultSchema:
    """Map Qdrant payload → SearchResultSchema. Tương đồng với phần mapping trong
    `retrieval.retrieve_from_collection` nhưng không cần score (scroll không trả score)."""
    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _i(v):
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return SearchResultSchema(
        point_id=str(point_id),
        collection=collection,
        score=0.0,
        entity_name=payload.get("entity_name", "") or "",
        place_name=payload.get("place_name", "") or "",
        district=payload.get("district", "") or "",
        rating=_f(payload.get("rating")),
        min_price=_f(payload.get("min_price_vnd")),
        max_price=_f(payload.get("max_price_vnd")),
        address=payload.get("address", "") or "",
        content=payload.get("content", "") or "",
        cuisine=payload.get("cuisine"),
        restaurant_type=payload.get("restaurant_type"),
        time_open=payload.get("time_open"),
        time_close=payload.get("time_close"),
        tags=_norm_tags(payload.get("tags")),
        review_count=_i(payload.get("review_count")),
        star_rating=_f(payload.get("star_rating")),
        price_level=payload.get("price_level"),
        price_currency=payload.get("price_currency"),
    )


async def _scroll_collection(
    client: AsyncQdrantClient,
    collection: str,
    filters: dict,
) -> List[SearchResultSchema]:
    """Filter-only retrieval bằng Qdrant scroll. Không có vector query → không cần encode."""
    try:
        scroll_filter = _build_filter(filters)
        points, _next = await client.scroll(
            collection_name=collection,
            scroll_filter=scroll_filter,
            limit=SCROLL_LIMIT_PER_COLLECTION,
            with_payload=True,
            with_vectors=False,
        )
    except asyncio.CancelledError:
        # Đừng nuốt cancellation — phải để task unwind sạch khi client disconnect.
        raise
    except Exception as e:
        # Vẫn nuốt các lỗi khác (Qdrant auth/network/malformed filter) để recommend
        # không 500 toàn bộ chỉ vì 1 collection lỗi. Log lại loại lỗi cụ thể để dễ debug.
        print(f"Warning: scroll({collection}) failed: {type(e).__name__}: {e}")
        return []

    return [_payload_to_schema(p.id, collection, p.payload or {}) for p in points]


# Pre-compile word-boundary patterns: dùng `\b` để token "gà" không match trong
# "ngà", "bò" không match trong "bò bía chay". Vietnamese diacritics tính là \w
# trong Python regex (Unicode mode mặc định) nên \b hoạt động đúng.
_MEAT_TOKENS = ("hải sản", "bbq", "nướng", "bò", "gà", "heo")
_MEAT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _MEAT_TOKENS) + r")\b",
    re.UNICODE,
)


def _violates_dietary(r: SearchResultSchema, dietary: Optional[str]) -> bool:
    """Heuristic đơn giản: nếu user khai 'vegetarian/chay' mà entity_name/cuisine
    có từ thịt → penalty. Word-boundary để tránh false-positive (vd 'gà' trong 'ngà')."""
    if not dietary:
        return False
    d = dietary.lower()
    if not ("chay" in d or "vegetarian" in d or "vegan" in d):
        return False

    haystack = " ".join(filter(None, [
        (r.entity_name or "").lower(),
        (r.place_name or "").lower(),
        (r.cuisine or "").lower(),
        (r.restaurant_type or "").lower(),
    ]))

    # Nếu entity tự khai "chay" trong tên/cuisine → tin tưởng, không penalty bất kể
    # token meat khác (vd "Quán chay BBQ", "Bò bía chay").
    if re.search(r"\bchay\b", haystack):
        return False

    return bool(_MEAT_PATTERN.search(haystack))


def _matched_interests_for(r: SearchResultSchema, profile_interests: list[str]) -> list[str]:
    matched = []
    for it in profile_interests:
        cols = INTEREST_TO_COLLECTIONS.get(it, [])
        if r.collection in cols:
            matched.append(it)
    return matched


def _score(
    r: SearchResultSchema,
    profile: UserProfile,
    matched_interests: list[str],
) -> float:
    """Port tinh thần của PBL: `confidence*0.6 + rank*0.4`.
    Ở đây confidence ≈ rating chuẩn hoá; rank ≈ review_count + interest_match + dietary."""
    base = (r.rating or 0.0) / 10.0
    review_boost = min(0.2, math.log1p(r.review_count or 0) / 10.0)
    interest_boost = 0.2 if matched_interests else 0.0

    # Budget penalty: nếu min_price vượt ngưỡng budget cho loại collection → trừ điểm
    budget_pen = 0.0
    cap = _max_price_for(r.collection, profile.budget_level)
    if cap is not None and r.min_price is not None and r.min_price > cap:
        budget_pen = -0.3

    dietary_pen = -0.4 if _violates_dietary(r, profile.dietary) else 0.0

    return base * 0.6 + (review_boost + interest_boost) * 0.4 + budget_pen + dietary_pen


# ─── Main entrypoint ──────────────────────────────────────────────────────

async def recommend_for_profile(
    profile: UserProfile,
    client: AsyncQdrantClient,
    limit: int = TOP_N_DEFAULT,
    district: Optional[str] = None,
    include_hotels: bool = False,
) -> RecommendResponse:
    notes: list[str] = []

    # 1) Suy ra collections từ interests
    collections = _collections_for_interests(profile.interests)
    if include_hotels or profile.trip_dates is not None:
        collections.add(config.COLLECTION_ACCOMMODATION_HOTELS)

    # 2) Scroll candidates song song cho từng collection (mỗi cái có cap giá riêng)
    async def _pull(col: str) -> list[SearchResultSchema]:
        f: dict = {}
        if district:
            f["district"] = district
        cap = _max_price_for(col, profile.budget_level)
        if cap is not None:
            f["max_price"] = cap
        return await _scroll_collection(client, col, f)

    nested = await asyncio.gather(*[_pull(c) for c in collections])
    candidates: list[SearchResultSchema] = [r for batch in nested for r in batch]

    # 3) Score
    def _score_pair(r: SearchResultSchema) -> tuple[float, list[str]]:
        mi = _matched_interests_for(r, profile.interests)
        return _score(r, profile, mi), mi

    scored = [(r, *_score_pair(r)) for r in candidates]

    # 4) Lọc theo interest (nếu user có interests) + relax giống PBL.
    # Hotels được opt-in riêng (include_hotels / trip_dates) nên luôn pass qua filter này.
    relaxed = False
    if profile.interests:
        filtered = [
            (r, s, mi) for (r, s, mi) in scored
            if mi or r.collection in _HOTEL_COLLECTIONS
        ]
        if len(filtered) < MIN_KEPT:
            filtered = scored
            relaxed = True
            notes.append("relaxed_interests")
    else:
        filtered = scored

    # 5) Dedupe theo display name (giữ điểm cao nhất)
    by_name: dict[str, tuple[SearchResultSchema, float, list[str]]] = {}
    for r, s, mi in filtered:
        name = r.get_display_name()
        if name in ("Unknown", "Đang cập nhật"):
            continue
        prev = by_name.get(name)
        if prev is None or s > prev[1]:
            by_name[name] = (r, s, mi)

    # 6) Sort desc + cắt top-N
    ranked = sorted(by_name.values(), key=lambda x: x[1], reverse=True)[:limit]

    items = [
        RecommendItem(
            place_id=r.point_id,
            name=r.get_display_name(),
            collection=r.collection,
            district=r.district,
            rating=r.parent_rating if r.parent_rating else r.rating,
            rating_display=r.get_rating_display(),
            price_display=r.get_price_display(),
            address=r.get_address_display(),
            # Clip vào [0,1] để khớp `Field(ge=0.0, le=1.0)`: dietary_pen -0.4 +
            # budget_pen -0.3 có thể đẩy score xuống âm; rating cao bất thường có thể
            # đẩy lên >1 nếu công thức đổi sau này.
            recommend_score=max(0.0, min(1.0, round(s, 4))),
            matched_interests=mi,
        )
        for (r, s, mi) in ranked
    ]

    return RecommendResponse(
        items=items,
        profile_used=profile,
        relaxed=relaxed,
        notes=notes,
    )
