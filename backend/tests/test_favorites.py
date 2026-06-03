"""Tests cho db/favorites.py — lưu địa điểm yêu thích (ẩn danh theo client_id)."""
from __future__ import annotations

from app.db import favorites as fav_db


def _snap(name="Bà Nà Hills", address="Đà Nẵng"):
    return {
        "entity_name": name,
        "collection": "places_danang",
        "point_id": "p1",
        "address": address,
        "rating": 9.0,
    }


async def test_add_then_list(tmp_db):
    await fav_db.add_favorite("c1", "p1", "places_danang", _snap())
    items = await fav_db.list_favorites("c1")
    assert len(items) == 1
    assert items[0].point_id == "p1"
    assert items[0].snapshot["entity_name"] == "Bà Nà Hills"


async def test_upsert_idempotent_updates_snapshot(tmp_db):
    # Trùng (client, collection, point) → 1 dòng, snapshot cập nhật.
    await fav_db.add_favorite("c1", "p1", "places_danang", _snap("Cũ"))
    await fav_db.add_favorite("c1", "p1", "places_danang", _snap("Mới"))
    items = await fav_db.list_favorites("c1")
    assert len(items) == 1
    assert items[0].snapshot["entity_name"] == "Mới"


async def test_client_isolation(tmp_db):
    await fav_db.add_favorite("c1", "p1", "places_danang", _snap())
    assert await fav_db.list_favorites("c2") == []


async def test_delete_scoped_by_client(tmp_db):
    fav = await fav_db.add_favorite("c1", "p1", "places_danang", _snap())
    # client khác KHÔNG xoá được
    await fav_db.delete_favorite("c2", fav.id)
    assert len(await fav_db.list_favorites("c1")) == 1
    # đúng client xoá được
    await fav_db.delete_favorite("c1", fav.id)
    assert await fav_db.list_favorites("c1") == []


async def test_snapshot_round_trip_preserves_vietnamese(tmp_db):
    snap = _snap("Quán Chay Tình Thương", "207 Cách Mạng Tháng Tám, Cẩm Lệ")
    await fav_db.add_favorite("c1", "p1", "places_danang", snap)
    got = (await fav_db.list_favorites("c1"))[0]
    assert got.snapshot["entity_name"] == "Quán Chay Tình Thương"
    assert "Cẩm Lệ" in got.snapshot["address"]


async def test_same_point_different_collection_distinct(tmp_db):
    # Cùng point_id nhưng khác collection → 2 dòng riêng (UNIQUE gồm collection).
    await fav_db.add_favorite("c1", "p1", "places_danang", _snap())
    await fav_db.add_favorite("c1", "p1", "restaurants_danang", _snap())
    assert len(await fav_db.list_favorites("c1")) == 2
