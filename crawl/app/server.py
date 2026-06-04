"""FastAPI server cho crawl-admin đa-engine (standalone, port 8100).

Chạy:  cd crawl && uvicorn app.server:app --port 8100 --reload
"""
from __future__ import annotations
import sys

# stdout/stderr → UTF-8: tránh UnicodeEncodeError khi print() tiếng Việt trên console Windows (cp1252)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import config, db, orchestrator
from app.engines import ENGINES
from app.logbus import log_bus

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


async def _scheduled_run() -> None:
    if orchestrator.is_running():
        return
    try:
        await orchestrator.run_engines(list(ENGINES.keys()), trigger="scheduled", force=False)
    except Exception as exc:
        print(f"[crawl-admin] scheduled run failed: {type(exc).__name__}: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    scheduler = None
    if config.SCHEDULE_ENABLED:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_scheduled_run, "interval", hours=config.SCHEDULE_HOURS,
                          id="auto_crawl", max_instances=1, coalesce=True)
        scheduler.start()
        print(f"[crawl-admin] scheduler ON — mỗi {config.SCHEDULE_HOURS}h")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await db.close_db()


app = FastAPI(title="Crawl Admin", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _TEMPLATES.TemplateResponse(request, "index.html", {})


@app.get("/api/state")
async def api_state():
    return {"state": orchestrator.get_state(), "latest_run": await db.get_latest_run()}


@app.get("/api/jobs")
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


@app.post("/api/jobs/{key}/run")
async def api_job_run(key: str):
    if key not in ENGINES:
        return JSONResponse({"error": "engine không tồn tại"}, status_code=404)
    if orchestrator.is_running():
        return JSONResponse({"error": "Đang có một lượt crawl chạy."}, status_code=409)
    asyncio.create_task(_bg([key], force=True))
    return {"started": True}


@app.post("/api/jobs/run-all")
async def api_run_all():
    if orchestrator.is_running():
        return JSONResponse({"error": "Đang có một lượt crawl chạy."}, status_code=409)
    asyncio.create_task(_bg(list(ENGINES.keys()), force=False))
    return {"started": True}


async def _bg(keys: list[str], force: bool) -> None:
    try:
        await orchestrator.run_engines(keys, trigger="manual", force=force)
    except Exception as exc:
        print(f"[crawl-admin] run failed: {type(exc).__name__}: {exc}")


@app.get("/api/runs")
async def api_runs():
    return await db.list_runs(limit=20)


@app.get("/api/entities")
async def api_entities():
    return await db.list_entities()


# ─── Sources (URL Foody thêm tay, tùy chọn) ──────────────────────────────────
@app.get("/api/sources")
async def api_sources():
    return await db.list_sources()


@app.post("/api/sources")
async def api_add_source(url: str = Form(...), category: str = Form(""), label: str = Form("")):
    url = url.strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "URL không hợp lệ"}, status_code=400)
    await db.add_source(url, category, label)
    return {"ok": True}


@app.post("/api/sources/{source_id}/delete")
async def api_delete_source(source_id: int):
    await db.delete_source(source_id)
    return {"ok": True}


# ─── Log realtime (SSE) ──────────────────────────────────────────────────────
@app.get("/api/crawl/logs/stream")
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
