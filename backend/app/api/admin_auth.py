"""Cổng đăng nhập cho dashboard /admin (tách khỏi đăng nhập chat).

Vì /admin là HTML do backend phục vụ, mở bằng điều hướng trình duyệt (không gửi được header
Bearer), nên gác bằng **cookie HttpOnly** thay vì Bearer:
- GET/POST /admin/login: form đăng nhập; chỉ chấp nhận user role 'admin' → đặt cookie.
- GET /admin/logout: thu hồi token + xóa cookie.
- admin_guard (middleware): chặn mọi path /admin* (trừ login/logout/static) nếu chưa có cookie admin hợp lệ.

Dùng lại token opaque của app.db.auth (lưu sha256(token)); cookie chỉ chứa token thô.

Bảo mật: xác thực thật nằm ở server (get_user_by_token + check role). Cookie HttpOnly +
SameSite=Lax là toàn bộ lớp chống CSRF (không có anti-CSRF token) → TUYỆT ĐỐI không thêm
endpoint /admin GET làm thay đổi trạng thái ngoài /admin/logout. Dev dùng http nên chưa đặt
Secure; production (HTTPS) nên bật Secure.
"""
from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.db import auth as auth_db

logger = logging.getLogger("app.api.admin_auth")
router = APIRouter()

COOKIE_NAME = "admin_session"
COOKIE_PATH = "/admin"
_TTL_SECONDS = 8 * 3600  # phiên admin ngắn hơn token chat (8 giờ)


def _safe_next(next_url: str | None) -> str:
    """Chỉ cho redirect nội bộ vào khu /admin (chống open-redirect + chặn ký tự lạ).

    Yêu cầu prefix '/admin', không phải '//evil' (protocol-relative), và không chứa ký tự
    có thể phá HTML/redirect ('"<> hoặc khoảng trắng). Giá trị vẫn được escape lúc render.
    """
    if (
        next_url
        and next_url.startswith("/admin")
        and not next_url.startswith("//")
        and not any(c in next_url for c in '"\'<> \t\r\n')
    ):
        return next_url
    return "/admin"


async def _authed_admin(request: Request) -> dict | None:
    """Trả user admin nếu cookie hợp lệ, ngược lại None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user = await auth_db.get_user_by_token(token)
    if not user or user.get("role") != "admin":
        return None
    return user


def _login_page(next_url: str, error: str = "") -> HTMLResponse:
    err_html = f'<p class="err">{error}</p>' if error else ""
    status = 401 if error else 200
    html = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Đăng nhập quản trị</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family: Inter, system-ui, Arial, sans-serif; background:#f4f5f7; color:#1e2330; }}
  .card {{ background:#fff; border:1px solid #e4e7ec; border-radius:12px; padding:28px 26px;
    width:100%; max-width:360px; box-shadow:0 1px 3px rgba(16,24,40,.06); }}
  h1 {{ font-size:18px; margin:0 0 4px; }}
  p.sub {{ margin:0 0 18px; font-size:13px; color:#6b7280; }}
  label {{ display:block; font-size:13px; font-weight:600; margin:12px 0 4px; }}
  input {{ width:100%; padding:9px 11px; border:1px solid #e4e7ec; border-radius:8px;
    font-size:14px; font-family:inherit; }}
  input:focus {{ outline:none; border-color:#6c5ce7; box-shadow:0 0 0 2px rgba(108,92,231,.15); }}
  button {{ margin-top:18px; width:100%; padding:10px; border:0; border-radius:8px; cursor:pointer;
    background:#6c5ce7; color:#fff; font-weight:600; font-size:14px; }}
  button:hover {{ background:#5b4bd6; }}
  .err {{ color:#e0454e; font-size:13px; margin:10px 0 0; }}
</style></head>
<body>
  <form class="card" method="post" action="/admin/login">
    <h1>🛠️ Quản trị — Đà Nẵng RAG</h1>
    <p class="sub">Đăng nhập bằng tài khoản quản trị viên.</p>
    <input type="hidden" name="next" value="{escape(next_url, quote=True)}" />
    <label for="u">Tài khoản</label>
    <input id="u" name="username" autocomplete="username" autofocus required />
    <label for="p">Mật khẩu</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required />
    {err_html}
    <button type="submit">Đăng nhập</button>
  </form>
</body></html>"""
    return HTMLResponse(html, status_code=status)


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request) -> HTMLResponse:
    # Đã đăng nhập admin rồi → vào thẳng dashboard.
    if await _authed_admin(request):
        return RedirectResponse(_safe_next(request.query_params.get("next")), status_code=303)
    return _login_page(_safe_next(request.query_params.get("next")))


@router.post("/admin/login")
async def admin_login_submit(
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin"),
):
    target = _safe_next(next)
    user = await auth_db.get_user_by_username(username)
    if (
        not user
        or not auth_db.verify_password(password, user["password_hash"], user["password_salt"])
        or user["role"] != "admin"
    ):
        # Thông điệp chung (không phân biệt sai mật khẩu / không phải admin).
        return _login_page(target, error="Sai tài khoản, mật khẩu hoặc không có quyền quản trị")
    token = await auth_db.issue_token(user["id"], ttl_seconds=_TTL_SECONDS)
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        COOKIE_NAME, token, max_age=_TTL_SECONDS, httponly=True,
        samesite="lax", path=COOKIE_PATH,
    )
    return resp


@router.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    # Xóa cookie LUÔN (kể cả khi revoke lỗi) để client không kẹt phiên; revoke best-effort.
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    if token:
        try:
            await auth_db.revoke_token(token)
        except Exception:
            logger.error("admin_logout: revoke_token thất bại", exc_info=True)
    return resp


def _is_allowlisted(path: str) -> bool:
    """Path không cần cookie admin: trang login/logout và mọi file tĩnh.

    `'/static/' in path` là khớp chuỗi con — bất kỳ path chứa '/static/' (CSS/JS/ảnh) đều mở.
    Hiện chỉ có 2 mount /admin/crawl/static & /admin/metrics/static; nếu thêm route khác chứa
    '/static/' cần rà lại để tránh hở cổng.
    """
    return (
        path in ("/admin/login", "/admin/logout")
        or "/static/" in path
    )


async def admin_guard(request: Request, call_next):
    """Middleware: chặn /admin* nếu chưa đăng nhập admin. Đăng ký bằng app.middleware('http')."""
    path = request.url.path
    if path.startswith("/admin") and not _is_allowlisted(path):
        try:
            authed = await _authed_admin(request)
        except Exception:
            # Lỗi hạ tầng (DB lock/chưa init…) → FAIL-CLOSED: coi như chưa đăng nhập,
            # KHÔNG để lọt request, và log để không hỏng âm thầm.
            logger.error("admin_guard: lỗi kiểm tra cookie admin (fail-closed)", exc_info=True)
            authed = None
        if not authed:
            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                nxt = quote(request.url.path, safe="/")
                return RedirectResponse(f"/admin/login?next={nxt}", status_code=303)
            return JSONResponse({"detail": "Yêu cầu đăng nhập quản trị"}, status_code=401)
    return await call_next(request)
