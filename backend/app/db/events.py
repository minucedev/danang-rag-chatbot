from __future__ import annotations
import json
import time
from typing import Optional, TypedDict

from app.db.sessions import _db_conn


class EventDict(TypedDict, total=False):
    source: str
    source_event_id: str
    title: str
    description: Optional[str]
    start_time: Optional[int]
    end_time: Optional[int]
    venue_name: Optional[str]
    address: Optional[str]
    district: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    url: Optional[str]
    image_url: Optional[str]
    raw: Optional[dict]


async def upsert_events(events: list[EventDict]) -> tuple[int, int]:
    """Upsert by (source, source_event_id). Returns (inserted, updated).

    SQLite không trả về trực tiếp "đã insert hay update", nên dùng changes() trước/sau
    với mỗi câu kèm RETURNING là quá phức tạp — thay vào đó đếm bằng SELECT trước.
    """
    if not events:
        return (0, 0)

    now = int(time.time())
    conn = _db_conn()

    keys = [(e["source"], e["source_event_id"]) for e in events]
    placeholders = ",".join("(?,?)" for _ in keys)
    flat = [v for pair in keys for v in pair]
    async with conn.execute(
        f"SELECT source, source_event_id FROM events WHERE (source, source_event_id) IN (VALUES {placeholders})",
        flat,
    ) as cur:
        existing = {(r["source"], r["source_event_id"]) for r in await cur.fetchall()}

    inserted = 0
    updated = 0
    try:
        for e in events:
            key = (e["source"], e["source_event_id"])
            is_new = key not in existing
            raw_json = json.dumps(e.get("raw"), ensure_ascii=False) if e.get("raw") else None
            await conn.execute(
                """
                INSERT INTO events (
                    source, source_event_id, title, description, start_time, end_time,
                    venue_name, address, district, latitude, longitude, url, image_url,
                    raw_json, created_at, updated_at, last_seen_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, source_event_id) DO UPDATE SET
                    title        = excluded.title,
                    description  = excluded.description,
                    start_time   = excluded.start_time,
                    end_time     = excluded.end_time,
                    venue_name   = excluded.venue_name,
                    address      = excluded.address,
                    district     = excluded.district,
                    latitude     = excluded.latitude,
                    longitude    = excluded.longitude,
                    url          = excluded.url,
                    image_url    = excluded.image_url,
                    raw_json     = excluded.raw_json,
                    updated_at   = excluded.updated_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    e["source"], e["source_event_id"], e["title"],
                    e.get("description"), e.get("start_time"), e.get("end_time"),
                    e.get("venue_name"), e.get("address"), e.get("district"),
                    e.get("latitude"), e.get("longitude"),
                    e.get("url"), e.get("image_url"),
                    raw_json, now, now, now,
                ),
            )
            if is_new:
                inserted += 1
            else:
                updated += 1
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    return (inserted, updated)


async def query_events(
    start_ts: int,
    end_ts: int,
    district: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Trả sự kiện trong [start_ts, end_ts]. Sự kiện không có start_time bị bỏ qua
    (không định vị được thời gian → không gợi ý được)."""
    sql = (
        "SELECT id, source, source_event_id, title, description, start_time, end_time, "
        "venue_name, address, district, latitude, longitude, url, image_url "
        "FROM events WHERE start_time IS NOT NULL AND start_time >= ? AND start_time <= ?"
    )
    params: list = [start_ts, end_ts]
    if district:
        sql += " AND district = ?"
        params.append(district)
    sql += " ORDER BY start_time ASC LIMIT ?"
    params.append(limit)

    async with _db_conn().execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def prune_old_events(before_ts: int) -> int:
    """Xoá sự kiện có end_time hoặc start_time đã qua before_ts. Trả số dòng đã xoá."""
    conn = _db_conn()
    async with conn.execute(
        "DELETE FROM events WHERE COALESCE(end_time, start_time) IS NOT NULL "
        "AND COALESCE(end_time, start_time) < ?",
        (before_ts,),
    ) as cur:
        deleted = cur.rowcount
    await conn.commit()
    return max(deleted, 0)
