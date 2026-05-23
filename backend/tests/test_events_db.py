"""Tests cho app/db/events.py: upsert idempotent, query window/district, prune."""
from __future__ import annotations
import time

import pytest

from app.db.events import upsert_events, query_events, prune_old_events, EventDict

NOW = int(time.time())
DAY = 86400


def _ev(title: str, source_id: str, start_offset: int = 0, district: str | None = None) -> EventDict:
    return EventDict(
        source="test",
        source_event_id=source_id,
        title=title,
        description=None,
        start_time=NOW + start_offset,
        end_time=NOW + start_offset + 3600,
        venue_name=None,
        address=None,
        district=district,
        latitude=None,
        longitude=None,
        url=None,
        image_url=None,
        raw={"_test": True},
    )


async def test_upsert_insert(tmp_db):
    ins, upd = await upsert_events([_ev("Festival", "ev1"), _ev("Concert", "ev2")])
    assert ins == 2
    assert upd == 0


async def test_upsert_idempotent(tmp_db):
    await upsert_events([_ev("Festival", "ev1")])
    ins, upd = await upsert_events([_ev("Festival", "ev1")])
    assert ins == 0
    assert upd == 1


async def test_upsert_mixed(tmp_db):
    await upsert_events([_ev("Festival", "ev1")])
    ins, upd = await upsert_events([_ev("Festival", "ev1"), _ev("Concert", "ev2")])
    assert ins == 1
    assert upd == 1


async def test_query_window(tmp_db):
    await upsert_events([
        _ev("A", "a", start_offset=DAY),        # demain
        _ev("B", "b", start_offset=DAY * 3),    # dans 3j
        _ev("C", "c", start_offset=-DAY),       # hier (passé)
    ])
    rows = await query_events(NOW, NOW + DAY * 7)
    titles = [r["title"] for r in rows]
    assert "A" in titles
    assert "B" in titles
    assert "C" not in titles  # passé, avant NOW


async def test_query_district_filter(tmp_db):
    await upsert_events([
        _ev("HC Event", "hc1", start_offset=DAY, district="hai chau"),
        _ev("ST Event", "st1", start_offset=DAY, district="son tra"),
    ])
    rows = await query_events(NOW, NOW + DAY * 7, district="hai chau")
    assert len(rows) == 1
    assert rows[0]["title"] == "HC Event"


async def test_query_orders_by_start_time(tmp_db):
    await upsert_events([
        _ev("Z Later",  "z", start_offset=DAY * 3),
        _ev("A Sooner", "a", start_offset=DAY),
    ])
    rows = await query_events(NOW, NOW + DAY * 7)
    assert rows[0]["title"] == "A Sooner"
    assert rows[1]["title"] == "Z Later"


async def test_prune_removes_old(tmp_db):
    await upsert_events([
        _ev("Old", "old", start_offset=-DAY * 10),  # end_time aussi passé
        _ev("New", "new", start_offset=DAY),
    ])
    cutoff = NOW - DAY * 7
    pruned = await prune_old_events(cutoff)
    assert pruned == 1
    rows = await query_events(NOW, NOW + DAY * 7)
    assert any(r["title"] == "New" for r in rows)


async def test_upsert_empty_noop(tmp_db):
    ins, upd = await upsert_events([])
    assert ins == 0
    assert upd == 0
