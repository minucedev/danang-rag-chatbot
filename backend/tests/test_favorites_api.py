"""Tests cho api/favorites.py — pin envelope {items,total} camelCase + đường lỗi 500.

Gọi thẳng hàm route (như test_events_api.py) để khỏi import toàn bộ FastAPI app.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.favorites import add_favorite, list_favorites
from app.rag.schemas import FavoriteCreate


def _snap():
    return {"entity_name": "Cầu Rồng", "collection": "places_danang", "point_id": "p1"}


_USER = {"id": "c1", "username": "c1"}


async def test_add_then_list_camelcase_envelope(tmp_db):
    await add_favorite(
        FavoriteCreate(point_id="p1", collection="places_danang", snapshot=_snap()), user=_USER
    )
    res = await list_favorites(user=_USER)
    assert set(res.keys()) == {"items", "total"}
    assert res["total"] == len(res["items"]) == 1
    item = res["items"][0]
    # by_alias → camelCase là contract thật của frontend
    assert "createdAt" in item and "pointId" in item
    assert "created_at" not in item and "point_id" not in item


async def test_list_empty(tmp_db):
    assert await list_favorites(user={"id": "nobody"}) == {"items": [], "total": 0}


async def test_list_failure_raises_500(monkeypatch, tmp_db):
    import app.api.favorites as mod

    async def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(mod.fav_db, "list_favorites", _boom)
    with pytest.raises(HTTPException) as ei:
        await list_favorites(user=_USER)
    assert ei.value.status_code == 500
