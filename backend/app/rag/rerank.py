from __future__ import annotations
import asyncio
from typing import Any, List, Optional

import numpy as np
from sentence_transformers import CrossEncoder

from app import config
from app.rag.intent import QueryIntent
from app.rag.schemas import SearchResultSchema

# Nhóm collection theo loại thực thể — quyết định nhánh boost nào áp dụng.
_RESTAURANT_COLLECTIONS = {config.COLLECTION_RESTAURANTS, config.COLLECTION_RESTAURANT_REVIEWS}
_PLACE_COLLECTIONS = {config.COLLECTION_PLACES, config.COLLECTION_PLACE_REVIEWS}
_HOTEL_COLLECTIONS = {
    config.COLLECTION_ACCOMMODATION_HOTELS,
    config.COLLECTION_ACCOMMODATION_ROOMS,
    config.COLLECTION_ACCOMMODATION_REVIEWS,
}

# Query keyword → từ khoá "lệch" trong tên (ported nguyên từ notebook).
_MISMATCH_RULES = {
    "hải sản": ["gà rán", "burger", "lotteria", "jollibee", "pizza", "chè", "cafe", "coffee"],
    "mì quảng": ["pizza", "cinema", "bar", "lounge", "buffet", "chè", "cafe", "coffee"],
    "đồ nướng": ["bánh sầu riêng", "quán chay", "chè", "trà sữa", "cafe", "coffee"],
    "khách sạn": ["homestay", "hostel", "dorm"],
}


def _doc_text(r: SearchResultSchema) -> str:
    parts = [r.get_display_name()]
    if r.content:
        parts.append(r.content[:300])
    if r.district:
        parts.append(r.district)
    if r.address:
        parts.append(r.address)
    return " ".join(p for p in parts if p)


def _match_any(value: Any, wanted_tokens: list[str]) -> bool:
    """True nếu bất kỳ token mong muốn nào nằm trong value (str hoặc list)."""
    if not wanted_tokens:
        return True
    if value is None:
        return False
    if isinstance(value, list):
        text = " ".join(str(x).lower() for x in value)
    else:
        text = str(value).lower()
    return any(tok in text for tok in wanted_tokens)


def _heuristic_adjust(r: SearchResultSchema, base: float, query_lower: str, f: dict) -> float:
    """Cộng/trừ điểm metadata lên base score (ported từ rerank() của notebook).

    Chỉ chấm các trường vừa có trên SearchResultSchema VỪA được nối dây ở đây
    (district, rating, review_count, cuisine, restaurant_type, tags, star_rating,
    room_view, bed_type). Các tín hiệu notebook chưa có field tương ứng
    (restaurant_category, suitable_for, best_time_to_visit, visit_duration,
    amenities_room, cancellation_policy, children_policy, has_discount) bị bỏ qua cho
    tới khi retrieval/schema bổ sung. Lưu ý: price_level CÓ trên schema nhưng hiện
    chỉ dùng làm filter cứng (retrieval), chưa chấm điểm ở đây.
    """
    score = base
    name_lower = r.get_display_name().lower().strip()
    col = r.collection

    # 1. Quận/huyện khớp
    req_district = f.get("district")
    if req_district and r.district and req_district.lower() == r.district.lower():
        score += 0.3

    # 2. Rating boost theo số lượng review
    rating = r.rating if r.rating is not None else r.parent_rating
    review_count = r.review_count or 0
    if rating is not None:
        if review_count > 5:
            score += min(0.4, float(rating) / 20)
        else:
            score += min(0.15, float(rating) / 40)

    # 3. Mismatch penalty + tiếp khách/sang trọng
    for key, bad_words in _MISMATCH_RULES.items():
        if key in query_lower and any(word in name_lower for word in bad_words):
            score -= 0.8
    if any(word in query_lower for word in ("đối tác", "tiếp khách", "sang trọng")):
        if rating is not None and float(rating) < 7.5:
            score -= 0.3
        if "buffet" in name_lower:
            score -= 0.15

    # 4. Match boost theo loại thực thể
    if col in _RESTAURANT_COLLECTIONS:
        # Chỉ phạt khi doc CÓ field nhưng không khớp; doc thiếu field (vd review không
        # mang cuisine/restaurant_type) giữ trung lập thay vì bị trừ điểm oan.
        if f.get("cuisine") and r.cuisine is not None:
            score += 0.25 if _match_any(r.cuisine, f["cuisine"]) else -0.15
        if f.get("restaurant_type") and r.restaurant_type is not None:
            score += 0.2 if _match_any(r.restaurant_type, f["restaurant_type"]) else -0.1
    elif col in _PLACE_COLLECTIONS:
        if f.get("tags"):
            if _match_any(r.tags, f["tags"]):
                score += 0.15
    elif col in _HOTEL_COLLECTIONS:
        if f.get("star_rating") is not None and r.star_rating is not None:
            score += 0.2 if float(r.star_rating) >= float(f["star_rating"]) else -0.25
        if f.get("room_view") and _match_any(r.room_view, f["room_view"]):
            score += 0.15
        if f.get("bed_type") and _match_any(r.bed_type, f["bed_type"]):
            score += 0.1

    return score


async def rerank_results(
    results: List[SearchResultSchema],
    query: str,
    reranker: Optional[CrossEncoder] = None,
    top_k: int = config.TOP_K_RERANK,
    score_threshold: float = config.RERANK_SCORE_THRESHOLD,
    intent: Optional[QueryIntent] = None,
    extracted: Optional[dict] = None,
) -> List[SearchResultSchema]:
    """Rerank bằng BGE cross-encoder (nếu có) + heuristic metadata.

    Khi `reranker is None` (cấu hình ít RAM): bỏ cross-encoder, dùng điểm cosine
    (`result.score`) làm base rồi vẫn áp heuristic — phần tín hiệu mạnh nhất vẫn chạy.
    `reranker.predict()` là blocking → chạy qua run_in_executor.
    SPECIFIC_SEARCH không dùng below-threshold fallback vì exact_name_search sẽ xử lý.
    """
    if not results:
        return []

    # Base score: cross-encoder nếu có, ngược lại giữ điểm cosine từ retrieval.
    if reranker is not None:
        pairs = [[query, _doc_text(r)] for r in results]
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None, lambda: reranker.predict(pairs, show_progress_bar=False)
            )
            # CrossEncoder trả về scalar float khi chỉ có 1 pair
            base_scores: list[float] = raw.tolist() if np.ndim(raw) > 0 else [float(raw)]
        except Exception as exc:
            print(f"[reranker] predict failed ({type(exc).__name__}: {exc}), returning unranked")
            return results[:top_k]
    else:
        base_scores = [r.score for r in results]

    query_lower = query.lower().strip()
    f = (extracted or {}).get("filters", {}) or {}

    for result, base in zip(results, base_scores):
        result.score = _heuristic_adjust(result, float(base), query_lower, f)

    ranked = sorted(results, key=lambda r: r.score, reverse=True)
    filtered = [r for r in ranked if r.score >= score_threshold]

    if not filtered:
        # SPECIFIC_SEARCH: không trả junk — exact_name_search sẽ fallback
        if intent == QueryIntent.SPECIFIC_SEARCH:
            return []
        return ranked[:top_k]
    return filtered[:top_k]