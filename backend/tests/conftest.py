"""Fixtures dùng chung. `asyncio_mode=auto` (pytest.ini) cho phép test viết
`async def test_...` không cần `@pytest.mark.asyncio`."""
from __future__ import annotations
import os
import tempfile
from pathlib import Path

# CRITICAL: phải set BEFORE bất kỳ `from app...` import nào trong test files.
# `app.config` validate `QDRANT_URL` ở module-load. Dùng dummy values là an toàn vì
# test thật không gọi Qdrant (đều mock client) và `load_dotenv()` ở config.py không
# ghi đè key đã có sẵn trong env.
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-dummy")

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _reset_gemini_circuit_breaker():
    """Circuit breaker của Gemini là module-global → reset trước mỗi test để tránh
    rò rỉ cooldown giữa các test (1 test arm 429/503 sẽ làm test sau OPEN nhầm)."""
    from app.rag import gemini_fallback
    gemini_fallback._quota_disabled_until = 0.0
    yield


@pytest_asyncio.fixture
async def tmp_db(monkeypatch):
    """Override `config.DB_PATH` thành file tạm + init schema, dọn sau test."""
    from app import config
    from app.db import sessions as db

    tmp_dir = tempfile.mkdtemp()
    tmp_path = Path(tmp_dir) / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path))

    await db.init_db()
    try:
        yield
    finally:
        await db.close_db()
