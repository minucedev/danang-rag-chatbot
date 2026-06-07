"""Tests cho cổng cookie /admin (app/api/admin_auth.py) — mức hàm, không cần TestClient."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.api import admin_auth
from app.db import auth as auth_db


def _req(path: str = "/admin/crawl/", accept: str = "text/html", cookie: str | None = None) -> Request:
    headers = [(b"accept", accept.encode())]
    if cookie is not None:
        headers.append((b"cookie", cookie.encode()))
    scope = {
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": headers,
    }
    return Request(scope)


async def _passthru(request):
    return "PASSED"


async def _admin_cookie(tmp_db_helper_username="adm") -> str:
    uid = await auth_db.create_user(tmp_db_helper_username, "pw", role="admin")
    token = await auth_db.issue_token(uid)
    return f"{admin_auth.COOKIE_NAME}={token}"


# ─── _authed_admin ───────────────────────────────────────────────────────────
async def test_authed_admin_none_without_cookie(tmp_db):
    assert await admin_auth._authed_admin(_req()) is None


async def test_authed_admin_ok_for_admin_cookie(tmp_db):
    cookie = await _admin_cookie("boss")
    user = await admin_auth._authed_admin(_req(cookie=cookie))
    assert user and user["role"] == "admin"


async def test_authed_admin_rejects_user_role(tmp_db):
    uid = await auth_db.create_user("plain", "pw")  # role=user
    token = await auth_db.issue_token(uid)
    user = await admin_auth._authed_admin(_req(cookie=f"{admin_auth.COOKIE_NAME}={token}"))
    assert user is None


# ─── admin_guard middleware ──────────────────────────────────────────────────
async def test_guard_redirects_html_without_cookie(tmp_db):
    resp = await admin_auth.admin_guard(_req(path="/admin/crawl/"), _passthru)
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/login")


async def test_guard_json_401_without_cookie(tmp_db):
    resp = await admin_auth.admin_guard(
        _req(path="/admin/crawl/api/jobs", accept="application/json"), _passthru
    )
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 401


async def test_guard_allows_login_path(tmp_db):
    assert await admin_auth.admin_guard(_req(path="/admin/login"), _passthru) == "PASSED"


async def test_guard_allows_static(tmp_db):
    out = await admin_auth.admin_guard(_req(path="/admin/crawl/static/style.css"), _passthru)
    assert out == "PASSED"


async def test_guard_allows_non_admin_path(tmp_db):
    assert await admin_auth.admin_guard(_req(path="/chat"), _passthru) == "PASSED"


async def test_guard_passes_with_admin_cookie(tmp_db):
    cookie = await _admin_cookie("boss2")
    out = await admin_auth.admin_guard(_req(path="/admin/crawl/", cookie=cookie), _passthru)
    assert out == "PASSED"


async def test_guard_blocks_user_cookie(tmp_db):
    uid = await auth_db.create_user("plain2", "pw")
    token = await auth_db.issue_token(uid)
    resp = await admin_auth.admin_guard(
        _req(path="/admin/crawl/", cookie=f"{admin_auth.COOKIE_NAME}={token}"), _passthru
    )
    assert isinstance(resp, RedirectResponse)  # bị chặn


async def test_guard_fails_closed_when_lookup_raises(tmp_db, monkeypatch):
    async def boom(_):
        raise RuntimeError("db down")
    monkeypatch.setattr(admin_auth.auth_db, "get_user_by_token", boom)
    resp = await admin_auth.admin_guard(
        _req(path="/admin/crawl/", cookie=f"{admin_auth.COOKIE_NAME}=x"), _passthru
    )
    assert resp != "PASSED"  # lỗi DB → KHÔNG lọt (fail-closed)
    assert isinstance(resp, RedirectResponse)


async def test_guard_blocks_expired_cookie(tmp_db):
    uid = await auth_db.create_user("oldadmin", "pw", role="admin")
    token = await auth_db.issue_token(uid, ttl_seconds=-10)  # đã hết hạn
    resp = await admin_auth.admin_guard(
        _req(path="/admin/crawl/", cookie=f"{admin_auth.COOKIE_NAME}={token}"), _passthru
    )
    assert resp != "PASSED"


# ─── _safe_next (chống open-redirect / ký tự lạ) ─────────────────────────────
def test_safe_next_rules():
    assert admin_auth._safe_next("/admin/crawl/") == "/admin/crawl/"
    assert admin_auth._safe_next(None) == "/admin"
    assert admin_auth._safe_next("//evil.com") == "/admin"
    assert admin_auth._safe_next("https://evil.com") == "/admin"
    assert admin_auth._safe_next("/chat") == "/admin"
    # ký tự phá HTML/redirect bị loại
    assert admin_auth._safe_next('/admin"><script>') == "/admin"


# ─── POST /admin/login ───────────────────────────────────────────────────────
async def test_login_submit_admin_sets_cookie(tmp_db):
    await auth_db.create_user("boss", "pw", role="admin")
    resp = await admin_auth.admin_login_submit(username="boss", password="pw", next="/admin")
    assert isinstance(resp, RedirectResponse) and resp.status_code == 303
    sc = resp.headers["set-cookie"].lower()
    assert admin_auth.COOKIE_NAME in sc and "httponly" in sc and "path=/admin" in sc


async def test_login_submit_wrong_password_no_cookie(tmp_db):
    await auth_db.create_user("boss2", "pw", role="admin")
    resp = await admin_auth.admin_login_submit(username="boss2", password="WRONG", next="/admin")
    assert resp.status_code == 401 and "set-cookie" not in resp.headers


async def test_login_submit_non_admin_no_cookie(tmp_db):
    await auth_db.create_user("plainx", "pw")  # role=user
    resp = await admin_auth.admin_login_submit(username="plainx", password="pw", next="/admin")
    assert resp.status_code == 401 and "set-cookie" not in resp.headers


# ─── logout: thu hồi token + xóa cookie + gate chặn cookie cũ ─────────────────
async def test_logout_revokes_and_blocks(tmp_db):
    cookie = await _admin_cookie("boss3")
    token = cookie.split("=", 1)[1]
    resp = await admin_auth.admin_logout(_req(cookie=cookie))
    assert resp.status_code == 303 and "set-cookie" in resp.headers
    assert await auth_db.get_user_by_token(token) is None  # đã thu hồi
    blocked = await admin_auth.admin_guard(_req(path="/admin/crawl/", cookie=cookie), _passthru)
    assert blocked != "PASSED"  # cookie cũ không còn vào được
