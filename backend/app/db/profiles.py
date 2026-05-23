from __future__ import annotations
import json
import time
from typing import Optional

from app.db.sessions import _db_conn
from app.rag.schemas import UserProfile


async def get_profile(session_id: str) -> Optional[UserProfile]:
    async with _db_conn().execute(
        "SELECT profile_json FROM profiles WHERE session_id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return UserProfile.model_validate_json(row["profile_json"])


async def upsert_profile(session_id: str, profile: UserProfile) -> UserProfile:
    now = int(time.time())
    payload = profile.model_dump_json()
    await _db_conn().execute(
        """
        INSERT INTO profiles (session_id, profile_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            profile_json = excluded.profile_json,
            updated_at   = excluded.updated_at
        """,
        (session_id, payload, now),
    )
    await _db_conn().commit()
    return profile


async def delete_profile(session_id: str) -> None:
    await _db_conn().execute(
        "DELETE FROM profiles WHERE session_id = ?", (session_id,)
    )
    await _db_conn().commit()
