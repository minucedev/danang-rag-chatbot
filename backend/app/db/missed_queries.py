from __future__ import annotations
import time
from typing import Literal, Optional
from dataclasses import dataclass

from app.db.sessions import _db_conn

MissedQueryStatus = Literal["pending", "resolved", "not_found"]


@dataclass
class MissedQueryEntity:
    id: int
    query: str
    rewritten_query: Optional[str]
    intent: Optional[str]
    session_id: Optional[str]
    retry_count: int
    status: MissedQueryStatus
    created_at: int
    last_tried_at: Optional[int]


async def log_missed_query(
    query: str,
    rewritten_query: Optional[str],
    intent: Optional[str],
    session_id: Optional[str],
) -> int:
    now = int(time.time())
    async with _db_conn().execute(
        """
        INSERT INTO missed_queries (query, rewritten_query, intent, session_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (query, rewritten_query, intent, session_id, now),
    ) as cur:
        row_id = cur.lastrowid
    await _db_conn().commit()
    return row_id


async def get_pending_queries(limit: int = 20, max_retry: int = 3) -> list[MissedQueryEntity]:
    async with _db_conn().execute(
        """
        SELECT id, query, rewritten_query, intent, session_id,
               retry_count, status, created_at, last_tried_at
        FROM missed_queries
        WHERE status = 'pending' AND retry_count < ?
        ORDER BY retry_count ASC, created_at ASC
        LIMIT ?
        """,
        (max_retry, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [MissedQueryEntity(**dict(r)) for r in rows]


async def mark_resolved(missed_id: int) -> None:
    await _db_conn().execute(
        "UPDATE missed_queries SET status = 'resolved', last_tried_at = ? WHERE id = ?",
        (int(time.time()), missed_id),
    )
    await _db_conn().commit()


async def mark_not_found(missed_id: int) -> None:
    await _db_conn().execute(
        "UPDATE missed_queries SET status = 'not_found', last_tried_at = ? WHERE id = ?",
        (int(time.time()), missed_id),
    )
    await _db_conn().commit()


async def increment_retry(missed_id: int, max_retry: int = 3) -> None:
    now = int(time.time())
    await _db_conn().execute(
        """
        UPDATE missed_queries
        SET retry_count = retry_count + 1,
            last_tried_at = ?,
            status = CASE WHEN retry_count + 1 >= ? THEN 'not_found' ELSE status END
        WHERE id = ?
        """,
        (now, max_retry, missed_id),
    )
    await _db_conn().commit()
