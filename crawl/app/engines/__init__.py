"""Registry 3 engine: foody (nhà hàng) + agoda/booking (khách sạn).

Mỗi engine: async run(ctx) -> dict {total, ok, failed}. Engine khách sạn là sync Playwright
(crawl1 (2).py) → chạy qua run_in_executor + cầu nối logging sang log_bus (orchestrate as-is).
"""
from __future__ import annotations
import asyncio
import csv
import hashlib
import json
import logging
import random
import time
from pathlib import Path

from playwright.async_api import async_playwright

from app import config, db, discover, foody_crawler, foody_review_crawler, ingest, review_preprocessor
from app.logbus import log_bus

_VN_DISTRICTS = {
    "hải châu": "Hải Châu", "sơn trà": "Sơn Trà", "thanh khê": "Thanh Khê",
    "ngũ hành sơn": "Ngũ Hành Sơn", "cẩm lệ": "Cẩm Lệ", "liên chiểu": "Liên Chiểu",
    "hòa vang": "Hòa Vang",
}


def _entity_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _extract_district(address: str) -> str:
    low = (address or "").lower()
    for key, val in _VN_DISTRICTS.items():
        if key in low:
            return val
    return ""


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with open(path, encoding="utf-8-sig") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


# ─── Foody engine (async: discovery API → detail Playwright → CSV + DB) ───────
def _write_foody_csv(entities: list[dict]) -> None:
    rows = []
    for e in entities:
        if e.get("data_json"):
            try:
                rows.append(json.loads(e["data_json"]))
            except Exception:
                pass
    if not rows:
        return
    Path(config.DATA_FOODY).mkdir(parents=True, exist_ok=True)
    path = Path(config.DATA_FOODY) / "restaurant_detail.csv"
    # Hợp nhất key qua MỌI row (giữ thứ tự xuất hiện) — tránh mất cột nếu schema lệch giữa các lần crawl.
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


async def _run_foody(ctx) -> dict:
    await ctx.log("info", f"Foody discovery (cap {config.DISCOVERY_MAX_NEW})…")
    try:
        found = await discover.discover()
    except Exception as exc:
        await ctx.log("error", f"Discovery lỗi: {type(exc).__name__}: {exc}")
        found = []
    new = 0
    for it in found:
        district = _extract_district(it.get("address", ""))
        if await db.upsert_discovered(
            _entity_id(it["url"]), it["url"], it.get("name", ""), district, it.get("review_count")
        ):
            new += 1
    await ctx.log("info", f"Discovery: {len(found)} quán, {new} mới thêm vào hàng đợi.")

    now = int(time.time())
    targets = [
        e for e in await db.list_entities()
        if e.get("last_crawl_at") is None
        or now - e["last_crawl_at"] >= config.FRESHNESS_HOURS * 3600
    ]
    await ctx.log("info", f"{len(targets)} quán cần crawl chi tiết (bỏ qua quán mới crawl gần đây).")
    if not targets:
        return {"total": 0, "ok": 0, "failed": 0}

    counters = {"ok": 0, "failed": 0}
    reviews_lock = asyncio.Lock()
    sem = asyncio.Semaphore(config.MAX_WORKERS)

    # ─── Khởi tạo các file CSV nếu cào từ đầu (Fresh start vs Resume) ───
    all_entities = await db.list_entities()
    is_fresh_start = all(e.get("last_crawl_at") is None for e in all_entities)
    if is_fresh_start:
        await ctx.log("info", "Lượt cào mới: Xóa các file CSV cũ để bắt đầu ghi mới.")
        for fname in ["restaurant_detail.csv", "reviews_output.csv", "reviews_cleaned.csv"]:
            p = Path(config.DATA_FOODY) / fname
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
    else:
        await ctx.log("info", "Resume: Sẽ append thêm vào các file CSV hiện có.")

    async def _one(browser, ent):
        url = ent["url"]
        async with sem:
            cxt = await foody_crawler.new_context(browser)
            page = await cxt.new_page()
            try:
                await db.set_entity_status(url, "crawling")
                await ctx.log("info", f"Đang crawl: {url}")

                # Tính review_limit từ review_count hiện có (discovery API)
                try:
                    rc_est = int(float(ent.get("review_count") or 0))
                except (ValueError, TypeError):
                    rc_est = 0
                rv_limit = foody_review_crawler.review_limit(rc_est) if rc_est > 0 else 0

                data, reviews = await foody_crawler.crawl_detail_with_reviews(page, url, rv_limit)

                name = data.get("Name", "")
                district = _extract_district(data.get("Address", "")) or ent.get("district", "")
                try:
                    rc = int(float(data.get("Total review") or 0))
                except (ValueError, TypeError):
                    rc = None
                await db.replace_entity_data(
                    url, name, district, json.dumps(data, ensure_ascii=False), rc
                )
                if reviews:
                    async with reviews_lock:
                        review_preprocessor.append_reviews_to_files(reviews, config.DATA_FOODY)
                    await ctx.log("info", f"OK: {name or url} — {len(reviews)} review")
                else:
                    await ctx.log("info", f"OK: {name or url} (0 review)")

                # Ghi lại file restaurant_detail.csv đồng bộ tiến độ
                async with reviews_lock:
                    _write_foody_csv(await db.list_entities())

                counters["ok"] += 1
            except Exception as exc:
                counters["failed"] += 1
                await db.set_entity_status(url, "error", f"{type(exc).__name__}: {exc}")
                await ctx.log("error", f"FAIL {url} — {type(exc).__name__}: {exc}")
            finally:
                await cxt.close()
                await asyncio.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.FOODY_HEADLESS)
        await asyncio.gather(*[_one(browser, e) for e in targets])
        await browser.close()

    await ctx.log("info", "Đã hoàn thành lượt crawl chi tiết Foody.")
    return {"total": len(targets), "ok": counters["ok"], "failed": counters["failed"]}





# ─── Hotel engines (sync Playwright crawl1(2).py → chạy qua thread) ───────────
class _BusLogHandler(logging.Handler):
    """Đẩy log record của engine sync (chạy trong thread) sang log_bus an toàn (qua loop)."""
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._loop.call_soon_threadsafe(log_bus.publish, line)
        except Exception:
            pass


def _make_agoda():
    from app.engines.hotel_crawler import AgodaCrawlerEngine
    return AgodaCrawlerEngine(
        headless=config.HOTEL_HEADLESS,
        max_pages=config.AGODA_MAX_PAGES,
        max_hotels=config.AGODA_MAX_HOTELS,
        reviews_per_hotel=config.AGODA_REVIEWS,
        data_dir=Path(config.DATA_AGODA),
    )


def _make_booking():
    from app.engines.hotel_crawler import BookingCrawlerEngine
    return BookingCrawlerEngine(
        headless=config.HOTEL_HEADLESS,
        max_pages=config.BOOKING_MAX_PAGES,
        max_properties=config.BOOKING_MAX_PROPERTIES,
        min_reviews=config.BOOKING_MIN_REVIEWS,
        search_city=config.BOOKING_CITY,
        data_dir=Path(config.DATA_BOOKING),
    )


def _hotel_runner(make_engine, data_dir: str):
    async def _run(ctx) -> dict:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        handler = _BusLogHandler(loop)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.INFO)  # root mặc định WARNING (stdlib) → hạ INFO để bắt log INFO engine sync
        root.addHandler(handler)
        try:
            await ctx.log("info", "Khởi chạy engine khách sạn (Playwright sync trong thread)…")
            await loop.run_in_executor(None, lambda: make_engine().run())
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        n = _count_csv_rows(Path(data_dir) / "hotels.csv")
        await ctx.log("info", f"Engine xong — {n} khách sạn trong hotels.csv")
        return {"total": n, "ok": n, "failed": 0}
    return _run


# ─── Ingest job (CSV crawl → Qdrant, upsert) — chạy sync trong thread ─────────
def _ingest_runner():
    async def _run(ctx) -> dict:
        loop = asyncio.get_running_loop()

        def _log(line: str) -> None:  # gọi từ thread → đẩy lên log_bus an toàn
            loop.call_soon_threadsafe(
                log_bus.publish, f"[{time.strftime('%H:%M:%S')}] INFO: {line}")

        await ctx.log("info", "Bắt đầu ingest CSV → Qdrant (upsert)…")
        counts = await loop.run_in_executor(None, lambda: ingest.run_ingest_blocking(_log))
        total = sum(counts.values()) if counts else 0
        await ctx.log("info", f"Ingest xong: {counts}")
        return {"total": total, "ok": total, "failed": 0}
    return _run


ENGINES: dict[str, dict] = {
    "foody": {"label": "Foody — Nhà hàng + Reviews", "kind": "crawl", "run": _run_foody},
    "agoda": {"label": "Agoda — Khách sạn", "kind": "crawl", "run": _hotel_runner(_make_agoda, config.DATA_AGODA)},
    "booking": {"label": "Booking — Khách sạn", "kind": "crawl", "run": _hotel_runner(_make_booking, config.DATA_BOOKING)},
    "ingest": {"label": "⬆ Đẩy lên Qdrant", "kind": "ingest", "run": _ingest_runner()},
}

CRAWL_KEYS = [k for k, v in ENGINES.items() if v.get("kind") == "crawl"]
