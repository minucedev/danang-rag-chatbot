"""Điều phối đa-engine: chạy 1 hoặc nhiều engine lần lượt, khóa 1-run, freshness theo engine."""
from __future__ import annotations
import asyncio
import time

from app import config, db
from app.engines import ENGINES
from app.logbus import log_bus

_run_lock = asyncio.Lock()
_state: dict = {"running": False, "engine": None, "run_id": None}


def is_running() -> bool:
    return _state["running"]


def get_state() -> dict:
    return dict(_state)


class RunCtx:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    async def log(self, level: str, msg: str) -> None:
        log_bus.publish(f"[{time.strftime('%H:%M:%S')}] {level.upper()}: {msg}")
        try:
            await db.add_log(self.run_id, level, msg)
        except Exception:
            pass


async def _run_one(key: str, trigger: str) -> None:
    eng = ENGINES[key]
    run_id = await db.create_run(engine=key, trigger=trigger)
    ctx = RunCtx(run_id)
    _state.update(running=True, engine=key, run_id=run_id)
    await ctx.log("info", f"══ Engine '{key}' bắt đầu (trigger={trigger}) ══")
    try:
        counts = await eng["run"](ctx) or {}
        await db.finish_run(run_id, "done", counts.get("total", 0),
                            counts.get("ok", 0), counts.get("failed", 0))
        await db.set_engine_state(key, int(time.time()), "done")
        await ctx.log("info", f"══ Engine '{key}' xong: {counts} ══")
    except Exception as exc:
        await db.finish_run(run_id, "error", 0, 0, 0)
        await db.set_engine_state(key, int(time.time()), "error")
        await ctx.log("error", f"Engine '{key}' lỗi: {type(exc).__name__}: {exc}")


async def run_engines(keys: list[str], trigger: str = "manual", force: bool = False) -> None:
    """Chạy lần lượt các engine. force=True bỏ qua freshness (nút Chạy từng engine)."""
    if _run_lock.locked():
        raise RuntimeError("Đang có một lượt crawl chạy — vui lòng đợi.")
    async with _run_lock:
        try:
            now = int(time.time())
            state = await db.list_engine_state()
            for key in keys:
                if key not in ENGINES:
                    continue
                if not force:
                    st = state.get(key)
                    if st and st.get("last_run_at") and \
                            now - st["last_run_at"] < config.JOB_FRESHNESS_HOURS * 3600:
                        log_bus.publish(
                            f"[{time.strftime('%H:%M:%S')}] INFO: Bỏ qua '{key}' (mới chạy gần đây)."
                        )
                        continue
                await _run_one(key, trigger)
        finally:
            _state.update(running=False, engine=None)
