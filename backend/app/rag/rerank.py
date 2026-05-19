from __future__ import annotations
from typing import List
from app.rag.intent import QueryIntent, CollectionRegistry
from app.rag.schemas import SearchResultSchema
from app.utils.slugify_vn import slugify_vn


def rerank_results(
    results: List[SearchResultSchema],
    query: str,
    intent: QueryIntent,
) -> List[SearchResultSchema]:
    """Rerank results using multiple signals and strict keyword penalties.

    One deliberate divergence from the validated prototype: the district boost
    compares slug↔slug (slugify_vn) instead of raw
    `district.lower() in query.lower()` — Phase 9b fixed a real diacritic
    mismatch bug there; reverting would reintroduce it. Boost magnitude (0.3)
    unchanged.
    """
    query_lower = query.lower()
    q_slug = slugify_vn(query)

    # Định nghĩa các cặp từ khóa nhạy cảm để tránh hiện tượng "râu ông nọ cắm cằm bà kia"
    mismatch_rules = {
        "hải sản": ["gà rán", "burger", "lotteria", "jollibee", "pizza", "chè", "cafe", "coffee"],
        "mì quảng": ["pizza", "cinema", "bar", "lounge", "buffet", "chè", "cafe", "coffee"],
        "đồ nướng": ["bánh sầu riêng", "quán chay", "chè", "trà sữa", "cafe", "coffee"],
        "khách sạn": ["homestay", "hostel", "dorm"],  # Nếu khách tìm khách sạn xịn, hạ bớt dorm/hostel
    }

    for result in results:
        final_score = result.score
        entity_name_lower = result.get_display_name().lower()

        # 1. Áp dụng trọng số Collection dựa trên Intent
        collection_weight = CollectionRegistry.get_weight(result.collection, intent)
        final_score *= collection_weight

        # 2. Boost điểm cho Quận/Huyện trùng khớp (Tăng mạnh từ 0.15 lên 0.3)
        if result.district and slugify_vn(result.district) in q_slug:
            final_score += 0.3

        # 3. Boost điểm cho thực thể có Rating chất lượng (Dựa trên số lượng review)
        rating_value = result.parent_rating if result.parent_rating else result.rating
        review_count = result.review_count or 0
        if rating_value is not None:
            if review_count > 5:
                final_score += min(0.4, rating_value / 20)
            else:
                final_score += min(0.15, rating_value / 40)  # Ít review thì boost ít tránh điểm ảo

        # 4. CƠ CHẾ PHẠT (PENALTY) ĐỂ KHỬ NHIỄU VECTOR SEARCH
        for key, bad_words in mismatch_rules.items():
            if key in query_lower:
                # Nếu câu hỏi chứa từ khóa cốt lõi (vd: hải sản) nhưng tên thực thể chứa từ lạc quẻ (vd: lotteria)
                if any(word in entity_name_lower for word in bad_words):
                    final_score -= 0.8  # Trừ điểm cực nặng để đẩy xuống đáy danh sách
                    print(f"  [DEBUG RERANK] Hạ điểm phạt thực thể lệch ngành: {result.get_display_name()}")

        # 5. Tối ưu cho nhu cầu tiếp đối tác / sang trọng
        if "đối tác" in query_lower or "tiếp khách" in query_lower or "sang trọng" in query_lower:
            if rating_value and rating_value < 7.5:
                final_score -= 0.3
            if "buffet" in entity_name_lower:
                final_score -= 0.15

        result.score = final_score

    # Sắp xếp lại danh sách sau khi đã xử lý tất cả các chiều thông tin
    results.sort(key=lambda x: x.score, reverse=True)

    return results
