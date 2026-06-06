"""Router đăng nhập. Tài khoản admin tạo sẵn (xem scripts/create_user.py) — không có register.

Cơ chế: token opaque trong SQLite + Authorization: Bearer. Xem app/db/auth.py.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.db import auth as auth_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    username: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


@router.post("/login", response_model=LoginOut)
async def login(body: LoginBody):
    user = await auth_db.get_user_by_username(body.username)
    # Thông điệp chung (không phân biệt sai user / sai mật khẩu) để không lộ username tồn tại.
    if not user or not auth_db.verify_password(
        body.password, user["password_hash"], user["password_salt"]
    ):
        raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu")
    token = await auth_db.issue_token(user["id"])
    return LoginOut(token=token, user=UserOut(id=user["id"], username=user["username"]))


@router.post("/logout")
async def logout(
    _user: dict = Depends(get_current_user),
    authorization: Optional[str] = Header(default=None),
):
    # get_current_user đã đảm bảo token hợp lệ → header chắc chắn có dạng "Bearer <token>".
    await auth_db.revoke_token(authorization[len("Bearer "):])
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return UserOut(id=user["id"], username=user["username"])
