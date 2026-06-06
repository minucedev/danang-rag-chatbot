"""Test store: round-trip save/list/get, chống path traversal, bỏ qua run hỏng."""
from __future__ import annotations

import pytest

from app.metrics import store


@pytest.fixture
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def _result(run_id, created_at, **extra):
    base = {
        "id": run_id, "created_at": created_at, "suite": "both",
        "enable_judge": False, "n_pass": 5, "n_total": 9,
        "report_card": [{"group": "Retrieval", "metric": "MRR", "score": "0.9",
                         "target": "≥ 0.60", "pass": "✅"}],
        "retrieval_rows": [{"id": "H01", "mrr": 0.9}],
        "generation_rows": [], "itinerary_rows": [], "perf_rows": [],
    }
    base.update(extra)
    return base


def test_save_then_get_roundtrip(tmp_runs):
    store.save_run(_result("20260606-101010", 1000))
    got = store.get_run("20260606-101010")
    assert got is not None
    assert got["id"] == "20260606-101010"
    assert got["n_pass"] == 5
    # CSV report card được ghi
    assert store.get_csv_path("20260606-101010", "eval_report_card") is not None
    # CSV không có dữ liệu (itinerary rỗng) thì không tạo file
    assert store.get_csv_path("20260606-101010", "eval_itinerary") is None


def test_list_runs_sorted_newest_first(tmp_runs):
    store.save_run(_result("20260606-090000", 1000))
    store.save_run(_result("20260606-120000", 3000))
    store.save_run(_result("20260606-100000", 2000))
    runs = store.list_runs()
    assert [r["created_at"] for r in runs] == [3000, 2000, 1000]


def test_list_runs_skips_corrupt(tmp_runs, caplog):
    import logging
    store.save_run(_result("20260606-101010", 1000))
    # Tạo 1 run hỏng: thư mục có result.json không phải JSON hợp lệ
    bad = tmp_runs / "20260606-999999"
    bad.mkdir(parents=True)
    (bad / "result.json").write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.metrics.store"):
        runs = store.list_runs()
    assert [r["id"] for r in runs] == ["20260606-101010"]
    assert "bỏ qua run hỏng" in caplog.text


@pytest.mark.parametrize("bad_id", ["../../etc", "..", "a/b", "foo bar", "', ;", ""])
def test_get_run_rejects_traversal(tmp_runs, bad_id):
    assert store.get_run(bad_id) is None


@pytest.mark.parametrize("bad_id", ["../../secret", "..", "x/y"])
def test_get_csv_path_rejects_traversal(tmp_runs, bad_id):
    assert store.get_csv_path(bad_id, "eval_report_card") is None


def test_get_csv_path_rejects_unknown_name(tmp_runs):
    store.save_run(_result("20260606-101010", 1000))
    assert store.get_csv_path("20260606-101010", "../result") is None
    assert store.get_csv_path("20260606-101010", "passwd") is None


def test_get_run_missing_returns_none(tmp_runs):
    assert store.get_run("20260606-000000") is None
