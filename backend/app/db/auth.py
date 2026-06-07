"""Auth backend cho SQLite — KHÔNG thêm thư viện (chỉ stdlib).

- Mật khẩu: pbkdf2_hmac sha256 + salt/user, so sánh hằng-thời-gian.
- Token đăng nhập: opaque (secrets), DB chỉ lưu sha256(token) → rò DB không lộ token thô.
Dùng chung connection với app.db.sessions (cùng file chats.db).
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
import uuid
from typing import Optional

from app.db.sessions import _db_conn

_PBKDF2_ITER = 200_000
_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 ngày


# ─── Mật khẩu ────────────────────────────────────────────────────────────────
def hash_password(password: str) -> tuple[str, str]:
    """Trả (hash_hex, salt_hex). Salt 16 byte ngẫu nhiên mỗi user."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return digest.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITER
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


# ─── Users ───────────────────────────────────────────────────────────────────
async def create_user(username: str, password: str, role: str = "user") -> str:
    """Tạo user, trả id. Raise nếu username đã tồn tại (UNIQUE)."""
    uid = str(uuid.uuid4())
    h, s = hash_password(password)
    await _db_conn().execute(
        "INSERT INTO users (id, username, password_hash, password_salt, role, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, username, h, s, role, int(time.time())),
    )
    await _db_conn().commit()
    return uid


async def set_user_role(username: str, role: str) -> bool:
    """Cập nhật role cho user đã tồn tại. Trả True nếu có dòng bị ĐỔI giá trị.

    Lưu ý: SQLite rowcount=0 cả khi user đã có sẵn đúng role đó (no-op) → False KHÔNG
    đồng nghĩa "user không tồn tại". Caller cần check tồn tại riêng nếu muốn phân biệt.
    """
    cur = await _db_conn().execute(
        "UPDATE users SET role = ? WHERE username = ?", (role, username)
    )
    await _db_conn().commit()
    return cur.rowcount > 0


async def get_user_by_username(username: str) -> Optional[dict]:
    async with _db_conn().execute(
        "SELECT id, username, password_hash, password_salt, role FROM users WHERE username = ?",
        (username,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


# ─── Tokens ──────────────────────────────────────────────────────────────────
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_token(user_id: str, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
    """Sinh token thô, lưu sha256(token) + hạn dùng. Trả token thô (chỉ lần này)."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    await _db_conn().execute(
        "INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (_hash_token(token), user_id, now, now + ttl_seconds),
    )
    await _db_conn().commit()
    return token


async def get_user_by_token(token: str) -> Optional[dict]:
    """Tra user qua token còn hạn. Trả {id, username, role} hoặc None."""
    async with _db_conn().execute(
        "SELECT u.id, u.username, u.role, t.expires_at "
        "FROM auth_tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.token_hash = ?",
        (_hash_token(token),),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    if row["expires_at"] is not None and row["expires_at"] < int(time.time()):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


async def revoke_token(token: str) -> None:
    await _db_conn().execute(
        "DELETE FROM auth_tokens WHERE token_hash = ?", (_hash_token(token),)
    )
    await _db_conn().commit()
