"""Tạo / cấp quyền tài khoản đăng nhập cho chatbot.

Chạy:
  python backend/scripts/create_user.py <username> <password>              # tạo user thường
  python backend/scripts/create_user.py <username> <password> --role admin # tạo admin
Nếu username đã tồn tại: chỉ cập nhật role theo --role (kiêm "nâng quyền").
Ghi vào cùng SQLite mà server dùng (config.DB_PATH = backend/data/chats.db).
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
from pathlib import Path

# UTF-8 console (Windows cp1252 → tránh UnicodeEncodeError khi in tiếng Việt)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# app.config validate QDRANT_URL lúc import — CLI không gọi Qdrant nên đặt dummy.
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "cli-dummy")

# Cho `import app.*` chạy được khi gọi script trực tiếp từ gốc repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # = backend/

from app.db import sessions as db   # noqa: E402
from app.db import auth as auth_db  # noqa: E402


async def _run(username: str, password: str, role: str) -> int:
    await db.init_db()
    try:
        if await auth_db.get_user_by_username(username):
            # Đã có → chỉ cập nhật role (nâng/hạ quyền). LƯU Ý: KHÔNG đổi mật khẩu.
            await auth_db.set_user_role(username, role)
            print(f"✓ Tài khoản '{username}' đã tồn tại — đã đặt role='{role}'. "
                  f"(Mật khẩu KHÔNG thay đổi.)")
            return 0
        uid = await auth_db.create_user(username, password, role=role)
        print(f"✓ Đã tạo tài khoản '{username}' (role={role}) — id={uid}")
        return 0
    finally:
        await db.close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tạo / cấp quyền tài khoản đăng nhập chatbot")
    ap.add_argument("username")
    ap.add_argument("password")
    ap.add_argument("--role", choices=["user", "admin"], default="user")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.username, args.password, args.role)))
