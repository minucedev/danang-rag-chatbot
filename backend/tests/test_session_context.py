"""Test session context DB functions và memory helpers."""
from __future__ import annotations
import pytest

from app.db.sessions import get_session_context, upsert_session_context, create_session
from app.rag.memory import extract_session_prefs, merge_session_prefs
from app.rag.intent import QueryIntent


async def test_get_session_context_returns_none_when_empty(tmp_db):
    sid = await create_session("test")
    ctx = await get_session_context(sid)
    assert ctx is None


async def test_upsert_and_get_session_context(tmp_db):
    sid = await create_session("test")
    await upsert_session_context(sid, {"district": "son tra", "max_price": 500000})
    ctx = await get_session_context(sid)
    assert ctx is not None
    assert ctx["district"] == "son tra"
    assert ctx["max_price"] == 500000


async def test_upsert_session_context_overwrites_on_conflict(tmp_db):
    sid = await create_session("test")
    await upsert_session_context(sid, {"district": "hai chau"})
    await upsert_session_context(sid, {"district": "son tra", "max_price": 300000})
    ctx = await get_session_context(sid)
    assert ctx["district"] == "son tra"
    assert ctx["max_price"] == 300000


# ── extract_session_prefs ──────────────────────────────────────────────────

def test_extract_session_prefs_returns_non_null_filters():
    analysis = {
        "intent": QueryIntent.HOTEL_SEARCH,
        "rewritten_query": "khách sạn Sơn Trà",
        "filters": {"district": "son tra", "max_price": 500000, "min_rating": None, "min_price": None},
        "source": "LLM",
    }
    prefs = extract_session_prefs(analysis)
    assert prefs == {"district": "son tra", "max_price": 500000}
    assert "min_rating" not in prefs
    assert "min_price" not in prefs


def test_extract_session_prefs_returns_empty_when_all_null():
    analysis = {
        "intent": QueryIntent.GENERAL,
        "rewritten_query": "địa điểm du lịch",
        "filters": {"district": None, "max_price": None, "min_rating": None, "min_price": None},
        "source": "LLM",
    }
    prefs = extract_session_prefs(analysis)
    assert prefs == {}


def test_extract_session_prefs_handles_missing_filters_key():
    analysis = {"intent": QueryIntent.CHITCHAT, "rewritten_query": "", "source": "LLM"}
    prefs = extract_session_prefs(analysis)
    assert prefs == {}


# ── merge_session_prefs ────────────────────────────────────────────────────

def test_merge_session_prefs_fills_none_fields():
    ctx = {"district": "son tra", "max_price": 300000}
    filters = {"district": None, "max_price": None, "min_rating": None, "min_price": None}
    merged = merge_session_prefs(ctx, filters)
    assert merged["district"] == "son tra"
    assert merged["max_price"] == 300000


def test_merge_session_prefs_does_not_override_explicit_filter():
    ctx = {"district": "son tra"}
    filters = {"district": "hai chau", "max_price": None, "min_rating": None, "min_price": None}
    merged = merge_session_prefs(ctx, filters)
    # current_filters thắng
    assert merged["district"] == "hai chau"


def test_merge_session_prefs_no_context_returns_original():
    filters = {"district": "son tra", "max_price": 500000, "min_rating": None, "min_price": None}
    merged = merge_session_prefs(None, filters)
    assert merged == filters


def test_merge_session_prefs_empty_context():
    filters = {"district": None}
    merged = merge_session_prefs({}, filters)
    assert merged["district"] is None
