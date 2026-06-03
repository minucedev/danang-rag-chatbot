"""FastAPI server cho tool crawl-admin (standalone, port 8100).

Chạy: uvicorn crawl.app.server:app --port 8100 --reload  (từ thư mục gốc repo)
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import config, db, pipeline

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="Crawl Admin", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"freshness_default": config.FRESHNESS_HOURS},
    )


# ─── State ────────────────────────────────────────────────────────────────────
@app.get("/api/state")
async def api_state():
    return {"state": pipeline.get_state(), "latest_run": await db.get_latest_run()}


# ─── Sources ───────────────────────────────────────────────────────────────
@app.get("/api/sources")
async def api_sources():
    return await db.list_sources()


@app.post("/api/sources")
async def api_add_source(
    url: str = Form(...),
    category: str = Form(""),
    label: str = Form(""),
):
    url = url.strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "URL không hợp lệ"}, status_code=400)
    await db.add_source(url, category, label)
    return {"ok": True}


@app.post("/api/sources/{source_id}/delete")
async def api_delete_source(source_id: int):
    await db.delete_source(source_id)
    return {"ok": True}


# ─── Entities ──────────────────────────────────────────────────────────────
@app.get("/api/entities")
async def api_entities():
    return await db.list_entities()


# ─── Crawl run ─────────────────────────────────────────────────────────────
async def _bg_run(freshness_hours: Optional[int]) -> None:
    try:
        await pipeline.run_crawl("manual", freshness_hours)
    except Exception as exc:  # đã log trong pipeline; nuốt ở background task
        print(f"[crawl-admin] run failed: {type(exc).__name__}: {exc}")


@app.post("/api/crawl/run")
async def api_crawl_run(freshness_hours: str = Form("")):
    if pipeline.is_running():
        return JSONResponse({"error": "Đang có một lượt crawl chạy."}, status_code=409)
    fh: Optional[int] = int(freshness_hours) if freshness_hours.strip().isdigit() else None
    asyncio.create_task(_bg_run(fh))
    return {"started": True}


@app.get("/api/crawl/logs/stream")
async def api_logs_stream():
    async def _gen():
        q = pipeline.log_bus.subscribe()
        try:
            yield "data: (đã kết nối log realtime)\n\n"
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # heartbeat giữ kết nối
        finally:
            pipeline.log_bus.unsubscribe(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
