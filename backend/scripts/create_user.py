"""Tạo tài khoản đăng nhập cho chatbot (admin tạo sẵn — không có register công khai).

Chạy:
  python backend/scripts/create_user.py <username> <password>
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


async def _run(username: str, password: str) -> int:
    await db.init_db()
    try:
        if await auth_db.get_user_by_username(username):
            print(f"✗ Username '{username}' đã tồn tại.")
            return 1
        uid = await auth_db.create_user(username, password)
        print(f"✓ Đã tạo tài khoản '{username}' — id={uid}")
        return 0
    finally:
        await db.close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tạo tài khoản đăng nhập chatbot")
    ap.add_argument("username")
    ap.add_argument("password")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.username, args.password)))
