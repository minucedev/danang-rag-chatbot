"""Tests cho api/itineraries.py — envelope camelCase + đường 404 của get_itinerary."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.itineraries import create_itinerary, list_itineraries, get_itinerary
from app.rag.schemas import ItineraryCreate


async def test_create_list_get_camelcase(tmp_db):
    created = await create_itinerary(
        ItineraryCreate(client_id="c1", title="Đà Nẵng 2N", content_md="# Ngày 1\n- Bà Nà")
    )
    res = await list_itineraries(client_id="c1")
    assert set(res.keys()) == {"items", "total"}
    item = res["items"][0]
    assert "createdAt" in item and "updatedAt" in item
    assert "created_at" not in item

    full = await get_itinerary(created.id, client_id="c1")
    assert full.content_md == "# Ngày 1\n- Bà Nà"


async def test_get_missing_raises_404(tmp_db):
    with pytest.raises(HTTPException) as ei:
        await get_itinerary(999, client_id="c1")
    assert ei.value.status_code == 404
