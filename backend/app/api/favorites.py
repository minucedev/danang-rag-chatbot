from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api._errors import tracked_500
from app.db import favorites as fav_db
from app.rag.schemas import FavoriteCreate, FavoriteEntity

router = APIRouter()


# Chủ sở hữu lấy TỪ token (user["id"]) — không tin client_id do client gửi. Cột client_id trong
# DB được tái dùng làm khóa chủ sở hữu (= user_id) nên không phải đổi schema favorites.
@router.post("/api/favorites", response_model=FavoriteEntity, response_model_by_alias=True)
async def add_favorite(body: FavoriteCreate, user: dict = Depends(get_current_user)):
    try:
        return await fav_db.add_favorite(
            user["id"], body.point_id, body.collection, body.snapshot
        )
    except Exception as e:
        raise tracked_500("favorites.add", e)


@router.get("/api/favorites")
async def list_favorites(user: dict = Depends(get_current_user)):
    try:
        items = await fav_db.list_favorites(user["id"])
    except Exception as e:
        raise tracked_500("favorites.list", e)
    return {"items": [i.model_dump(by_alias=True) for i in items], "total": len(items)}


@router.delete("/api/favorites/{favorite_id}")
async def delete_favorite(favorite_id: int, user: dict = Depends(get_current_user)):
    try:
        await fav_db.delete_favorite(user["id"], favorite_id)
    except Exception as e:
        raise tracked_500("favorites.delete", e)
    return {"ok": True}
