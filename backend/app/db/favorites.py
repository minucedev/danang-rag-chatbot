from __future__ import annotations
import json
import time
from typing import List

from app.db.sessions import _db_conn
from app.rag.schemas import FavoriteEntity


async def add_favorite(
    client_id: str, point_id: str, collection: str, snapshot: dict
) -> FavoriteEntity:
    """Lưu (hoặc cập nhật snapshot) 1 địa điểm yêu thích. Idempotent theo
    (client_id, collection, point_id)."""
    now = int(time.time())
    snap = json.dumps(snapshot, ensure_ascii=False)
    await _db_conn().execute(
        """
        INSERT INTO favorites (client_id, point_id, collection, snapshot_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id, collection, point_id) DO UPDATE SET
            snapshot_json = excluded.snapshot_json
        """,
        (client_id, point_id, collection, snap, now),
    )
    await _db_conn().commit()
    async with _db_conn().execute(
        "SELECT id, point_id, collection, snapshot_json, created_at "
        "FROM favorites WHERE client_id = ? AND collection = ? AND point_id = ?",
        (client_id, collection, point_id),
    ) as cur:
        row = await cur.fetchone()
    return _to_entity(row)


async def list_favorites(client_id: str) -> List[FavoriteEntity]:
    async with _db_conn().execute(
        "SELECT id, point_id, collection, snapshot_json, created_at "
        "FROM favorites WHERE client_id = ? ORDER BY created_at DESC",
        (client_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [_to_entity(r) for r in rows]


async def delete_favorite(client_id: str, favorite_id: int) -> None:
    # Scoped theo client_id để không xoá được favorite của client khác.
    await _db_conn().execute(
        "DELETE FROM favorites WHERE id = ? AND client_id = ?",
        (favorite_id, client_id),
    )
    await _db_conn().commit()


def _to_entity(row) -> FavoriteEntity:
    return FavoriteEntity(
        id=row["id"],
        point_id=row["point_id"],
        collection=row["collection"],
        snapshot=json.loads(row["snapshot_json"]),
        created_at=row["created_at"],
    )
