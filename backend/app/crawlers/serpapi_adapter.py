from __future__ import annotations
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from app import config
from app.db.events import EventDict

SOURCE = "serpapi"
_ENDPOINT = "https://serpapi.com/search.json"
# Múi giờ Đà Nẵng = UTC+7 (Asia/Ho_Chi_Minh). Dùng cố định, tránh phụ thuộc tz database.
_VN_TZ = timezone(timedelta(hours=7))


def _parse_when(when: Optional[str], start_date: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """Best-effort parse SerpAPI date fields. Trả (start_ts, end_ts) epoch UTC hoặc (None, None).

    SerpAPI thực tế trả 2 field tách biệt:
    - start_date: "May 24"  → chứa ngày/tháng
    - when:       "Sun, 16:00 – 18:00"  → chứa giờ (có thể 24h hoặc AM/PM)
    Năm không có → suy luận: nếu cách hôm nay > 30 ngày về quá khứ thì +1 năm.
    """
    today = datetime.now(_VN_TZ)
    year = today.year

    # Parse ngày từ start_date trước, fallback sang when
    date_raw = (start_date or when or "").strip()
    if not date_raw:
        return (None, None)

    m_date = re.search(r"([A-Za-z]{3})\s+(\d{1,2})", date_raw)
    if not m_date:
        return (None, None)
    mon_abbr, day_str = m_date.group(1), m_date.group(2)
    try:
        month = datetime.strptime(mon_abbr, "%b").month
        day = int(day_str)
    except ValueError:
        return (None, None)

    # Suy luận năm: > 30 ngày trong quá khứ → khả năng cao là năm sau
    cand = datetime(year, month, day, tzinfo=_VN_TZ)
    if (today - cand).days > 30:
        cand = cand.replace(year=year + 1)

    # Parse giờ từ when (hỗ trợ cả "16:00 – 18:00" 24h và "7 – 10 PM" AM/PM)
    start_hour, end_hour = 9, 22
    time_raw = (when or start_date or "").strip()
    m_time = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*(?:–|-|to)\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?",
        time_raw, re.IGNORECASE,
    )
    if m_time:
        sh = int(m_time.group(1))
        eh = int(m_time.group(3))
        ampm = (m_time.group(5) or "").upper()
        if ampm == "PM":
            if sh != 12: sh += 12
            if eh != 12: eh += 12
        elif ampm == "AM":
            if sh == 12: sh = 0
            if eh == 12: eh = 0
        # 24h format: giờ >= 13 không cần shift; giữ nguyên
        start_hour = sh
        end_hour = eh

    try:
        start_dt = cand.replace(hour=start_hour % 24)
        end_dt = cand.replace(hour=end_hour % 24)
        if end_dt <= start_dt:
            end_dt = end_dt + timedelta(hours=2)
        return (int(start_dt.timestamp()), int(end_dt.timestamp()))
    except ValueError:
        return (int(cand.timestamp()), None)


def _make_id(title: str, when: str, venue: str) -> str:
    """SerpAPI không expose ID ổn định → hash title+when+venue làm khoá dedup."""
    raw = f"{title}|{when}|{venue}".lower().strip()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


async def fetch_events(query: str = "Da Nang events", num: int = 50) -> list[EventDict]:
    if not config.SERPAPI_KEY:
        print("[serpapi] SERPAPI_KEY not configured — skipping adapter")
        return []

    params = {
        "engine": "google_events",
        "q": query,
        "hl": "en",
        "gl": "vn",
        "api_key": config.SERPAPI_KEY,
        "num": num,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_ENDPOINT, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"SerpAPI returned HTTP {e.response.status_code}") from None
        payload = resp.json()

    results: list[EventDict] = []
    for item in payload.get("events_results", []):
        title = item.get("title")
        if not title:
            continue
        date_blk = item.get("date") or {}
        when = date_blk.get("when") or ""
        start_date = date_blk.get("start_date") or ""
        start_ts, end_ts = _parse_when(when, start_date)

        venue_blk = item.get("venue") or {}
        venue_name = venue_blk.get("name")

        addr_list = item.get("address") or []
        address = ", ".join(addr_list) if isinstance(addr_list, list) else str(addr_list)

        results.append(EventDict(
            source=SOURCE,
            source_event_id=_make_id(title, when or start_date, venue_name or ""),
            title=title,
            description=item.get("description"),
            start_time=start_ts,
            end_time=end_ts,
            venue_name=venue_name,
            address=address or None,
            district=None,  # orchestrator slugify
            latitude=None,
            longitude=None,
            url=item.get("link"),
            image_url=item.get("thumbnail"),
            raw=item,
        ))
    return results
