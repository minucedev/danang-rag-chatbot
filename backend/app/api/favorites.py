from __future__ import annotations
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.db import favorites as fav_db
from app.rag.schemas import FavoriteCreate, FavoriteEntity

router = APIRouter()


@router.post("/api/favorites", response_model=FavoriteEntity, response_model_by_alias=True)
async def add_favorite(body: FavoriteCreate):
    try:
        return await fav_db.add_favorite(
            body.client_id, body.point_id, body.collection, body.snapshot
        )
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] add error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"add favorite failed (id={err_id})")


@router.get("/api/favorites")
async def list_favorites(client_id: str = Query(..., alias="clientId")):
    try:
        items = await fav_db.list_favorites(client_id)
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] list error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"list favorites failed (id={err_id})")
    return {"items": [i.model_dump(by_alias=True) for i in items], "total": len(items)}


@router.delete("/api/favorites/{favorite_id}")
async def delete_favorite(favorite_id: int, client_id: str = Query(..., alias="clientId")):
    try:
        await fav_db.delete_favorite(client_id, favorite_id)
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[favorites] delete error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"delete favorite failed (id={err_id})")
    return {"ok": True}
