"""DB layer (aiosqlite) cho tool crawl-admin — theo pattern backend/app/db."""
from __future__ import annotations
import asyncio
import time
from pathlib import Path
from typing import Optional

import aiosqlite

from app import config

_db: Optional[aiosqlite.Connection] = None
# Serialize execute+commit: engine foody ghi đồng thời (asyncio.gather nhiều worker) trên
# CÙNG 1 connection → khóa để mỗi cặp ghi+commit là nguyên tử, tránh interleave/rowcount sai.
_wlock = asyncio.Lock()


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


async def upsert_discovered(
    entity_id: str, url: str, name: str, district: str, review_count: Optional[int]
) -> bool:
    """Thêm entity phát hiện từ discovery (kèm info cơ bản từ API) nếu CHƯA có.
    KHÔNG ghi đè entity đã crawl. Trả True nếu là entity mới."""
    now = _now()
    cur = await conn().execute(
        """INSERT INTO entities (id, url, name, district, review_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO NOTHING""",
        (entity_id, url, name, district, review_count, now, now),
    )
    await conn().commit()
    return cur.rowcount > 0


async def set_entity_status(url: str, status: str, error: str = "") -> None:
    async with _wlock:
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
    async with _wlock:
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
async def create_run(engine: str = "", trigger: str = "manual") -> int:
    cur = await conn().execute(
        "INSERT INTO crawl_runs (engine, trigger, started_at, status) VALUES (?, ?, ?, 'running')",
        (engine, trigger, _now()),
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


async def list_runs(limit: int = 20) -> list[dict]:
    async with conn().execute(
        "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ─── Engine state (freshness theo engine) ─────────────────────────────────────
async def get_engine_state(engine: str) -> Optional[dict]:
    async with conn().execute(
        "SELECT * FROM engine_state WHERE engine = ?", (engine,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_engine_state() -> dict[str, dict]:
    async with conn().execute("SELECT * FROM engine_state") as cur:
        return {r["engine"]: dict(r) for r in await cur.fetchall()}


async def set_engine_state(engine: str, last_run_at: int, last_status: str) -> None:
    await conn().execute(
        """INSERT INTO engine_state (engine, last_run_at, last_status)
           VALUES (?, ?, ?)
           ON CONFLICT(engine) DO UPDATE SET
             last_run_at = excluded.last_run_at, last_status = excluded.last_status""",
        (engine, last_run_at, last_status),
    )
    await conn().commit()


# ─── Logs ─────────────────────────────────────────────────────────────────────
async def add_log(run_id: Optional[int], level: str, message: str) -> None:
    async with _wlock:
        await conn().execute(
            "INSERT INTO crawl_logs (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
            (run_id, _now(), level, message),
        )
        await conn().commit()
