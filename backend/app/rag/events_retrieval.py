from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from app import config
from app.db.events import query_events

_VN_TZ = timezone(timedelta(hours=7))


def _format_event_time(start_ts: Optional[int], end_ts: Optional[int]) -> str:
    if not start_ts:
        return "Chưa rõ thời gian"
    start = datetime.fromtimestamp(start_ts, tz=_VN_TZ)
    label = start.strftime("%A, %d/%m/%Y %H:%M")
    if end_ts:
        end = datetime.fromtimestamp(end_ts, tz=_VN_TZ)
        label += f" – {end.strftime('%H:%M')}"
    return label


async def retrieve_events(
    district: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    limit: int = config.DEFAULT_EVENT_LIMIT,
) -> list[dict]:
    """Trả danh sách event từ SQLite cho chat pipeline.

    Mặc định: cửa sổ thời gian = now → now + DEFAULT_EVENT_DAYS ngày.
    Trả dict với field tương tự SearchResultSchema.to_dict() để pipeline xử lý thống nhất.
    """
    now = int(time.time())
    s = start_ts if start_ts is not None else now
    e = end_ts if end_ts is not None else now + config.DEFAULT_EVENT_DAYS * 86400

    rows = await query_events(s, e, district=district, limit=limit)
    return [_to_source_dict(r) for r in rows]


def _to_source_dict(row: dict) -> dict:
    """Chuyển event record sang shape dùng trong SSE 'sources' event + context builder."""
    return {
        "id": row.get("id"),
        "type": "event",
        "title": row.get("title", ""),
        "venue_name": row.get("venue_name"),
        "address": row.get("address"),
        "district": row.get("district"),
        "start_time": row.get("start_time"),
        "end_time": row.get("end_time"),
        "time_display": _format_event_time(row.get("start_time"), row.get("end_time")),
        "url": row.get("url"),
        "image_url": row.get("image_url"),
        "source": row.get("source"),
        "description": row.get("description"),
    }


def format_events_context(events: list[dict]) -> str:
    """Format danh sách event thành context text cho LLM."""
    if not events:
        return "Không tìm thấy sự kiện nào phù hợp trong thời gian này."
    parts = []
    for i, ev in enumerate(events[:10], 1):
        lines = [f"[{i}] {ev['title']}"]
        lines.append(f"   - Thời gian: {ev['time_display']}")
        if ev.get("venue_name"):
            lines.append(f"   - Địa điểm: {ev['venue_name']}")
        if ev.get("address"):
            lines.append(f"   - Địa chỉ: {ev['address']}")
        if ev.get("description"):
            lines.append(f"   - Mô tả: {ev['description'][:200]}")
        if ev.get("url"):
            lines.append(f"   - Link: {ev['url']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
