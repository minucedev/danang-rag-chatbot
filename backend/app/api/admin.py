from __future__ import annotations
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional

from app import config
from app.crawlers.events_crawler import run_event_crawl
from app.crawlers.places_crawler import run_place_crawl, run_new_places_crawl

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_token(x_admin_token: Optional[str]) -> None:
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin endpoint disabled or bad token")


@router.post("/crawl/events")
async def trigger_event_crawl(x_admin_token: Optional[str] = Header(default=None)):
    _check_token(x_admin_token)
    result = await run_event_crawl()
    return {
        "inserted": result.inserted,
        "updated": result.updated,
        "errors": result.errors,
    }


class CrawlPlacesBody(BaseModel):
    missed_only: bool = False
    limit: int = Field(default=20, ge=1, le=500)


@router.post("/crawl/places")
async def trigger_place_crawl(
    body: CrawlPlacesBody = CrawlPlacesBody(),
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_token(x_admin_token)
    from app.crawlers.places_crawler import PlaceCrawlResult
    if body.missed_only:
        from app.db.missed_queries import get_pending_queries
        pending = await get_pending_queries(limit=body.limit, max_retry=config.MAX_PLACE_RETRY)
        missed_ids = [q.id for q in pending]
        result = await run_place_crawl(missed_ids=missed_ids)
    else:
        result = PlaceCrawlResult()
        for fn, label in [(run_place_crawl, "missed"), (run_new_places_crawl, "new_places")]:
            try:
                r = await fn()
                result.inserted += r.inserted
                result.updated += r.updated
                result.resolved_misses += r.resolved_misses
                result.errors.extend(r.errors)
            except Exception as exc:
                result.errors.append(f"{label}: {type(exc).__name__}: {exc}")
    return {
        "inserted": result.inserted,
        "updated": result.updated,
        "resolved_misses": result.resolved_misses,
        "errors": result.errors,
    }
