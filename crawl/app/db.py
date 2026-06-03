"""DB layer (aiosqlite) cho tool crawl-admin — theo pattern backend/app/db."""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

import aiosqlite

from app import config

_db: Optional[aiosqlite.Connection] = None


def _now() -> int:
    return int(time.time())


async def init_db() -> None:
    global _db
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    await _db.executescript(schema)
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB chưa init — gọi init_db() trước")
    return _db


# ─── Sources ────────────────────────────────────────────────────────────────
async def add_source(url: str, category: str = "", label: str = "") -> None:
    await conn().execute(
        """INSERT INTO sources (url, category, label, active, created_at)
           VALUES (?, ?, ?, 1, ?)
           ON CONFLICT(url) DO UPDATE SET
             category = excluded.category, label = excluded.label, active = 1""",
        (url.strip(), category.strip(), label.strip(), _now()),
    )
    await conn().commit()


async def list_sources() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM sources ORDER BY created_at DESC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def list_active_sources() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM sources WHERE active = 1 ORDER BY id"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def delete_source(source_id: int) -> None:
    await conn().execute("DELETE FROM sources WHERE id = ?", (source_id,))
    await conn().commit()


# ─── Entities ────────────────────────────────────────────────────────────────
async def get_entity_by_url(url: str) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM entities WHERE url = ?", (url,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def ensure_entity(entity_id: str, url: str, source_id: Optional[int]) -> None:
    """Tạo bản ghi entity rỗng (status=pending) nếu chưa có."""
    now = _now()
    await conn().execute(
        """INSERT INTO entities (id, url, source_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(url) DO NOTHING""",
        (entity_id, url, source_id, now, now),
    )
    await conn().commit()


async def set_entity_status(url: str, status: str, error: str = "") -> None:
    await conn().execute(
        "UPDATE entities SET status = ?, error = ?, updated_at = ? WHERE url = ?",
        (status, error, _now(), url),
    )
    await conn().commit()


async def replace_entity_data(
    url: str, name: str, district: str, data_json: str, review_count: Optional[int]
) -> None:
    """GHI ĐÈ hoàn toàn thông tin entity sau khi crawl lại (crawl-update.txt #5)."""
    now = _now()
    await conn().execute(
        """UPDATE entities SET
             name = ?, district = ?, data_json = ?, review_count = ?,
             last_crawl_at = ?, status = 'done', error = '', updated_at = ?
           WHERE url = ?""",
        (name, district, data_json, review_count, now, now, url),
    )
    await conn().commit()


async def list_entities() -> list[dict]:
    async with conn().execute(
        "SELECT * FROM entities ORDER BY (last_crawl_at IS NULL) DESC, last_crawl_at ASC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ─── Crawl runs ───────────────────────────────────────────────────────────────
async def create_run(trigger: str = "manual") -> int:
    cur = await conn().execute(
        "INSERT INTO crawl_runs (trigger, started_at, status) VALUES (?, ?, 'running')",
        (trigger, _now()),
    )
    await conn().commit()
    return cur.lastrowid


async def finish_run(run_id: int, status: str, total: int, ok: int, failed: int) -> None:
    await conn().execute(
        """UPDATE crawl_runs SET finished_at = ?, status = ?, total = ?, ok = ?, failed = ?
           WHERE id = ?""",
        (_now(), status, total, ok, failed, run_id),
    )
    await conn().commit()


async def get_latest_run() -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


# ─── Logs ─────────────────────────────────────────────────────────────────────
async def add_log(run_id: Optional[int], level: str, message: str) -> None:
    await conn().execute(
        "INSERT INTO crawl_logs (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
        (run_id, _now(), level, message),
    )
    await conn().commit()
