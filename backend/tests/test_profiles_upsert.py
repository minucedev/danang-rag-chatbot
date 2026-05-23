"""Pin behavior cho `profiles.upsert_profile` ON CONFLICT clause + round-trip."""
from __future__ import annotations
import asyncio
from datetime import date

import pytest

from app.db import profiles as profile_db
from app.db import sessions as session_db
from app.rag.schemas import TripDates, UserProfile


async def _new_session() -> str:
    return await session_db.create_session("test")


async def test_insert_then_get(tmp_db):
    sid = await _new_session()
    p = UserProfile(interests=["beach", "food"], budget_level="low")
    await profile_db.upsert_profile(sid, p)

    got = await profile_db.get_profile(sid)
    assert got is not None
    assert got.interests == ["beach", "food"]
    assert got.budget_level == "low"


async def test_upsert_overwrites_same_session(tmp_db):
    sid = await _new_session()
    await profile_db.upsert_profile(sid, UserProfile(interests=["beach"]))
    await profile_db.upsert_profile(
        sid,
        UserProfile(interests=["food", "cafe"], budget_level="high"),
    )

    got = await profile_db.get_profile(sid)
    assert got.interests == ["food", "cafe"]
    assert got.budget_level == "high"
    # KHÔNG merge → "beach" không còn
    assert "beach" not in got.interests


async def test_upsert_bumps_updated_at(tmp_db):
    sid = await _new_session()
    await profile_db.upsert_profile(sid, UserProfile(interests=["beach"]))

    async with session_db._db_conn().execute(
        "SELECT updated_at FROM profiles WHERE session_id = ?", (sid,)
    ) as cur:
        row1 = await cur.fetchone()
    t1 = row1["updated_at"]

    await asyncio.sleep(1.1)  # đảm bảo unix-timestamp chênh ≥ 1s
    await profile_db.upsert_profile(sid, UserProfile(interests=["food"]))

    async with session_db._db_conn().execute(
        "SELECT updated_at FROM profiles WHERE session_id = ?", (sid,)
    ) as cur:
        row2 = await cur.fetchone()
    assert row2["updated_at"] > t1


async def test_get_missing_returns_none(tmp_db):
    assert await profile_db.get_profile("does-not-exist") is None


async def test_round_trip_preserves_trip_dates_and_interests(tmp_db):
    sid = await _new_session()
    p = UserProfile(
        display_name="Olivia",
        trip_dates=TripDates(start=date(2026, 6, 1), end=date(2026, 6, 5)),
        interests=["beach", "culture"],
        budget_level="mid",
    )
    await profile_db.upsert_profile(sid, p)

    got = await profile_db.get_profile(sid)
    assert got == p
    assert got.trip_dates.length_days == 5  # property hoạt động sau round-trip


async def test_delete_is_idempotent(tmp_db):
    # Không crash khi delete profile không tồn tại
    await profile_db.delete_profile("never-existed")
    await profile_db.delete_profile("never-existed")
