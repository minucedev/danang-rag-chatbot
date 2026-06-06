"""Semantic QA cache (SQLite): câu hỏi gần trùng câu đã trả lời tốt → trả lại ngay, bỏ Gemini.

Lưu embedding câu hỏi (BGE-M3, float32 1024) dạng BLOB; so khớp bằng cosine trong bộ nhớ (cache nhỏ,
cap QA_CACHE_MAX_ROWS nên brute-force rẻ). Khớp thêm intent + filters để không trả nhầm câu khác điều kiện.
Dùng chung connection với app.db.sessions.
"""
from __future__ import annotations
import json
import time
from typing import Any, Optional

import numpy as np

from app import config
from app.db.sessions import _db_conn


def _vec_to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _canon_filters(filters: Optional[dict]) -> str:
    """Chuỗi JSON chuẩn hoá để so khớp filter chính xác: bỏ rỗng/None, sort list + sort key."""
    out: dict[str, Any] = {}
    for k, v in (filters or {}).items():
        if v in (None, "", [], {}):
            continue
        out[k] = sorted(v) if isinstance(v, list) else v
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


async def find_similar(
    vec, intent: str, filters: Optional[dict],
    threshold: float = None, ttl_seconds: int = None,
) -> Optional[dict]:
    """Trả {answer, sources_json, score} của câu gần trùng nhất (≥ threshold, cùng intent + filters),
    đồng thời tăng hit_count. None nếu không có."""
    threshold = config.QA_CACHE_SIM_THRESHOLD if threshold is None else threshold
    ttl_seconds = config.QA_CACHE_TTL_DAYS * 86400 if ttl_seconds is None else ttl_seconds
    canon = _canon_filters(filters)
    cutoff = int(time.time()) - ttl_seconds
    qv = np.asarray(vec, dtype=np.float32)

    async with _db_conn().execute(
        "SELECT id, question_vec, answer, sources_json FROM qa_cache "
        "WHERE intent = ? AND filters_json = ? AND created_at >= ?",
        (intent, canon, cutoff),
    ) as cur:
        rows = await cur.fetchall()

    best = None
    best_score = threshold
    for r in rows:
        score = float(np.dot(qv, _blob_to_vec(r["question_vec"])))
        if score >= best_score:
            best_score = score
            best = r
    if best is None:
        return None

    await _db_conn().execute(
        "UPDATE qa_cache SET hit_count = hit_count + 1, last_used_at = ? WHERE id = ?",
        (int(time.time()), best["id"]),
    )
    await _db_conn().commit()
    return {"answer": best["answer"], "sources_json": best["sources_json"], "score": best_score}


async def store(
    question: str, vec, answer: str, intent: str,
    filters: Optional[dict], sources_json: Optional[str],
) -> None:
    """Lưu (hoặc cập nhật) 1 cặp Q&A. Cap số dòng theo QA_CACHE_MAX_ROWS (xoá cũ nhất)."""
    now = int(time.time())
    await _db_conn().execute(
        """
        INSERT INTO qa_cache
            (question, question_vec, answer, intent, filters_json, sources_json, created_at, last_used_at, hit_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(question, intent) DO UPDATE SET
            question_vec = excluded.question_vec,
            answer       = excluded.answer,
            filters_json = excluded.filters_json,
            sources_json = excluded.sources_json,
            created_at   = excluded.created_at,
            last_used_at = excluded.last_used_at
        """,
        (question, _vec_to_blob(vec), answer, intent, _canon_filters(filters),
         sources_json, now, now),
    )
    # Cap: xoá dòng cũ nhất khi vượt trần.
    await _db_conn().execute(
        "DELETE FROM qa_cache WHERE id IN ("
        "  SELECT id FROM qa_cache ORDER BY created_at DESC LIMIT -1 OFFSET ?"
        ")",
        (config.QA_CACHE_MAX_ROWS,),
    )
    await _db_conn().commit()


async def clear() -> None:
    await _db_conn().execute("DELETE FROM qa_cache")
    await _db_conn().commit()
