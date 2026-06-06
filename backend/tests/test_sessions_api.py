"""owned_session_or_404 là chốt phân quyền dùng chung cho sessions/profile router — đảo boolean
là lộ chat/profile của user khác mà không test nào fail. Test trực tiếp cả 2 nhánh (như test_favorites_api)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import owned_session_or_404
from app.db import sessions as session_db


async def test_raises_404_for_non_owner(tmp_db):
    sid = await session_db.create_session("A", user_id="user-a")
    with pytest.raises(HTTPException) as ei:
        await owned_session_or_404(sid, {"id": "user-b"})   # không phải chủ
    assert ei.value.status_code == 404


async def test_raises_404_for_missing_session(tmp_db):
    with pytest.raises(HTTPException) as ei:
        await owned_session_or_404("khong-ton-tai", {"id": "user-a"})
    assert ei.value.status_code == 404


async def test_passes_for_owner(tmp_db):
    sid = await session_db.create_session("A", user_id="user-a")
    await owned_session_or_404(sid, {"id": "user-a"})        # không raise = đạt
