"""Fixtures dùng chung cho test crawl-admin (asyncio_mode=auto ở pytest.ini)."""
from __future__ import annotations
import os
import tempfile
from pathlib import Path

# Đặt trước mọi import app.* — config nạp backend/.env; QDRANT không cần cho test transform/db.
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def tmp_db(monkeypatch):
    """SQLite tạm + init schema; dọn sau test."""
    from app.crawl_admin import config
    from app.crawl_admin import db

    tmp_dir = tempfile.mkdtemp()
    monkeypatch.setattr(config, "DB_PATH", str(Path(tmp_dir) / "test.db"))
    await db.init_db()
    try:
        yield db
    finally:
        await db.close_db()
