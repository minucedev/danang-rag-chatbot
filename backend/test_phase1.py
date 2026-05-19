# -*- coding: utf-8 -*-
"""Phase 1 smoke test — run without GPU or Qdrant."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ["QDRANT_URL"] = "http://dummy"

# --- utils ---
from app.utils.nfc import normalize_nfc
from app.utils.slugify_vn import slugify_vn

assert normalize_nfc("test") == "test"
assert slugify_vn("Hải Châu") == "hai chau", slugify_vn("Hải Châu")
assert slugify_vn("Sơn Trà") == "son tra", slugify_vn("Sơn Trà")
assert slugify_vn("Ngũ Hành Sơn") == "ngu hanh son", slugify_vn("Ngũ Hành Sơn")
print("utils: OK")

# --- intent ---
from app.rag.intent import QueryIntent, CollectionRegistry

assert QueryIntent.HOTEL_SEARCH.display == "Khách sạn"
assert QueryIntent.RESTAURANT_SEARCH.display == "Nhà hàng"
assert QueryIntent.PLACE_SEARCH.display == "Địa điểm"
assert QueryIntent.SPECIFIC_SEARCH.display == "Địa điểm cụ thể"
# SPECIFIC_SEARCH routes to the GENERAL collection set (entity type unknown)
assert set(CollectionRegistry.get_collections_by_intent(QueryIntent.SPECIFIC_SEARCH)) == set(
    CollectionRegistry.get_collections_by_intent(QueryIntent.GENERAL)
)

# CollectionRegistry intent routing
hotel_cols = CollectionRegistry.get_collections_by_intent(QueryIntent.HOTEL_SEARCH)
assert "accommodation_hotels_danang" in hotel_cols
assert "restaurants_danang" not in hotel_cols  # isolation: no mixing
rest_cols = CollectionRegistry.get_collections_by_intent(QueryIntent.RESTAURANT_SEARCH)
assert "restaurants_danang" in rest_cols
assert "accommodation_hotels_danang" not in rest_cols
print("intent: OK")

# --- memory ---
from app.rag.memory import needs_context, build_search_query, build_history_messages

assert needs_context("cái nào") is True
assert needs_context("đó") is True
assert needs_context("Gợi ý khách sạn 4 sao ở Sơn Trà có hồ bơi view biển") is False
assert needs_context("Cái đó giá bao nhiêu") is True

history = [
    {"role": "user", "content": "khách sạn sơn trà", "sources": None},
    {
        "role": "assistant",
        "content": "Có 3 khách sạn",
        "sources": [{"entity_name": "Sala Danang", "parent_entity_name": None}],
    },
]
enriched = build_search_query(history, "cái nào có hồ bơi")
assert "Sala Danang" in enriched, enriched

# Long standalone query should NOT be enriched
standalone = build_search_query(history, "Gợi ý nhà hàng hải sản tốt ở Hải Châu Đà Nẵng")
assert standalone == "Gợi ý nhà hàng hải sản tốt ở Hải Châu Đà Nẵng"

msgs = build_history_messages(history, max_turns=3)
assert msgs == [
    {"role": "user", "content": "khách sạn sơn trà"},
    {"role": "assistant", "content": "Có 3 khách sạn"},
]
print("memory: OK")

# --- schemas (no Qdrant needed) ---
from app.rag.schemas import SearchResultSchema

r = SearchResultSchema(
    point_id="1",
    collection="accommodation_hotels_danang",
    score=1.5,
    entity_name="Hotel Test",
    min_price=1000000,
    max_price=2000000,
    rating=9.1,
    review_count=100,
)
assert r.get_display_name() == "Hotel Test"
assert "1.000.000" in r.get_price_display() or "1,000,000" in r.get_price_display()
assert "9.1" in r.get_rating_display()
print("schemas: OK")

print("\nAll Phase 1 checks passed - OK")
