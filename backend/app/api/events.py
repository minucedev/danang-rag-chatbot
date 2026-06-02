from __future__ import annotations
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.rag.events_retrieval import retrieve_events

router = APIRouter()


@router.get("/api/events")
async def list_events(
    district: Optional[str] = None,
    days: int = Query(default=60, ge=1, le=365),
    limit: int = Query(default=12, ge=1, le=50),
):
    """Liệt kê sự kiện sắp tới để app đề xuất chủ động (không qua chat)."""
    now = int(time.time())
    try:
        events = await retrieve_events(
            district=district, start_ts=now, end_ts=now + days * 86400, limit=limit,
        )
    except Exception as exc:
        print(f"[events] list_events(district={district!r}, days={days}, limit={limit}) "
              f"FAILED: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="Không tải được danh sách sự kiện.") from exc
    return {"items": events, "total": len(events)}
