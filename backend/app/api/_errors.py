"""Helper xử lý lỗi 500 đồng nhất cho các router: log đầy đủ phía server + trả err_id cho client
(không lộ chi tiết exception). Thay cho pattern try/except → uuid + print lặp lại nhiều nơi."""
from __future__ import annotations
import logging
import uuid

from fastapi import HTTPException

logger = logging.getLogger("app.api")


def tracked_500(tag: str, exc: Exception) -> HTTPException:
    """Gọi trong khối except. Trả về HTTPException(500) kèm err_id; raise nó ở caller."""
    err_id = uuid.uuid4().hex[:8]
    logger.error("[%s] error_id=%s: %s: %s", tag, err_id, type(exc).__name__, exc, exc_info=exc)
    return HTTPException(status_code=500, detail=f"{tag} failed (id={err_id})")
