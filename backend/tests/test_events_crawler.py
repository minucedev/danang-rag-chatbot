"""Tests cho orchestrator: dedup cross-source, district infer, error isolation."""
from __future__ import annotations
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.crawlers.events_crawler import run_event_crawl, _infer_district
from app.db.events import query_events, EventDict

NOW = int(time.time())
DAY = 86400


def _serpapi_ev(title: str, sid: str, address: str = "123 Hải Châu, Đà Nẵng") -> EventDict:
    return EventDict(
        source="serpapi", source_event_id=sid, title=title,
        start_time=NOW + DAY, end_time=NOW + DAY + 3600,
        address=address, district=None,
        description=None, venue_name=None,
        latitude=None, longitude=None,
        url=None, image_url=None, raw={},
    )


async def test_district_inferred_from_address(tmp_db):
    ev = _serpapi_ev("Lễ hội", "ev1", address="56 Nguyễn Văn Linh, Hải Châu, Đà Nẵng")
    with patch("app.crawlers.serpapi_adapter.fetch_events", new=AsyncMock(return_value=[ev])):
        result = await run_event_crawl()

    rows = await query_events(NOW, NOW + DAY * 7, district="hai chau")
    assert len(rows) == 1
    assert rows[0]["title"] == "Lễ hội"
    assert result.inserted == 1
    assert result.errors == []


async def test_adapter_error_is_isolated(tmp_db):
    """Nếu serpapi crash, crawler ghi lỗi nhưng không raise."""
    with patch("app.crawlers.serpapi_adapter.fetch_events", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await run_event_crawl()

    assert len(result.errors) == 1
    assert "serpapi" in result.errors[0]
    assert result.inserted == 0


async def test_dedup_across_runs(tmp_db):
    ev = _serpapi_ev("Concert", "dup1")
    mock = AsyncMock(return_value=[ev])
    with patch("app.crawlers.serpapi_adapter.fetch_events", new=mock):
        r1 = await run_event_crawl()
        r2 = await run_event_crawl()

    assert r1.inserted == 1
    assert r2.inserted == 0
    assert r2.updated == 1


def test_infer_district():
    assert _infer_district("123 Hải Châu, Đà Nẵng") == "hai chau"
    assert _infer_district("456 Sơn Trà, Đà Nẵng") == "son tra"
    assert _infer_district("unknown street") is None
    assert _infer_district(None) is None
