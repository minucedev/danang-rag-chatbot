"""Test missed_queries DB module."""
from __future__ import annotations
import pytest

from app.db.sessions import create_session
from app.db.missed_queries import (
    log_missed_query,
    get_pending_queries,
    mark_resolved,
    mark_not_found,
    increment_retry,
)


async def test_log_and_retrieve_missed_query(tmp_db):
    sid = await create_session("test")
    row_id = await log_missed_query("nhà hàng ABC", "nhà hàng ABC Đà Nẵng", "restaurant_search", sid)
    assert row_id > 0
    pending = await get_pending_queries(limit=10)
    assert any(q.id == row_id for q in pending)


async def test_log_missed_query_without_session(tmp_db):
    row_id = await log_missed_query("khách sạn XYZ", None, "hotel_search", None)
    assert row_id > 0
    pending = await get_pending_queries(limit=10)
    found = next((q for q in pending if q.id == row_id), None)
    assert found is not None
    assert found.session_id is None


async def test_mark_resolved_changes_status(tmp_db):
    row_id = await log_missed_query("query", None, "place_search", None)
    await mark_resolved(row_id)
    pending = await get_pending_queries(limit=10)
    assert not any(q.id == row_id for q in pending)


async def test_mark_not_found_changes_status(tmp_db):
    row_id = await log_missed_query("query", None, "place_search", None)
    await mark_not_found(row_id)
    pending = await get_pending_queries(limit=10)
    assert not any(q.id == row_id for q in pending)


async def test_increment_retry_increments_count(tmp_db):
    row_id = await log_missed_query("query", None, "hotel_search", None)
    pending_before = await get_pending_queries(limit=10)
    found = next(q for q in pending_before if q.id == row_id)
    assert found.retry_count == 0

    await increment_retry(row_id, max_retry=3)
    pending_after = await get_pending_queries(limit=10)
    updated = next((q for q in pending_after if q.id == row_id), None)
    assert updated is not None
    assert updated.retry_count == 1


async def test_increment_retry_marks_not_found_at_max(tmp_db):
    """Sau max_retry lần → status = not_found."""
    row_id = await log_missed_query("query", None, "hotel_search", None)
    max_retry = 3
    for _ in range(max_retry):
        await increment_retry(row_id, max_retry=max_retry)
    pending = await get_pending_queries(limit=10, max_retry=max_retry)
    assert not any(q.id == row_id for q in pending)


async def test_get_pending_queries_respects_max_retry(tmp_db):
    row_id = await log_missed_query("query", None, "place_search", None)
    await increment_retry(row_id, max_retry=2)
    await increment_retry(row_id, max_retry=2)
    # retry_count = 2 → max_retry=2 → excluded (retry_count < max_retry = False)
    pending = await get_pending_queries(limit=10, max_retry=2)
    assert not any(q.id == row_id for q in pending)


async def test_missed_query_entity_fields(tmp_db):
    sid = await create_session("sess")
    row_id = await log_missed_query("hỏi về X", "X Đà Nẵng", "specific_search", sid)
    pending = await get_pending_queries(limit=10)
    q = next(q for q in pending if q.id == row_id)
    assert q.query == "hỏi về X"
    assert q.rewritten_query == "X Đà Nẵng"
    assert q.intent == "specific_search"
    assert q.status == "pending"
    assert q.retry_count == 0
