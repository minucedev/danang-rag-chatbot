"""Router crawl-admin — gắn vào app chính tại /admin/crawl (thay crawl/app/server.py cũ).

Phục vụ dashboard Jinja + các API điều khiển crawl/ingest. Dùng chung process, embedder,
Qdrant với chatbot. Static (style.css) được mount ở main.py.
"""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import config as backend_config
from app.crawl_admin import config, db, orchestrator
from app.crawl_admin.engines import ENGINES, CRAWL_KEYS
from app.crawl_admin.logbus import log_bus

router = APIRouter(prefix="/admin/crawl", tags=["crawl-admin"])

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "crawl_admin" / "templates")
)


def _require_write_auth(x_admin_token: str | None = Header(default=None)) -> None:
    """Dashboard nằm trên cổng public 8000. Khi CRAWL_ADMIN_REQUIRE_TOKEN bật, các route
    GHI (kích hoạt crawl, thêm/xóa nguồn) phải kèm header x-admin-token khớp ADMIN_TOKEN."""
    if not config.REQUIRE_TOKEN:
        return
    if not backend_config.ADMIN_TOKEN or x_admin_token != backend_config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Crawl admin write disabled or bad token")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _TEMPLATES.TemplateResponse(request, "index.html", {})


@router.get("/api/state")
async def api_state():
    return {"state": orchestrator.get_state(), "latest_run": await db.get_latest_run()}


@router.get("/api/jobs")
async def api_jobs():
    state = orchestrator.get_state()
    eng_state = await db.list_engine_state()
    out = []
    for key, meta in ENGINES.items():
        st = eng_state.get(key, {})
        out.append({
            "key": key,
            "label": meta["label"],
            "last_run_at": st.get("last_run_at"),
            "last_status": st.get("last_status", ""),
            "running": state.get("running") and state.get("engine") == key,
        })
    return out


@router.post("/api/jobs/{key}/run")
async def api_job_run(key: str, _: None = Depends(_require_write_auth)):
    if key not in ENGINES:
        return JSONResponse({"error": "engine không tồn tại"}, status_code=404)
    if orchestrator.is_running():
        return JSONResponse({"error": "Đang có một lượt crawl chạy."}, status_code=409)
    asyncio.create_task(_bg([key], force=True))
    return {"started": True}


@router.post("/api/jobs/run-all")
async def api_run_all(_: None = Depends(_require_write_auth)):
    if orchestrator.is_running():
        return JSONResponse({"error": "Đang có một lượt crawl chạy."}, status_code=409)
    asyncio.create_task(_bg(CRAWL_KEYS, force=False))
    return {"started": True}


async def _bg(keys: list[str], force: bool) -> None:
    try:
        await orchestrator.run_engines(keys, trigger="manual", force=force)
    except Exception as exc:
        print(f"[crawl-admin] run failed: {type(exc).__name__}: {exc}")


@router.get("/api/runs")
async def api_runs():
    return await db.list_runs(limit=20)


@router.get("/api/entities")
async def api_entities():
    return await db.list_entities()


@router.get("/api/hotels")
async def api_hotels():
    import pandas as pd
    out = []
    # 1. Thử đọc Traveloka hotels
    traveloka_path = Path(config.DATA_TRAVELOKA) / "hotels.csv"
    if traveloka_path.exists():
        try:
            df = pd.read_csv(traveloka_path, encoding="utf-8-sig")
            for _, r in df.iterrows():
                out.append({
                    "name": str(r.get("name", "")).strip(),
                    "platform": "Traveloka",
                    "rating": str(r.get("rating", "")).strip(),
                    "review_count": str(r.get("review_count", "")).strip(),
                    "address": str(r.get("full_address", "") or r.get("address", "")).strip()
                })
        except Exception as exc:
            logging.warning("api_hotels: đọc %s lỗi: %s", traveloka_path, type(exc).__name__)
    # 2. Thử đọc Booking hotels
    booking_path = Path(config.DATA_BOOKING) / "hotels.csv"
    if booking_path.exists():
        try:
            df = pd.read_csv(booking_path, encoding="utf-8-sig")
            for _, r in df.iterrows():
                out.append({
                    "name": str(r.get("name", "")).strip(),
                    "platform": "Booking",
                    "rating": str(r.get("rating", "")).strip(),
                    "review_count": str(r.get("review_count", "")).strip(),
                    "address": str(r.get("full_address", "") or r.get("address", "")).strip()
                })
        except Exception as exc:
            logging.warning("api_hotels: đọc %s lỗi: %s", booking_path, type(exc).__name__)

    return out


# ─── Sources (URL Foody thêm tay, tùy chọn) ──────────────────────────────────
@router.get("/api/sources")
async def api_sources():
    return await db.list_sources()


@router.post("/api/sources")
async def api_add_source(
    url: str = Form(...), category: str = Form(""), label: str = Form(""),
    _: None = Depends(_require_write_auth),
):
    url = url.strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "URL không hợp lệ"}, status_code=400)
    await db.add_source(url, category, label)
    return {"ok": True}


@router.post("/api/sources/{source_id}/delete")
async def api_delete_source(source_id: int, _: None = Depends(_require_write_auth)):
    await db.delete_source(source_id)
    return {"ok": True}


# ─── Log realtime (SSE) ──────────────────────────────────────────────────────
@router.get("/api/logs/stream")
async def api_logs_stream():
    async def _gen():
        q = log_bus.subscribe()
        try:
            yield "data: (đã kết nối log realtime)\n\n"
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            log_bus.unsubscribe(q)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
