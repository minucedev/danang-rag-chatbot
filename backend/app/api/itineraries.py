from __future__ import annotations
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db import itineraries as itin_db
from app.rag.schemas import ItineraryCreate, ItineraryEntity

router = APIRouter()


# Chủ sở hữu lấy TỪ token (user["id"]); cột client_id trong DB tái dùng làm khóa chủ sở hữu.
@router.post("/api/itineraries", response_model=ItineraryEntity, response_model_by_alias=True)
async def create_itinerary(body: ItineraryCreate, user: dict = Depends(get_current_user)):
    try:
        return await itin_db.create_itinerary(
            user["id"], body.title, body.content_md, body.session_id
        )
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[itineraries] create error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"create itinerary failed (id={err_id})")


@router.get("/api/itineraries")
async def list_itineraries(user: dict = Depends(get_current_user)):
    try:
        items = await itin_db.list_itineraries(user["id"])
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[itineraries] list error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"list itineraries failed (id={err_id})")
    return {"items": [i.model_dump(by_alias=True) for i in items], "total": len(items)}


@router.get(
    "/api/itineraries/{itinerary_id}",
    response_model=ItineraryEntity,
    response_model_by_alias=True,
)
async def get_itinerary(itinerary_id: int, user: dict = Depends(get_current_user)):
    item = await itin_db.get_itinerary(user["id"], itinerary_id)
    if not item:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    return item


@router.delete("/api/itineraries/{itinerary_id}")
async def delete_itinerary(itinerary_id: int, user: dict = Depends(get_current_user)):
    try:
        await itin_db.delete_itinerary(user["id"], itinerary_id)
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[itineraries] delete error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"delete itinerary failed (id={err_id})")
    return {"ok": True}
