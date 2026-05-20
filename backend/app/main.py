from __future__ import annotations
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer

from app import config
from app.db import sessions as db
from app.rag.llm import load_llm
from app.rag.pipeline import RAGPipeline
import app.rag.pipeline as pl_module

from app.api import chat, sessions, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────
    print("Loading embedding model...")
    encoder = SentenceTransformer(
        config.EMBED_MODEL_NAME,
        device="cuda" if torch.cuda.is_available() else "cpu",
    )

    print("Loading LLM (llama.cpp)...")
    llm = load_llm()

    print("Connecting to Qdrant...")
    qdrant = AsyncQdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, timeout=60)

    pipeline = RAGPipeline(encoder=encoder, llm=llm, qdrant_client=qdrant)
    pl_module._pipeline_instance = pipeline

    print("Initializing database...")
    await db.init_db()

    print("Warming up pipeline (first GPU pass)...")
    await pipeline.warmup()
    print("Server ready.")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    await db.close_db()
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

# Module-level placeholder so health.py can check before pipeline loads
pl_module._pipeline_instance = None
