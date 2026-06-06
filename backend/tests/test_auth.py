"""Tests cho auth: hash mật khẩu, vòng đời token, get_current_user, cách ly session theo user."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_user
from app.db import auth as auth_db
from app.db import sessions as session_db


# ─── Mật khẩu ────────────────────────────────────────────────────────────────
def test_password_hash_roundtrip():
    h, s = auth_db.hash_password("s3cret")
    assert h != "s3cret" and s  # đã hash, có salt
    assert auth_db.verify_password("s3cret", h, s) is True
    assert auth_db.verify_password("sai", h, s) is False


def test_password_salt_is_random():
    h1, s1 = auth_db.hash_password("same")
    h2, s2 = auth_db.hash_password("same")
    assert s1 != s2 and h1 != h2  # salt/user → hash khác nhau cùng mật khẩu


# ─── Users ───────────────────────────────────────────────────────────────────
async def test_create_and_get_user(tmp_db):
    uid = await auth_db.create_user("alice", "pw")
    got = await auth_db.get_user_by_username("alice")
    assert got["id"] == uid and got["username"] == "alice"
    assert await auth_db.get_user_by_username("nobody") is None


async def test_duplicate_username_raises(tmp_db):
    await auth_db.create_user("bob", "pw")
    with pytest.raises(Exception):  # UNIQUE constraint
        await auth_db.create_user("bob", "pw2")


# ─── Tokens ──────────────────────────────────────────────────────────────────
async def test_token_issue_and_lookup(tmp_db):
    uid = await auth_db.create_user("carol", "pw")
    token = await auth_db.issue_token(uid)
    user = await auth_db.get_user_by_token(token)
    assert user == {"id": uid, "username": "carol"}


async def test_token_revoke(tmp_db):
    uid = await auth_db.create_user("dave", "pw")
    token = await auth_db.issue_token(uid)
    await auth_db.revoke_token(token)
    assert await auth_db.get_user_by_token(token) is None


async def test_token_expired(tmp_db):
    uid = await auth_db.create_user("erin", "pw")
    token = await auth_db.issue_token(uid, ttl_seconds=-10)  # đã hết hạn
    assert await auth_db.get_user_by_token(token) is None


async def test_unknown_token(tmp_db):
    assert await auth_db.get_user_by_token("khong-ton-tai") is None


# ─── get_current_user dependency ─────────────────────────────────────────────
async def test_get_current_user_missing_header(tmp_db):
    with pytest.raises(HTTPException) as ei:
        await get_current_user(authorization=None)
    assert ei.value.status_code == 401


async def test_get_current_user_bad_scheme(tmp_db):
    with pytest.raises(HTTPException) as ei:
        await get_current_user(authorization="Token abc")
    assert ei.value.status_code == 401


async def test_get_current_user_valid(tmp_db):
    uid = await auth_db.create_user("frank", "pw")
    token = await auth_db.issue_token(uid)
    user = await get_current_user(authorization=f"Bearer {token}")
    assert user["id"] == uid


# ─── Cách ly session theo user ───────────────────────────────────────────────
async def test_sessions_scoped_by_user(tmp_db):
    s_a = await session_db.create_session("A's chat", user_id="user-a")
    s_b = await session_db.create_session("B's chat", user_id="user-b")

    a_list = await session_db.list_sessions("user-a")
    assert [s.id for s in a_list] == [s_a]            # A chỉ thấy chat của A
    assert all(s.id != s_b for s in a_list)

    assert await session_db.session_owned_by(s_a, "user-a") is True
    assert await session_db.session_owned_by(s_a, "user-b") is False   # B không sở hữu chat của A
    assert await session_db.session_owned_by("khong-ton-tai", "user-a") is False
