"""Test orchestrator: freshness gate (skip/force), unknown key, khóa 1-run.
Monkeypatch _run_one (tránh chạy engine thật) + db.list_engine_state."""
from __future__ import annotations
import time

import pytest

from app import config, orchestrator


@pytest.fixture
def record_runs(monkeypatch):
    """Ghi lại key nào được _run_one gọi, không chạy engine thật."""
    called: list[str] = []

    async def _fake_run_one(key, trigger, *args, **kwargs):
        called.append(key)

    monkeypatch.setattr(orchestrator, "_run_one", _fake_run_one)
    return called


async def _set_state(monkeypatch, mapping):
    async def _list():
        return mapping
    monkeypatch.setattr(orchestrator.db, "list_engine_state", _list)


async def test_skip_recent_engine(record_runs, monkeypatch):
    now = int(time.time())
    await _set_state(monkeypatch, {"foody": {"engine": "foody", "last_run_at": now - 60, "last_status": "done"}})
    monkeypatch.setattr(config, "JOB_FRESHNESS_HOURS", 20)
    await orchestrator.run_engines(["foody"], trigger="scheduled", force=False)
    assert record_runs == []  # mới chạy 60s trước → bỏ qua


async def test_force_overrides_freshness(record_runs, monkeypatch):
    now = int(time.time())
    await _set_state(monkeypatch, {"foody": {"engine": "foody", "last_run_at": now - 60, "last_status": "done"}})
    monkeypatch.setattr(config, "JOB_FRESHNESS_HOURS", 20)
    await orchestrator.run_engines(["foody"], trigger="manual", force=True)
    assert record_runs == ["foody"]


async def test_stale_engine_runs(record_runs, monkeypatch):
    now = int(time.time())
    await _set_state(monkeypatch, {"foody": {"engine": "foody", "last_run_at": now - 30 * 3600, "last_status": "done"}})
    monkeypatch.setattr(config, "JOB_FRESHNESS_HOURS", 20)
    await orchestrator.run_engines(["foody"], trigger="scheduled", force=False)
    assert record_runs == ["foody"]  # 30h > 20h → chạy


async def test_never_run_engine_runs(record_runs, monkeypatch):
    await _set_state(monkeypatch, {})  # chưa có state
    await orchestrator.run_engines(["foody"], trigger="scheduled", force=False)
    assert record_runs == ["foody"]


async def test_unknown_key_skipped(record_runs, monkeypatch):
    await _set_state(monkeypatch, {})
    await orchestrator.run_engines(["khong_ton_tai"], trigger="manual", force=True)
    assert record_runs == []


async def test_run_ctx_stores_force():
    ctx = orchestrator.RunCtx(123, trigger="scheduled", force=False)
    assert ctx.run_id == 123
    assert ctx.trigger == "scheduled"
    assert ctx.force is False

    ctx_forced = orchestrator.RunCtx(456, trigger="manual", force=True)
    assert ctx_forced.run_id == 456
    assert ctx_forced.trigger == "manual"
    assert ctx_forced.force is True


async def test_hotel_runner_registers_callbacks(tmp_db, monkeypatch):
    from app.engines import _hotel_runner
    
    mock_engine_instance = type("MockEngine", (), {"run": lambda self: None})()
    runner = _hotel_runner(lambda: mock_engine_instance, "/tmp/dummy", "traveloka")
    
    ctx = orchestrator.RunCtx(999, trigger="manual", force=True)
    res = await runner(ctx)
    
    assert res == {"total": 0, "ok": 0, "failed": 0}
    assert hasattr(mock_engine_instance, "check_freshness_callback")
    assert hasattr(mock_engine_instance, "save_entity_callback")
    assert mock_engine_instance.check_freshness_callback("https://hotel-dummy/1") is True


