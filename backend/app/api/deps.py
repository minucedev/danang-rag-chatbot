"""Dependencies dùng chung cho auth. get_current_user lấy user từ header Bearer."""
from __future__ import annotations
from typing import Optional

from fastapi import Header, HTTPException

from app.db import auth as auth_db


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Trả {id, username} nếu token hợp lệ; ngược lại 401. Gắn vào route cần đăng nhập."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Thiếu token đăng nhập")
    user = await auth_db.get_user_by_token(authorization[len("Bearer "):])
    if not user:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn")
    return user
