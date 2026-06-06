"""Router metrics-admin — dashboard đánh giá RAG tại /admin/metrics.

Chạy bộ benchmark (pbl7-metrics) trên pipeline THẬT của app, hiển thị report card +
biểu đồ, xuất CSV. Dùng chung process/pipeline/Gemini với chatbot. Mirror pattern
crawl_admin: router + Jinja2 + SSE; static mount ở main.py.
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import config as backend_config
from app.crawl_admin import config as crawl_config
from app.metrics import runner, store
from app.metrics.progress import progress_bus

router = APIRouter(prefix="/admin/metrics", tags=["metrics-admin"])

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "metrics" / "templates")
)


def _require_write_auth(x_admin_token: str | None = Header(default=None)) -> None:
    """Dùng lại cờ CRAWL_ADMIN_REQUIRE_TOKEN: khi bật, route ghi (chạy eval) cần x-admin-token."""
    if not crawl_config.REQUIRE_TOKEN:
        return
    if not backend_config.ADMIN_TOKEN or x_admin_token != backend_config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Metrics admin write disabled or bad token")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _TEMPLATES.TemplateResponse(request, "index.html", {})


@router.get("/api/state")
async def api_state():
    latest = runner.get_latest()
    summary = None
    if latest:
        summary = {
            "id": latest["id"],
            "suite": latest["suite"],
            "n_pass": latest["n_pass"],
            "n_total": latest["n_total"],
        }
    return {"state": runner.get_state(), "latest": summary}


@router.post("/api/run")
async def api_run(payload: dict = Body(default={}), _: None = Depends(_require_write_auth)):
    if runner.is_running():
        return JSONResponse({"error": "Đang có một lượt eval chạy."}, status_code=409)
    suite = payload.get("suite", "both")
    if suite not in ("general", "itinerary", "both"):
        return JSONResponse({"error": "suite không hợp lệ"}, status_code=400)
    enable_judge = bool(payload.get("enable_judge", True))
    asyncio.create_task(runner.run_eval(suite=suite, enable_judge=enable_judge))
    return {"started": True}


@router.get("/api/runs")
async def api_runs():
    return store.list_runs()


@router.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str):
    data = store.get_run(run_id)
    if data is None:
        return JSONResponse({"error": "không tìm thấy run"}, status_code=404)
    return data


@router.get("/api/runs/{run_id}/{name}.csv")
async def api_run_csv(run_id: str, name: str):
    path = store.get_csv_path(run_id, name)
    if path is None:
        return JSONResponse({"error": "không tìm thấy CSV"}, status_code=404)
    return FileResponse(path, media_type="text/csv", filename=f"{run_id}_{name}.csv")


@router.get("/api/logs/stream")
async def api_logs_stream():
    async def _gen():
        q = progress_bus.subscribe()
        try:
            yield "data: (đã kết nối log tiến độ)\n\n"
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            progress_bus.unsubscribe(q)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
