"""Entrypoint NHẸ chỉ phục vụ dashboard admin (crawl + metrics) để test giao diện mà KHÔNG
nạp model chatbot (BGE-M3/LLM/Qdrant).

Chạy:  cd backend && python -m uvicorn app.admin_app:app --port 8000 --reload
Mở:    http://localhost:8000/admin/crawl/   và   http://localhost:8000/admin/metrics/

Tái dùng nguyên router/static/template/DB của app chính — KHÔNG đụng app.main.
Lưu ý: bấm "Chạy eval" (metrics) cần pipeline thật (không có ở đây); job ingest (crawl) sẽ tự
nạp BGE-M3 lần đầu. Xem/duyệt dashboard và crawl Foody thì entrypoint này là đủ.
"""
from __future__ import annotations
import sys

# stdout/stderr → UTF-8 (Windows cp1252) để log tiếng Việt không crash. Giống app/main.py.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.crawl_admin import db as crawl_db
from app.api import crawl_admin as crawl_admin_api
from app.api import metrics_admin
from app.api import admin_shell


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chỉ init crawl.db (sqlite). KHÔNG nạp model, KHÔNG Qdrant client.
    await crawl_db.init_db()
    print("Admin-only ready — http://localhost:8000/admin/crawl/  |  /admin/metrics/")
    yield
    await crawl_db.close_db()


app = FastAPI(title="PPBL Admin (chỉ dashboard)", lifespan=lifespan)
app.include_router(admin_shell.router)
app.include_router(crawl_admin_api.router)
app.include_router(metrics_admin.router)

_BASE = Path(__file__).resolve().parent
app.mount(
    "/admin/crawl/static",
    StaticFiles(directory=str(_BASE / "crawl_admin" / "static")),
    name="crawl_admin_static",
)
app.mount(
    "/admin/metrics/static",
    StaticFiles(directory=str(_BASE / "metrics" / "static")),
    name="metrics_admin_static",
)
