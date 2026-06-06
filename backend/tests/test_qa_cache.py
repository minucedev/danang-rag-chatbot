"""QA cache tất định (không cần model): round-trip vector, khớp cosine + intent + filters + TTL,
tăng hit_count, cap số dòng, clear. Dùng vector giả đã chuẩn hoá."""
from __future__ import annotations

import numpy as np

from app import config
from app.db import qa_cache


def _unit(arr) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float32)
    return a / np.linalg.norm(a)


_V1 = _unit([1.0, 0.0, 0.0, 0.0])
_V_NEAR = _unit([0.97, 0.24, 0.0, 0.0])   # cosine với _V1 ≈ 0.97 > ngưỡng 0.93
_V_FAR = _unit([0.0, 1.0, 0.0, 0.0])      # cosine với _V1 = 0
_FILT = {"district": "son tra"}


async def _store(q="quán hải sản ngon", vec=_V1, intent="restaurant_search", filt=_FILT):
    await qa_cache.store(q, vec, "Gợi ý: Bé Mặn, Năm Đảnh…", intent, filt, '[{"id":1}]')


def test_blob_roundtrip():
    blob = qa_cache._vec_to_blob(_V1)
    assert np.allclose(qa_cache._blob_to_vec(blob), _V1)


async def test_exact_vec_hits(tmp_db):
    await _store()
    hit = await qa_cache.find_similar(_V1, "restaurant_search", _FILT)
    assert hit is not None and "Bé Mặn" in hit["answer"]
    assert hit["score"] >= 0.99


async def test_near_vec_hits(tmp_db):
    await _store()
    hit = await qa_cache.find_similar(_V_NEAR, "restaurant_search", _FILT)
    assert hit is not None


async def test_far_vec_misses(tmp_db):
    await _store()
    assert await qa_cache.find_similar(_V_FAR, "restaurant_search", _FILT) is None


async def test_different_intent_misses(tmp_db):
    await _store()
    assert await qa_cache.find_similar(_V1, "hotel_search", _FILT) is None


async def test_different_filters_misses(tmp_db):
    await _store()
    assert await qa_cache.find_similar(_V1, "restaurant_search", {"district": "hai chau"}) is None


async def test_ttl_expired_misses(tmp_db):
    await _store()
    # ttl âm → cutoff ở tương lai → dòng vừa lưu bị loại
    assert await qa_cache.find_similar(_V1, "restaurant_search", _FILT, ttl_seconds=-100) is None


async def test_hit_increments_count(tmp_db):
    await _store()
    await qa_cache.find_similar(_V1, "restaurant_search", _FILT)
    await qa_cache.find_similar(_V1, "restaurant_search", _FILT)
    async with qa_cache._db_conn().execute("SELECT hit_count FROM qa_cache") as cur:
        row = await cur.fetchone()
    assert row["hit_count"] == 2


async def test_max_rows_cap(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "QA_CACHE_MAX_ROWS", 3)
    for i in range(5):
        await _store(q=f"câu hỏi {i}")
    async with qa_cache._db_conn().execute("SELECT COUNT(*) AS n FROM qa_cache") as cur:
        n = (await cur.fetchone())["n"]
    assert n == 3


async def test_clear(tmp_db):
    await _store()
    await qa_cache.clear()
    async with qa_cache._db_conn().execute("SELECT COUNT(*) AS n FROM qa_cache") as cur:
        assert (await cur.fetchone())["n"] == 0
