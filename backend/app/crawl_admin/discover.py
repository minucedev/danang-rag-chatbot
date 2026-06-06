"""Auto-discovery quán Đà Nẵng từ API listing công khai của Foody (không cần Playwright).

Dùng endpoint nội bộ __get/Place/HomeListPlace (trả JSON, phân trang tăng dần theo `page`
theo đúng thứ tự API trả về). Trả danh sách entity để pipeline crawl chi tiết sau.
"""
from __future__ import annotations
import asyncio

import httpx

from app.crawl_admin import config

_API = "https://www.foody.vn/__get/Place/HomeListPlace"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


_CITY_COOKIES = {
    "da-nang": "219",
    "danang": "219",
    "ha-noi": "218",
    "hanoi": "218",
    "ho-chi-minh": "217",
    "hcm": "217",
}


async def discover(
    city: str | None = None,
    max_new: int | None = None,
    page_count: int | None = None,
) -> list[dict]:
    """Phân trang API listing → list {url, name, address, review_count, avg_rating}.

    Dừng khi đủ `max_new` quán hoặc hết trang. URL trả về là URL tuyệt đối.
    """
    city = city or config.DISCOVERY_CITY
    max_new = max_new or config.DISCOVERY_MAX_NEW
    page_count = page_count or config.DISCOVERY_PAGE_COUNT

    out: list[dict] = []
    seen: set[str] = set()
    headers = {**_HEADERS, "Referer": f"https://www.foody.vn/{city}"}

    # Foody yêu cầu cookie floc (location code) để lọc chính xác tỉnh thành
    cookies = {"flg": "vn"}
    loc_id = _CITY_COOKIES.get(city.lower())
    if loc_id:
        cookies["floc"] = loc_id

    async with httpx.AsyncClient(timeout=25.0, headers=headers, cookies=cookies) as client:
        for page in range(1, config.DISCOVERY_MAX_PAGES + 1):
            if len(out) >= max_new:
                break
            params = {"t": page, "page": page, "count": page_count, "type": 1, "city": city}
            resp = await client.get(_API, params=params)
            resp.raise_for_status()
            items = (resp.json() or {}).get("Items") or []
            if not items:
                break
            for it in items:
                rel = (it.get("Url") or "").strip()
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                url = rel if rel.startswith("http") else f"https://www.foody.vn{rel}"
                out.append({
                    "url": url,
                    "name": it.get("Name") or "",
                    "address": it.get("Address") or "",
                    "review_count": it.get("TotalReviews"),
                    "avg_rating": it.get("AvgRating"),
                })
                if len(out) >= max_new:
                    break
            await asyncio.sleep(config.DISCOVERY_PAGE_DELAY)

    return out[:max_new]
