"""Pin behavior cho `_collections_for_interests`, `_max_price_for`, và empty-profile
default path của `recommend_for_profile`."""
from __future__ import annotations
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import config
from app.rag import recommend as rec
from app.rag.schemas import TripDates, UserProfile


# ── _collections_for_interests ─────────────────────────────────────────────

def test_empty_interests_defaults_to_places_and_restaurants():
    cols = rec._collections_for_interests([])
    assert cols == {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}


def test_unknown_interest_falls_back_to_default():
    # Gọi trực tiếp với str ngoài Literal (Pydantic ngăn input, nhưng helper vẫn
    # cần defensive fallback nếu danh sách trong code đi vào hàm).
    cols = rec._collections_for_interests(["unknown_x"])
    assert cols == {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}


def test_food_interest_maps_to_restaurants_only():
    cols = rec._collections_for_interests(["food"])
    assert cols == {config.COLLECTION_RESTAURANTS}


def test_nightlife_maps_to_both_places_and_restaurants():
    cols = rec._collections_for_interests(["nightlife"])
    assert cols == {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}


# ── _max_price_for ─────────────────────────────────────────────────────────

def test_max_price_none_when_no_budget():
    assert rec._max_price_for(config.COLLECTION_RESTAURANTS, None) is None


def test_max_price_for_restaurant_low_is_300k():
    assert rec._max_price_for(config.COLLECTION_RESTAURANTS, "low") == 300_000


def test_max_price_for_hotel_low_is_1m():
    assert rec._max_price_for(config.COLLECTION_ACCOMMODATION_HOTELS, "low") == 1_000_000


def test_max_price_for_high_is_none():
    # 'high' → cap None (không giới hạn)
    assert rec._max_price_for(config.COLLECTION_ACCOMMODATION_HOTELS, "high") is None
    assert rec._max_price_for(config.COLLECTION_RESTAURANTS, "high") is None


def test_max_price_for_rooms_uses_hotel_table():
    # ROOMS thuộc _HOTEL_COLLECTIONS nên dùng bảng hotel cap
    assert rec._max_price_for(config.COLLECTION_ACCOMMODATION_ROOMS, "mid") == 2_500_000


@pytest.mark.xfail(
    reason="Known bug: PLACES dùng meal-budget fallback. Sẽ fix bằng PLACES cap riêng."
)
def test_max_price_for_places_should_not_use_meal_budget():
    # PLACES dùng cap RESTAURANT (300k cho 'low') — vé tham quan thường > 300k.
    # Test này pin behavior để khi fix có signal.
    assert rec._max_price_for(config.COLLECTION_PLACES, "low") != 300_000


# ── recommend_for_profile empty-profile path ───────────────────────────────


def _stub_client(scroll_return=None):
    """Stub AsyncQdrantClient. `.scroll` ghi lại kwargs để inspect."""
    client = SimpleNamespace()
    calls = []

    async def _scroll(**kwargs):
        calls.append(kwargs)
        return (scroll_return or [], None)

    client.scroll = _scroll
    client._calls = calls
    return client


async def test_empty_profile_scrolls_only_places_and_restaurants():
    client = _stub_client()
    profile = UserProfile()  # interests=[], không trip_dates, include_hotels mặc định False
    await rec.recommend_for_profile(profile, client, include_hotels=False)
    cols = {c["collection_name"] for c in client._calls}
    assert cols == {config.COLLECTION_PLACES, config.COLLECTION_RESTAURANTS}


async def test_include_hotels_adds_hotel_collection():
    client = _stub_client()
    await rec.recommend_for_profile(UserProfile(), client, include_hotels=True)
    cols = {c["collection_name"] for c in client._calls}
    assert config.COLLECTION_ACCOMMODATION_HOTELS in cols


async def test_trip_dates_implicitly_adds_hotel_collection():
    client = _stub_client()
    profile = UserProfile(
        trip_dates=TripDates(start=date(2026, 6, 1), end=date(2026, 6, 5))
    )
    await rec.recommend_for_profile(profile, client, include_hotels=False)
    cols = {c["collection_name"] for c in client._calls}
    assert config.COLLECTION_ACCOMMODATION_HOTELS in cols
