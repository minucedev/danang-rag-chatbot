"""Test _build_filter — gating star_rating/price_level theo collection để tránh
Qdrant xoá sạch point ở collection thiếu field."""
from __future__ import annotations

from app import config
from app.rag.retrieval import _build_filter


def _keys(filt) -> set[str]:
    return {c.key for c in (filt.must or [])} if filt else set()


def test_star_rating_only_applied_to_hotels():
    f = {"star_rating": 4}
    assert "star_rating" in _keys(_build_filter(f, config.COLLECTION_ACCOMMODATION_HOTELS))
    assert "star_rating" not in _keys(_build_filter(f, config.COLLECTION_RESTAURANTS))
    assert "star_rating" not in _keys(_build_filter(f, config.COLLECTION_PLACES))


def test_price_level_gated_to_entity_and_room():
    f = {"price_level": "low"}
    assert "price_level" in _keys(_build_filter(f, config.COLLECTION_RESTAURANTS))
    assert "price_level" in _keys(_build_filter(f, config.COLLECTION_ACCOMMODATION_ROOMS))
    # Review collection thiếu price_level → KHÔNG đặt điều kiện (tránh wipe).
    assert "price_level" not in _keys(_build_filter(f, config.COLLECTION_PLACE_REVIEWS))


def test_collection_none_skips_gated_conditions():
    f = {"star_rating": 4, "price_level": "low", "district": "son tra"}
    keys = _keys(_build_filter(f, None))
    assert "district" in keys
    assert "star_rating" not in keys
    assert "price_level" not in keys


def test_legacy_scalar_filters_unchanged():
    f = {"district": "son tra", "min_rating": 8.0, "max_price": 1_000_000, "min_price": 200_000}
    keys = _keys(_build_filter(f, config.COLLECTION_PLACES))
    assert {"district", "rating", "min_price_vnd"} <= keys


def test_list_filters_do_not_become_qdrant_conditions():
    # cuisine/tags... là rerank-only → không sinh điều kiện Qdrant.
    f = {"cuisine": ["hải sản"], "tags": ["view biển"], "room_view": ["sea view"]}
    assert _build_filter(f, config.COLLECTION_RESTAURANTS) is None


def test_empty_filters_returns_none():
    assert _build_filter(None, config.COLLECTION_PLACES) is None
    assert _build_filter({}, config.COLLECTION_PLACES) is None
