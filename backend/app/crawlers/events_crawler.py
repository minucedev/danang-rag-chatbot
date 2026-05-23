from __future__ import annotations
import asyncio
import time

from app.db.events import EventDict, upsert_events, prune_old_events
from app.crawlers import serpapi_adapter
from app.utils.slugify_vn import slugify_vn

# Ánh xạ từ khóa địa chỉ sang slug quận — dùng để rút district khi adapter không cung cấp.
_DISTRICT_KEYWORDS: list[tuple[str, str]] = [
    ("hai chau", "hai chau"),
    ("son tra", "son tra"),
    ("ngu hanh son", "ngu hanh son"),
    ("cam le", "cam le"),
    ("lien chieu", "lien chieu"),
    ("thanh khe", "thanh khe"),
    ("hoa vang", "hoa vang"),
]


def _infer_district(address: str | None) -> str | None:
    if not address:
        return None
    slug = slugify_vn(address)
    for keyword_slug, district in _DISTRICT_KEYWORDS:
        if keyword_slug in slug:
            return district
    return None


class CrawlResult:
    def __init__(self) -> None:
        self.inserted = 0
        self.updated = 0
        self.errors: list[str] = []


async def run_event_crawl() -> CrawlResult:
    result = CrawlResult()
    print("[crawler] starting event crawl")

    adapter_results = await asyncio.gather(
        serpapi_adapter.fetch_events(),
        return_exceptions=True,
    )

    all_events: list[EventDict] = []
    for source_name, res in zip(["serpapi"], adapter_results):
        if isinstance(res, asyncio.CancelledError):
            raise res
        if isinstance(res, BaseException):
            msg = f"{source_name}: {type(res).__name__}: {res}"
            print(f"[crawler] adapter error — {msg}")
            result.errors.append(msg)
        elif isinstance(res, list):
            print(f"[crawler] {source_name}: fetched {len(res)} items")
            all_events.extend(res)

    # Enrich district từ address khi adapter không rút được
    for ev in all_events:
        if not ev.get("district") and ev.get("address"):
            ev["district"] = _infer_district(ev.get("address"))

    if all_events:
        ins, upd = await upsert_events(all_events)
        result.inserted = ins
        result.updated = upd
        print(f"[crawler] upsert done — inserted={ins} updated={upd}")

    # Prune sự kiện đã kết thúc > 7 ngày trước
    cutoff = int(time.time()) - 7 * 86400
    pruned = await prune_old_events(cutoff)
    if pruned:
        print(f"[crawler] pruned {pruned} old events")

    return result
