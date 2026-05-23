"""Tests cho events_retrieval: query theo window/district, format context."""
from __future__ import annotations
import time

import pytest

from app.db.events import upsert_events, EventDict
from app.rag.events_retrieval import retrieve_events, format_events_context

NOW = int(time.time())
DAY = 86400


async def _seed(events):
    await upsert_events(events)


def _ev(title, sid, offset=DAY, district=None, url=None):
    return EventDict(
        source="test", source_event_id=sid, title=title,
        start_time=NOW + offset, end_time=NOW + offset + 3600,
        district=district, address=None, description=f"Desc {title}",
        venue_name=f"Venue {title}", latitude=None, longitude=None,
        url=url, image_url=None, raw={},
    )


async def test_retrieve_returns_upcoming(tmp_db):
    await _seed([_ev("Festival", "f1"), _ev("Concert", "c1", offset=DAY * 3)])
    events = await retrieve_events()
    assert len(events) == 2
    titles = [e["title"] for e in events]
    assert "Festival" in titles
    assert "Concert" in titles


async def test_retrieve_district_filter(tmp_db):
    await _seed([
        _ev("HC Show", "hc1", district="hai chau"),
        _ev("ST Show", "st1", district="son tra"),
    ])
    events = await retrieve_events(district="hai chau")
    assert len(events) == 1
    assert events[0]["title"] == "HC Show"


async def test_retrieve_no_past_events(tmp_db):
    await _seed([_ev("Old", "old", offset=-DAY * 2)])
    events = await retrieve_events()
    assert events == []


async def test_to_source_dict_has_expected_fields(tmp_db):
    await _seed([_ev("A", "a1", url="https://example.com")])
    events = await retrieve_events()
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "event"
    assert ev["title"] == "A"
    assert "time_display" in ev
    assert ev["url"] == "https://example.com"


async def test_format_context_empty():
    ctx = format_events_context([])
    assert "Không tìm thấy" in ctx


async def test_format_context_includes_title_and_time(tmp_db):
    await _seed([_ev("Big Show", "bs1", district="hai chau")])
    events = await retrieve_events()
    ctx = format_events_context(events)
    assert "Big Show" in ctx
    assert "Venue Big Show" in ctx
