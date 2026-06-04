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

    async def _fake_run_one(key, trigger):
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
