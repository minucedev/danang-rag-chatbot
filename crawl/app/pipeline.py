"""Pipeline crawl: chọn entity theo độ "cũ" → crawl song song → ghi đè DB → log realtime.

Hiện thực logic crawl-update.txt (phần Entity + lịch crawl):
- lưu last_crawl_at mỗi entity; bỏ qua nếu mới crawl < FRESHNESS_HOURS;
- entity chưa có / quá cũ (>= STALE_HOURS) thì thêm vào danh sách;
- crawl được mới thay thế HOÀN TOÀN data trong DB.
(Discovery từ trang listing + crawl review = v2.)
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import random
import time

from playwright.async_api import async_playwright

from app import config, db, foody_crawler

_VN_DISTRICTS = {
    "hải châu": "Hải Châu", "sơn trà": "Sơn Trà", "thanh khê": "Thanh Khê",
    "ngũ hành sơn": "Ngũ Hành Sơn", "cẩm lệ": "Cẩm Lệ", "liên chiểu": "Liên Chiểu",
    "hòa vang": "Hòa Vang",
}


class _LogBus:
    """Pub/sub log realtime cho SSE (mỗi client 1 Queue)."""

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def publish(self, line: str) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass


log_bus = _LogBus()
_run_lock = asyncio.Lock()
_state: dict = {"running": False, "run_id": None, "phase": "idle"}


def is_running() -> bool:
    return _state["running"]


def get_state() -> dict:
    return dict(_state)


def _entity_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _extract_district(address: str) -> str:
    low = (address or "").lower()
    for key, val in _VN_DISTRICTS.items():
        if key in low:
            return val
    return ""


async def _emit(run_id, level: str, message: str) -> None:
    log_bus.publish(f"[{time.strftime('%H:%M:%S')}] {level.upper()}: {message}")
    try:
        await db.add_log(run_id, level, message)
    except Exception:
        pass


async def select_targets(freshness_hours: int, stale_hours: int) -> list[tuple[dict, str]]:
    """Trả [(source, reason)] cần crawl. reason ∈ {new, due, stale}."""
    now = int(time.time())
    targets: list[tuple[dict, str]] = []
    for s in await db.list_active_sources():
        ent = await db.get_entity_by_url(s["url"])
        if not ent or ent.get("last_crawl_at") is None:
            targets.append((s, "new"))
            continue
        age = now - ent["last_crawl_at"]
        if age >= stale_hours * 3600:
            targets.append((s, "stale"))
        elif age >= freshness_hours * 3600:
            targets.append((s, "due"))
        # else: mới crawl gần đây → bỏ qua
    return targets


async def _crawl_one(browser, sem: asyncio.Semaphore, source: dict, run_id: int, counters: dict) -> None:
    url = source["url"]
    async with sem:
        ctx = await foody_crawler.new_context(browser)
        page = await ctx.new_page()
        try:
            await db.set_entity_status(url, "crawling")
            data = await foody_crawler.crawl_detail(page, url)
            name = data.get("Name", "")
            district = _extract_district(data.get("Address", ""))
            try:
                review_count = int(float(data.get("Total review") or 0))
            except (ValueError, TypeError):
                review_count = None
            await db.replace_entity_data(
                url, name, district, json.dumps(data, ensure_ascii=False), review_count
            )
            counters["ok"] += 1
            await _emit(run_id, "info", f"OK: {name or url}")
        except Exception as exc:
            counters["failed"] += 1
            await db.set_entity_status(url, "error", f"{type(exc).__name__}: {exc}")
            await _emit(run_id, "error", f"FAIL {url} — {type(exc).__name__}: {exc}")
        finally:
            await ctx.close()
            await asyncio.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))


async def run_crawl(trigger: str = "manual", freshness_hours: int | None = None,
                    stale_hours: int | None = None) -> int:
    if _run_lock.locked():
        raise RuntimeError("Đang có một lượt crawl chạy — vui lòng đợi.")
    freshness_hours = config.FRESHNESS_HOURS if freshness_hours is None else freshness_hours
    stale_hours = config.STALE_HOURS if stale_hours is None else stale_hours

    async with _run_lock:
        _state.update(running=True, phase="selecting", run_id=None)
        run_id = await db.create_run(trigger)
        _state["run_id"] = run_id
        counters = {"ok": 0, "failed": 0}
        try:
            await _emit(run_id, "info",
                        f"Bắt đầu crawl (trigger={trigger}, freshness={freshness_hours}h, stale={stale_hours}h)")
            targets = await select_targets(freshness_hours, stale_hours)
            total = len(targets)
            await _emit(run_id, "info",
                        f"Chọn {total} entity cần crawl (bỏ qua entity mới crawl gần đây)")
            for s, reason in targets:
                await db.ensure_entity(_entity_id(s["url"]), s["url"], s["id"])
                await _emit(run_id, "info", f"  → {s['url']} ({reason})")

            if total == 0:
                await db.finish_run(run_id, "done", 0, 0, 0)
                await _emit(run_id, "info", "Không có entity nào tới hạn. Xong.")
                return run_id

            _state["phase"] = "crawling"
            sem = asyncio.Semaphore(config.MAX_WORKERS)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=config.HEADLESS)
                await asyncio.gather(*[
                    _crawl_one(browser, sem, s, run_id, counters) for s, _ in targets
                ])
                await browser.close()

            await db.finish_run(run_id, "done", total, counters["ok"], counters["failed"])
            await _emit(run_id, "info",
                        f"DONE — ok={counters['ok']} failed={counters['failed']}/{total}")
            return run_id
        except Exception as exc:
            await db.finish_run(run_id, "error", 0, counters["ok"], counters["failed"])
            await _emit(run_id, "error", f"Run lỗi: {type(exc).__name__}: {exc}")
            raise
        finally:
            _state.update(running=False, phase="idle")
