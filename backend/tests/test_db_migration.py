"""Test init_db() heal được DB schema CŨ (thiếu user_id/summary/role, thiếu qa_cache).

Tái hiện lỗi thật: executescript(schema) từng abort tại CREATE INDEX idx_sessions_user vì cột
user_id chưa tồn tại trên DB cũ → migration không chạy, qa_cache không được tạo, app không boot.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _make_old_db(path: str) -> None:
    """Dựng DB theo schema CŨ: sessions không user_id/summary, users không role, không qa_cache."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        """
    )
    con.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s1', 'cũ', 1, 1)"
    )
    con.commit()
    con.close()


async def test_init_db_heals_old_schema(tmp_path, monkeypatch):
    from app import config
    from app.db import sessions as db

    db_file = tmp_path / "old.db"
    _make_old_db(str(db_file))
    monkeypatch.setattr(config, "DB_PATH", str(db_file))

    await db.init_db()  # KHÔNG được raise (trước fix sẽ raise OperationalError: no such column)
    try:
        conn = db._db_conn()

        async def _cols(table):
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                return [r["name"] for r in await cur.fetchall()]

        sess_cols = await _cols("sessions")
        assert "user_id" in sess_cols and "summary" in sess_cols   # đã vá cột
        assert "role" in await _cols("users")                       # users.role được thêm

        async def _exists(kind, name):
            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (kind, name)
            ) as cur:
                return await cur.fetchone() is not None

        assert await _exists("table", "qa_cache")                   # bảng mới được tạo
        assert await _exists("index", "idx_sessions_user")          # index tạo sau migration

        # Dữ liệu cũ không mất.
        async with conn.execute("SELECT title FROM sessions WHERE id='s1'") as cur:
            row = await cur.fetchone()
        assert row is not None and row["title"] == "cũ"
    finally:
        await db.close_db()


async def test_init_db_idempotent_on_fresh_db(tmp_path, monkeypatch):
    """Chạy init_db 2 lần trên DB mới — không lỗi (CREATE ... IF NOT EXISTS + ALTER nuốt duplicate)."""
    from app import config
    from app.db import sessions as db

    db_file = tmp_path / "fresh.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))

    await db.init_db()
    await db.close_db()
    await db.init_db()  # lần 2 phải im lặng
    try:
        conn = db._db_conn()
        async with conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_sessions_user'"
        ) as cur:
            assert await cur.fetchone() is not None
    finally:
        await db.close_db()
