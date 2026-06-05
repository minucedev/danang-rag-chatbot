"""Registry 3 engine: foody (nhà hàng) + traveloka/booking (khách sạn).

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
    dropped = 0
    for e in entities:
        if e.get("data_json"):
            try:
                rows.append(json.loads(e["data_json"]))
            except Exception:
                dropped += 1
    if dropped:
        logging.warning("_write_foody_csv: bỏ %d entity có data_json hỏng (không ghi vào CSV)", dropped)
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
    all_ents = await db.list_entities()
    targets = []
    discovered_urls = {it["url"] for it in found}
    
    for e in all_ents:
        url = e["url"]
        last_crawl = e.get("last_crawl_at")
        if last_crawl is None or (now - last_crawl) >= config.STALE_HOURS * 3600:
            targets.append(e)
        elif url in discovered_urls and (now - last_crawl) >= config.FRESHNESS_HOURS * 3600:
            targets.append(e)
            
    await ctx.log(
        "info",
        f"{len(targets)} quán được đưa vào queue crawl chi tiết "
        f"(gồm các quán bị stale > {config.STALE_HOURS}h hoặc các quán quét từ list > {config.FRESHNESS_HOURS}h)."
    )
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

                data, reviews = await foody_crawler.crawl_detail_with_reviews(
                    page, url, rv_limit, last_crawl_at=ent.get("last_crawl_at")
                )

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
        try:
            await asyncio.gather(*[_one(browser, e) for e in targets])
        finally:
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


def _make_traveloka():
    from app.engines.hotel_crawler import TravelokaCrawlerEngine
    return TravelokaCrawlerEngine(
        headless=config.TRAVELOKA_HEADLESS,
        max_pages=config.TRAVELOKA_MAX_PAGES,
        max_hotels=config.TRAVELOKA_MAX_HOTELS,
        min_reviews=config.TRAVELOKA_REVIEWS,
        data_dir=Path(config.DATA_TRAVELOKA),
    )


def _make_booking():
    from app.engines.hotel_crawler import BookingCrawlerEngine
    return BookingCrawlerEngine(
        headless=config.BOOKING_HEADLESS,
        max_pages=config.BOOKING_MAX_PAGES,
        max_properties=config.BOOKING_MAX_PROPERTIES,
        min_reviews=config.BOOKING_MIN_REVIEWS,
        search_city=config.BOOKING_CITY,
        data_dir=Path(config.DATA_BOOKING),
    )


def _hotel_runner(make_engine, data_dir: str, engine_key: str):
    async def _run(ctx) -> dict:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        
        # Lấy thời điểm cào gần nhất của engine này từ SQLite DB
        state = await db.get_engine_state(engine_key)
        last_run_at = state.get("last_run_at") if state else None
        
        # Lọc các hotel URL bị stale trong DB để đưa vào queue cào (target_urls)
        stale_urls = []
        now = int(time.time())
        all_ents = await db.list_entities()
        for e in all_ents:
            url = e["url"]
            is_match = (engine_key == "traveloka" and "traveloka.com" in url) or \
                       (engine_key == "booking" and "booking.com" in url)
            if is_match:
                last_crawl = e.get("last_crawl_at")
                if last_crawl is None or (now - last_crawl) >= config.STALE_HOURS * 3600:
                    stale_urls.append(url)
                    
        await ctx.log("info", f"Tìm thấy {len(stale_urls)} khách sạn đã đến hạn hoặc chưa cào từ DB cần cào lại.")
        
        loop = asyncio.get_running_loop()
        handler = _BusLogHandler(loop)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.INFO)  # root mặc định WARNING (stdlib) → hạ INFO để bắt log INFO engine sync
        root.addHandler(handler)
        
        # Callback check freshness của từng hotel URL trong DB entities (chỉ skip nếu mới cào trong vòng FRESHNESS_HOURS)
        def check_freshness(url: str) -> bool:
            coro = db.get_entity_by_url(url)
            ent = asyncio.run_coroutine_threadsafe(coro, loop).result()
            if not ent:
                return True
            last_crawl = ent.get("last_crawl_at")
            if last_crawl is None:
                return True
            
            return (int(time.time()) - last_crawl) >= config.FRESHNESS_HOURS * 3600

        # Callback lưu thông tin hotel vào DB entities sau khi crawl xong
        def save_entity(url: str, name: str, data_json: str, review_count: int, address: str = ""):
            entity_id = hashlib.sha1(url.encode("utf-8")).hexdigest()
            district = _extract_district(address)
            # Tạo entity rỗng nếu chưa có
            asyncio.run_coroutine_threadsafe(
                db.ensure_entity(entity_id, url, None), loop
            ).result()
            # Ghi đè dữ liệu mới cào
            asyncio.run_coroutine_threadsafe(
                db.replace_entity_data(url, name, district, data_json, review_count), loop
            ).result()

        def _execute_crawl():
            engine = make_engine()
            engine.last_crawl_at = last_run_at
            engine.check_freshness_callback = check_freshness
            engine.save_entity_callback = save_entity
            engine.target_urls = stale_urls
            engine.run()

        try:
            await ctx.log("info", f"Khởi chạy engine {engine_key} (Playwright sync trong thread, last_crawl={last_run_at})…")
            await loop.run_in_executor(None, _execute_crawl)
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
    "traveloka": {"label": "Traveloka — Khách sạn", "kind": "crawl", "run": _hotel_runner(_make_traveloka, config.DATA_TRAVELOKA, "traveloka")},
    "booking": {"label": "Booking — Khách sạn", "kind": "crawl", "run": _hotel_runner(_make_booking, config.DATA_BOOKING, "booking")},
    "ingest": {"label": "⬆ Đẩy lên Qdrant", "kind": "ingest", "run": _ingest_runner()},
}

CRAWL_KEYS = [k for k, v in ENGINES.items() if v.get("kind") == "crawl"]
