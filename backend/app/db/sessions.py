from __future__ import annotations
import time
import uuid
from pathlib import Path
from typing import Optional, List

import aiosqlite

from app import config
from app.rag.schemas import SessionEntity, MessageEntity

_db: Optional[aiosqlite.Connection] = None


async def init_db() -> None:
    global _db
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    await _db.executescript(schema)
    # Migration idempotent cho DB cũ: schema.sql dùng CREATE TABLE IF NOT EXISTS nên KHÔNG
    # thêm cột mới vào bảng đã tồn tại (sessions, users) → ALTER thủ công từng (bảng, cột),
    # bỏ qua nếu cột đã có.
    for _table, _col, _decl in (
        ("sessions", "user_id", "TEXT"),
        ("sessions", "summary", "TEXT"),
        ("users", "role", "TEXT NOT NULL DEFAULT 'user'"),
    ):
        try:
            await _db.execute(f"ALTER TABLE {_table} ADD COLUMN {_col} {_decl}")
        except aiosqlite.OperationalError as exc:
            # CHỈ nuốt trường hợp idempotent "cột đã tồn tại". Các lỗi khác cùng kiểu
            # OperationalError (no such table / database is locked / corrupt) là sự cố thật
            # → re-raise thay vì giấu để app khởi động "sạch" trên DB hỏng.
            if "duplicate column name" not in str(exc).lower():
                raise
    # Index trên sessions.user_id tạo SAU migration (lúc này cột chắc chắn tồn tại). KHÔNG để
    # trong schema.sql vì executescript chạy trước ALTER → trên DB cũ sẽ lỗi "no such column".
    await _db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)")
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _db_conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    return _db


def auto_title_from_message(content: str) -> str:
    title = content.replace("\n", " ").strip()
    return (title[:37] + "...") if len(title) > 40 else (title or "Cuộc hội thoại mới")


async def create_session(title: str, user_id: Optional[str] = None) -> str:
    sid = str(uuid.uuid4())
    now = int(time.time())
    await _db_conn().execute(
        "INSERT INTO sessions (id, title, user_id, created_at, updated_at, summary) VALUES (?, ?, ?, ?, ?, NULL)",
        (sid, title, user_id, now, now),
    )
    await _db_conn().commit()
    return sid


async def list_sessions(user_id: str, limit: int = 50, offset: int = 0) -> List[SessionEntity]:
    async with _db_conn().execute(
        "SELECT id, title, created_at, updated_at, summary FROM sessions s "
        "WHERE user_id = ? "
        "AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id) "
        "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ) as cur:
        rows = await cur.fetchall()
    return [SessionEntity(**dict(r)) for r in rows]


async def get_session(session_id: str) -> Optional[SessionEntity]:
    async with _db_conn().execute(
        "SELECT id, title, created_at, updated_at, summary FROM sessions WHERE id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return SessionEntity(**dict(row)) if row else None

async def update_session_summary(session_id: str, summary: str) -> None:
    await _db_conn().execute(
        "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
        (summary, int(time.time()), session_id),
    )
    await _db_conn().commit()


async def session_owned_by(session_id: str, user_id: str) -> bool:
    """True nếu session tồn tại VÀ thuộc user. Dùng để gác quyền ở router (404 nếu False)."""
    async with _db_conn().execute(
        "SELECT 1 FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ) as cur:
        return await cur.fetchone() is not None


async def rename_session(session_id: str, new_title: str) -> None:
    await _db_conn().execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (new_title, int(time.time()), session_id),
    )
    await _db_conn().commit()


async def delete_session(session_id: str) -> None:
    await _db_conn().execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await _db_conn().commit()


async def add_message(
    session_id: str,
    role: str,
    content: str = "",
    sources_json: Optional[str] = None,
    intent: Optional[str] = None,
) -> int:
    now = int(time.time())
    async with _db_conn().execute(
        "INSERT INTO messages (session_id, role, content, sources_json, intent, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, sources_json, intent, now),
    ) as cur:
        msg_id = cur.lastrowid
    # bump session updated_at
    await _db_conn().execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
    )
    await _db_conn().commit()
    return msg_id


async def get_messages(session_id: str) -> List[MessageEntity]:
    import json
    async with _db_conn().execute(
        "SELECT id, session_id, role, content, sources_json, intent, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC, id ASC",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        raw = d.pop("sources_json", None)
        d["sources"] = json.loads(raw) if raw else None
        result.append(MessageEntity(**d))
    return result


async def update_message_content(message_id: int, content: str) -> None:
    await _db_conn().execute(
        "UPDATE messages SET content = ? WHERE id = ?", (content, message_id)
    )
    await _db_conn().commit()


async def get_session_context(session_id: str) -> Optional[dict]:
    import json
    async with _db_conn().execute(
        "SELECT context_json FROM session_context WHERE session_id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return json.loads(row["context_json"]) if row else None


async def upsert_session_context(session_id: str, context: dict) -> None:
    import json
    now = int(time.time())
    await _db_conn().execute(
        """
        INSERT INTO session_context (session_id, context_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            context_json = excluded.context_json,
            updated_at   = excluded.updated_at
        """,
        (session_id, json.dumps(context, ensure_ascii=False), now),
    )
    await _db_conn().commit()
