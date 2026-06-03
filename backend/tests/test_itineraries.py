"""Tests cho db/itineraries.py — lưu lịch trình markdown (ẩn danh theo client_id)."""
from __future__ import annotations

from app.db import itineraries as itin_db

MD = "# Ngày 1\n- Bà Nà Hills\n\n# Ngày 2\n- Cầu Rồng, Đà Nẵng"


async def test_create_then_get(tmp_db):
    created = await itin_db.create_itinerary("c1", "Đà Nẵng 2 ngày", MD, session_id="s1")
    got = await itin_db.get_itinerary("c1", created.id)
    assert got is not None
    assert got.title == "Đà Nẵng 2 ngày"
    assert got.content_md == MD  # markdown VN nguyên vẹn
    assert got.session_id == "s1"


async def test_list_returns_summary(tmp_db):
    await itin_db.create_itinerary("c1", "A", MD)
    await itin_db.create_itinerary("c1", "B", MD)
    items = await itin_db.list_itineraries("c1")
    assert {i.title for i in items} == {"A", "B"}


async def test_client_isolation(tmp_db):
    c = await itin_db.create_itinerary("c1", "A", MD)
    assert await itin_db.list_itineraries("c2") == []
    assert await itin_db.get_itinerary("c2", c.id) is None


async def test_delete_scoped_by_client(tmp_db):
    c = await itin_db.create_itinerary("c1", "A", MD)
    await itin_db.delete_itinerary("c2", c.id)  # client khác không xoá được
    assert await itin_db.get_itinerary("c1", c.id) is not None
    await itin_db.delete_itinerary("c1", c.id)
    assert await itin_db.get_itinerary("c1", c.id) is None
