"""Tests cho auth: hash mật khẩu, vòng đời token, get_current_user, cách ly session theo user."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.api import auth as auth_api
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
    assert user == {"id": uid, "username": "carol", "role": "user"}


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


# ─── Role & đăng ký ──────────────────────────────────────────────────────────
async def test_create_user_with_role(tmp_db):
    await auth_db.create_user("root", "pw", role="admin")
    got = await auth_db.get_user_by_username("root")
    assert got["role"] == "admin"


async def test_default_role_is_user(tmp_db):
    await auth_db.create_user("guest1", "pw")
    assert (await auth_db.get_user_by_username("guest1"))["role"] == "user"


async def test_set_user_role_promotes(tmp_db):
    await auth_db.create_user("promote_me", "pw")
    assert await auth_db.set_user_role("promote_me", "admin") is True
    assert (await auth_db.get_user_by_username("promote_me"))["role"] == "admin"
    assert await auth_db.set_user_role("nobody", "admin") is False


async def test_register_creates_user_role_and_token(tmp_db):
    out = await auth_api.register(auth_api.RegisterBody(username="newbie", password="secret6"))
    assert out.user.role == "user" and out.user.username == "newbie"
    # token trả về dùng được ngay
    who = await auth_db.get_user_by_token(out.token)
    assert who["id"] == out.user.id


async def test_register_duplicate_conflict(tmp_db):
    await auth_db.create_user("taken", "pw")
    with pytest.raises(HTTPException) as ei:
        await auth_api.register(auth_api.RegisterBody(username="taken", password="secret6"))
    assert ei.value.status_code == 409


async def test_login_returns_role(tmp_db):
    await auth_db.create_user("withrole", "pw", role="admin")
    out = await auth_api.login(auth_api.LoginBody(username="withrole", password="pw"))
    assert out.user.role == "admin"


# ─── Chuẩn hoá username (trim khoảng trắng) ──────────────────────────────────
async def test_register_strips_username(tmp_db):
    out = await auth_api.register(auth_api.RegisterBody(username="  spacey  ", password="secret6"))
    assert out.user.username == "spacey"  # đã trim trước khi lưu
    assert await auth_db.get_user_by_username("spacey") is not None


async def test_login_strips_username(tmp_db):
    await auth_db.create_user("trimmed", "pw")
    # Đăng nhập với khoảng trắng thừa vẫn khớp đúng tài khoản.
    out = await auth_api.login(auth_api.LoginBody(username="  trimmed  ", password="pw"))
    assert out.user.username == "trimmed"


def test_register_whitespace_only_username_rejected():
    # Toàn khoảng trắng → sau strip rỗng → < 3 ký tự → ValidationError.
    with pytest.raises(ValidationError):
        auth_api.RegisterBody(username="    ", password="secret6")


def test_register_short_after_strip_rejected():
    with pytest.raises(ValidationError):
        auth_api.RegisterBody(username="  ab  ", password="secret6")  # 'ab' < 3


async def test_register_duplicate_after_strip_conflict(tmp_db):
    # Lý do tồn tại của validator: '  alice  ' và 'alice' là CÙNG tài khoản → phải 409.
    await auth_db.create_user("alice", "pw")
    with pytest.raises(HTTPException) as ei:
        await auth_api.register(auth_api.RegisterBody(username="  alice  ", password="secret6"))
    assert ei.value.status_code == 409


def test_login_whitespace_only_username_rejected():
    # LoginBody min_length=1: sau strip rỗng → ValidationError (nhánh khác register min_length=3).
    with pytest.raises(ValidationError):
        auth_api.LoginBody(username="   ", password="pw")


def test_password_is_not_stripped():
    # Khoảng trắng trong mật khẩu là có nghĩa — validator CHỈ áp cho username, không cho password.
    assert auth_api.LoginBody(username="u", password="  pw  ").password == "  pw  "
    assert auth_api.RegisterBody(username="user", password="  secret6  ").password == "  secret6  "


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
