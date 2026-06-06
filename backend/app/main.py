from __future__ import annotations

# stdout/stderr về UTF-8: trên Windows mặc định cp1252 → print() chứa tiếng Việt
# crash UnicodeEncodeError (vd làm crawler 500). errors="replace" để không bao giờ raise.
import sys
for _s in (sys.stdout, sys.stderr):
    # reconfigure chỉ có trên TextIOWrapper thật; khi stdout bị wrap (pytest capture,
    # một số ASGI launcher) sẽ raise AttributeError/ValueError — bỏ qua nhưng để lại dấu vết.
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError) as _exc:
        print(f"[startup] stdout reconfigure skipped: {type(_exc).__name__}: {_exc}")

# HF cache phải set TRƯỚC khi import transformers/torch để load offline từ cache local
# (tránh treo do gọi mạng tới HuggingFace). setdefault để vẫn override được qua env.
import os
from pathlib import Path
os.environ.setdefault(
    "HF_HUB_CACHE",
    str(Path(__file__).resolve().parent.parent / "models" / ".cache" / "huggingface"),
)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from contextlib import asynccontextmanager
from datetime import datetime

import torch
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer, CrossEncoder

from app import config
from app.db import sessions as db
from app.rag.llm import load_llm, load_analyzer_llm
from app.rag.pipeline import RAGPipeline
import app.rag.pipeline as pl_module
from app.crawlers.events_crawler import run_event_crawl
from app.crawlers.places_crawler import run_place_crawl, run_new_places_crawl
from app.crawl_admin import (
    config as crawl_cfg, db as crawl_db,
    orchestrator as crawl_orch, ingest as crawl_ingest,
)
from app.crawl_admin.engines import CRAWL_KEYS


async def _scheduled_crawl() -> None:
    try:
        result = await run_event_crawl()
        if result.errors:
            print(f"[scheduler] crawl finished with errors: {result.errors}")
    except Exception as exc:
        print(f"[scheduler] event crawl FAILED: {type(exc).__name__}: {exc}")


async def _scheduled_missed_place_crawl() -> None:
    try:
        result = await run_place_crawl()
        print(
            f"[scheduler] missed_place_crawl done — "
            f"resolved={result.resolved_misses} ins={result.inserted} upd={result.updated}"
        )
        if result.errors:
            print(f"[scheduler] missed_place_crawl errors: {result.errors}")
    except Exception as exc:
        print(f"[scheduler] missed_place_crawl FAILED: {type(exc).__name__}: {exc}")


async def _scheduled_new_places_crawl() -> None:
    try:
        result = await run_new_places_crawl()
        print(
            f"[scheduler] new_places_crawl done — "
            f"ins={result.inserted} upd={result.updated}"
        )
        if result.errors:
            print(f"[scheduler] new_places_crawl errors: {result.errors}")
    except Exception as exc:
        print(f"[scheduler] new_places_crawl FAILED: {type(exc).__name__}: {exc}")

async def _scheduled_crawl_admin() -> None:
    if crawl_orch.is_running():
        return
    try:
        await crawl_orch.run_engines(CRAWL_KEYS, trigger="scheduled", force=False)
    except Exception as exc:
        print(f"[crawl-admin] scheduled run failed: {type(exc).__name__}: {exc}")


from app.api import chat, sessions, health, profile, recommend, admin, events, favorites, itineraries
from app.api import crawl_admin as crawl_admin_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("Loading embedding model...")
    encoder = SentenceTransformer(config.EMBED_MODEL_NAME, device=device)

    reranker = None
    if config.ENABLE_RERANKER:
        print("Loading reranker model...")
        try:
            reranker = CrossEncoder(config.RERANKER_MODEL_NAME, max_length=512, device=device)
        except Exception as exc:
            print(f"[startup] WARNING: Reranker failed to load ({type(exc).__name__}: {exc}). "
                  f"Continuing without reranking — result quality will be reduced.")
    else:
        print("Reranker disabled (ENABLE_RERANKER=false) — skipping to save memory.")

    print(f"Loading LLM ({config.LLM_HF_MODEL_NAME})...")
    try:
        llm = load_llm()
    except Exception as exc:
        raise RuntimeError(
            f"[startup] FATAL: Failed to load main LLM '{config.LLM_HF_MODEL_NAME}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    analyzer_llm = llm
    if config.ANALYZER_HF_MODEL_NAME != config.LLM_HF_MODEL_NAME:
        print(f"Loading analyzer model ({config.ANALYZER_HF_MODEL_NAME})...")
        try:
            analyzer_llm = load_analyzer_llm()
        except Exception as exc:
            print(f"[startup] WARNING: Analyzer model failed ({type(exc).__name__}: {exc}). "
                  f"Using main LLM for analysis.")

    print("Connecting to Qdrant...")
    qdrant = AsyncQdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, timeout=60)

    pipeline = RAGPipeline(
        encoder=encoder, llm=llm, qdrant_client=qdrant,
        reranker=reranker, analyzer_llm=analyzer_llm,
    )
    pl_module._pipeline_instance = pipeline

    # Crawl-admin tái dùng CHÍNH embedder này (tránh nạp BGE-M3 lần 2 ~2GB RAM).
    crawl_ingest.set_shared_embedder(encoder)

    print("Initializing database...")
    await db.init_db()
    await crawl_db.init_db()

    print("Starting schedulers...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_crawl,
        "interval",
        hours=config.CACHE_TTL_HOURS,
        next_run_time=datetime.now(),
        id="event_crawl",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _scheduled_missed_place_crawl,
        "interval",
        hours=config.PLACE_CRAWL_INTERVAL_HOURS,
        id="missed_place_crawl",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _scheduled_new_places_crawl,
        "interval",
        hours=config.NEW_PLACES_CRAWL_INTERVAL_HOURS,
        id="new_places_crawl",
        max_instances=1,
        coalesce=True,
    )
    # Auto-crawl khách sạn/nhà hàng — MẶC ĐỊNH TẮT (RAM ~4GB, chạy chung Playwright+chatbot).
    # Bật bằng CRAWL_SCHEDULE_ENABLED=true.
    if crawl_cfg.SCHEDULE_ENABLED:
        scheduler.add_job(
            _scheduled_crawl_admin,
            "interval",
            hours=crawl_cfg.SCHEDULE_HOURS,
            id="crawl_admin_auto",
            max_instances=1,
            coalesce=True,
        )
        print(f"[crawl-admin] auto-scheduler ON — mỗi {crawl_cfg.SCHEDULE_HOURS}h")
    scheduler.start()

    print("Warming up pipeline (first GPU pass)...")
    await pipeline.warmup()
    print("Server ready.")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    await db.close_db()
    await crawl_db.close_db()
    await qdrant.close()


app = FastAPI(title="Da Nang Travel RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(health.router)
app.include_router(profile.router)
app.include_router(recommend.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(favorites.router)
app.include_router(itineraries.router)
app.include_router(crawl_admin_api.router)

# Static cho dashboard crawl (style.css) — phục vụ tại /admin/crawl/static/*
app.mount(
    "/admin/crawl/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "crawl_admin" / "static")),
    name="crawl_admin_static",
)

# Module-level placeholder so health.py can check before pipeline loads
pl_module._pipeline_instance = None
