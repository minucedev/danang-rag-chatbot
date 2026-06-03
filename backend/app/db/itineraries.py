from __future__ import annotations
import time
from typing import List, Optional

from app.db.sessions import _db_conn
from app.rag.schemas import ItineraryEntity, ItineraryListItem


async def create_itinerary(
    client_id: str, title: str, content_md: str, session_id: Optional[str] = None
) -> ItineraryEntity:
    now = int(time.time())
    async with _db_conn().execute(
        """
        INSERT INTO itineraries (client_id, title, content_md, session_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (client_id, title, content_md, session_id, now, now),
    ) as cur:
        new_id = cur.lastrowid
    await _db_conn().commit()
    return ItineraryEntity(
        id=new_id, title=title, content_md=content_md,
        session_id=session_id, created_at=now, updated_at=now,
    )


async def list_itineraries(client_id: str) -> List[ItineraryListItem]:
    async with _db_conn().execute(
        "SELECT id, title, created_at, updated_at FROM itineraries "
        "WHERE client_id = ? ORDER BY updated_at DESC",
        (client_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [ItineraryListItem(**dict(r)) for r in rows]


async def get_itinerary(client_id: str, itinerary_id: int) -> Optional[ItineraryEntity]:
    async with _db_conn().execute(
        "SELECT id, title, content_md, session_id, created_at, updated_at "
        "FROM itineraries WHERE id = ? AND client_id = ?",
        (itinerary_id, client_id),
    ) as cur:
        row = await cur.fetchone()
    return ItineraryEntity(**dict(row)) if row else None


async def delete_itinerary(client_id: str, itinerary_id: int) -> None:
    await _db_conn().execute(
        "DELETE FROM itineraries WHERE id = ? AND client_id = ?",
        (itinerary_id, client_id),
    )
    await _db_conn().commit()
