"""Dependencies dùng chung cho auth. get_current_user lấy user từ header Bearer."""
from __future__ import annotations
from typing import Optional

from fastapi import Header, HTTPException

from app.db import auth as auth_db
from app.db import sessions as session_db


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Trả {id, username, role} nếu token hợp lệ; ngược lại 401. Gắn vào route cần đăng nhập."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Thiếu token đăng nhập")
    user = await auth_db.get_user_by_token(authorization[len("Bearer "):])
    if not user:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn")
    return user


async def owned_session_or_404(session_id: str, user: dict) -> None:
    """404 nếu session không tồn tại HOẶC không thuộc user. Gác quyền chung cho các router."""
    if not await session_db.session_owned_by(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found")
