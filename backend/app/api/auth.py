"""Router xác thực: đăng nhập, đăng ký (chỉ role 'user'), đăng xuất, thông tin user.

Tài khoản admin KHÔNG tạo qua register — chỉ qua scripts/create_user.py --role admin.
Cơ chế: token opaque trong SQLite + Authorization: Bearer. Xem app/db/auth.py.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_user
from app.db import auth as auth_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _strip_username(v):
    """Bỏ khoảng trắng đầu/cuối để '  alice ' và 'alice' là cùng một tài khoản
    (kể cả khi gọi API trực tiếp, không qua FE đã .trim()). Giá trị không phải chuỗi
    để nguyên cho pydantic báo lỗi type."""
    return v.strip() if isinstance(v, str) else v


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)

    # mode="before": chạy trước khi ràng buộc min_length của field được áp, nên min_length
    # kiểm tra trên giá trị ĐÃ strip → username toàn khoảng trắng (sau strip rỗng) bị loại.
    _strip = field_validator("username", mode="before")(_strip_username)


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=256)

    # min_length=3 áp lên username đã strip (xem LoginBody._strip).
    _strip = field_validator("username", mode="before")(_strip_username)


class UserOut(BaseModel):
    id: str
    username: str
    role: str


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
    return LoginOut(
        token=token,
        user=UserOut(id=user["id"], username=user["username"], role=user["role"]),
    )


@router.post("/register", response_model=LoginOut, status_code=201)
async def register(body: RegisterBody):
    """Khách tự đăng ký tài khoản role 'user' rồi tự đăng nhập (trả token luôn).

    KHÔNG cho phép tự chọn role — admin chỉ tạo qua scripts/create_user.py.
    """
    if await auth_db.get_user_by_username(body.username):
        raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
    uid = await auth_db.create_user(body.username, body.password, role="user")
    token = await auth_db.issue_token(uid)
    return LoginOut(
        token=token, user=UserOut(id=uid, username=body.username, role="user")
    )


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
    return UserOut(id=user["id"], username=user["username"], role=user["role"])
