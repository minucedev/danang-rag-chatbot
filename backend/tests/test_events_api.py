"""Tests cho GET /api/events (app/api/events.py).

Gọi thẳng hàm route `list_events` (truyền tham số tường minh) để khỏi phải import
toàn bộ FastAPI app (torch/transformers). Validation ge/le của Query là cơ chế
framework, được FastAPI enforce ở tầng HTTP nên không test ở đây.
"""
from __future__ import annotations
import time

import pytest
from fastapi import HTTPException

from app.api.events import list_events
from app.db.events import upsert_events, EventDict

NOW = int(time.time())
DAY = 86400


def _ev(title, sid, offset=DAY, district=None, image_url=None):
    return EventDict(
        source="test", source_event_id=sid, title=title,
        start_time=NOW + offset, end_time=NOW + offset + 3600,
        district=district, address=None, description=f"Desc {title}",
        venue_name=f"Venue {title}", latitude=None, longitude=None,
        url=f"https://e/{sid}", image_url=image_url, raw={},
    )


async def test_returns_upcoming_within_window(tmp_db):
    await upsert_events([_ev("Festival", "f1"), _ev("Concert", "c1", offset=DAY * 3)])
    res = await list_events(district=None, days=60, limit=12)
    assert res["total"] == 2
    assert {e["title"] for e in res["items"]} == {"Festival", "Concert"}


async def test_excludes_outside_window_then_includes_with_wider_days(tmp_db):
    """Pin phép tính cửa sổ now → now + days*86400."""
    await upsert_events([_ev("Far", "far", offset=DAY * 90)])
    assert (await list_events(district=None, days=60, limit=12))["total"] == 0
    assert (await list_events(district=None, days=120, limit=12))["total"] == 1


async def test_district_filter(tmp_db):
    await upsert_events([
        _ev("HC", "hc1", district="hai chau"),
        _ev("ST", "st1", district="son tra"),
    ])
    res = await list_events(district="hai chau", days=60, limit=12)
    assert res["total"] == 1
    assert res["items"][0]["title"] == "HC"


async def test_response_shape_and_image_url_passthrough(tmp_db):
    await upsert_events([_ev("WithImg", "i1", image_url="https://img/x.jpg")])
    res = await list_events(district=None, days=60, limit=12)
    assert set(res.keys()) == {"items", "total"}
    assert res["total"] == len(res["items"])
    assert res["items"][0]["image_url"] == "https://img/x.jpg"


async def test_limit_is_honored(tmp_db):
    await upsert_events([_ev(f"E{i}", f"e{i}", offset=DAY * (i + 1)) for i in range(5)])
    res = await list_events(district=None, days=60, limit=2)
    assert res["total"] == 2
    # ORDER BY start_time ASC → đúng 2 sự kiện sớm nhất (bắt regression đổi/bỏ ORDER BY).
    assert [e["title"] for e in res["items"]] == ["E0", "E1"]


async def test_empty_db_returns_empty(tmp_db):
    res = await list_events(district=None, days=60, limit=12)
    assert res == {"items": [], "total": 0}


async def test_db_failure_raises_503(monkeypatch):
    """Lỗi tầng dưới → HTTPException(503) thay vì 500 trần (có log)."""
    import app.api.events as ev_mod

    async def _boom(**_kw):
        raise RuntimeError("DB down")

    monkeypatch.setattr(ev_mod, "retrieve_events", _boom)
    with pytest.raises(HTTPException) as exc_info:
        await list_events(district=None, days=60, limit=12)
    assert exc_info.value.status_code == 503
