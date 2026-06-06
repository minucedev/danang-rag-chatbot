from __future__ import annotations
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
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
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] add error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"add favorite failed (id={err_id})")


@router.get("/api/favorites")
async def list_favorites(user: dict = Depends(get_current_user)):
    try:
        items = await fav_db.list_favorites(user["id"])
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] list error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"list favorites failed (id={err_id})")
    return {"items": [i.model_dump(by_alias=True) for i in items], "total": len(items)}


@router.delete("/api/favorites/{favorite_id}")
async def delete_favorite(favorite_id: int, user: dict = Depends(get_current_user)):
    try:
        await fav_db.delete_favorite(user["id"], favorite_id)
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] delete error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"delete favorite failed (id={err_id})")
    return {"ok": True}
