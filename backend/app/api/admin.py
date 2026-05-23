from __future__ import annotations
from fastapi import APIRouter, HTTPException, Header
from typing import Optional

from app import config
from app.crawlers.events_crawler import run_event_crawl

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/crawl/events")
async def trigger_event_crawl(x_admin_token: Optional[str] = Header(default=None)):
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin endpoint disabled or bad token")
    result = await run_event_crawl()
    return {
        "inserted": result.inserted,
        "updated": result.updated,
        "errors": result.errors,
    }
