from __future__ import annotations
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.db import itineraries as itin_db
from app.rag.schemas import ItineraryCreate, ItineraryEntity

router = APIRouter()


@router.post("/api/itineraries", response_model=ItineraryEntity, response_model_by_alias=True)
async def create_itinerary(body: ItineraryCreate):
    try:
        return await itin_db.create_itinerary(
            body.client_id, body.title, body.content_md, body.session_id
        )
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[itineraries] create error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"create itinerary failed (id={err_id})")


@router.get("/api/itineraries")
async def list_itineraries(client_id: str = Query(..., alias="clientId")):
    try:
        items = await itin_db.list_itineraries(client_id)
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
async def get_itinerary(itinerary_id: int, client_id: str = Query(..., alias="clientId")):
    item = await itin_db.get_itinerary(client_id, itinerary_id)
    if not item:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    return item


@router.delete("/api/itineraries/{itinerary_id}")
async def delete_itinerary(itinerary_id: int, client_id: str = Query(..., alias="clientId")):
    try:
        await itin_db.delete_itinerary(client_id, itinerary_id)
    except Exception as e:
        err_id = uuid.uuid4().hex[:8]
        print(f"[itineraries] delete error_id={err_id} {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"delete itinerary failed (id={err_id})")
    return {"ok": True}
