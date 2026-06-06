"""Test router metrics-admin qua TestClient (mount router trên app trống, không cần model)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config as backend_config
from app.api import metrics_admin
from app.crawl_admin import config as crawl_config
from app.metrics import runner, store


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(metrics_admin.router)
    return TestClient(app)


def test_run_invalid_suite_400(client, monkeypatch):
    monkeypatch.setattr(runner, "is_running", lambda: False)
    r = client.post("/admin/metrics/api/run", json={"suite": "bad"})
    assert r.status_code == 400


def test_run_conflict_when_running_409(client, monkeypatch):
    monkeypatch.setattr(runner, "is_running", lambda: True)
    r = client.post("/admin/metrics/api/run", json={"suite": "both"})
    assert r.status_code == 409


def test_run_started_200(client, monkeypatch):
    monkeypatch.setattr(runner, "is_running", lambda: False)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(runner, "run_eval", _noop)

    r = client.post("/admin/metrics/api/run", json={"suite": "general", "enable_judge": False})
    assert r.status_code == 200
    assert r.json() == {"started": True}


def test_run_detail_404(client):
    r = client.get("/admin/metrics/api/runs/20200101-000000")
    assert r.status_code == 404


def test_run_csv_404(client):
    r = client.get("/admin/metrics/api/runs/20200101-000000/eval_report_card.csv")
    assert r.status_code == 404


def test_runs_list_ok(client, monkeypatch):
    monkeypatch.setattr(store, "list_runs", lambda: [{"id": "x", "n_pass": 1, "n_total": 2}])
    r = client.get("/admin/metrics/api/runs")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "x"


def test_write_auth_blocks_without_token_503(client, monkeypatch):
    monkeypatch.setattr(crawl_config, "REQUIRE_TOKEN", True)
    monkeypatch.setattr(backend_config, "ADMIN_TOKEN", "secret")
    monkeypatch.setattr(runner, "is_running", lambda: False)
    r = client.post("/admin/metrics/api/run", json={"suite": "both"})
    assert r.status_code == 503


def test_write_auth_allows_with_token(client, monkeypatch):
    monkeypatch.setattr(crawl_config, "REQUIRE_TOKEN", True)
    monkeypatch.setattr(backend_config, "ADMIN_TOKEN", "secret")
    monkeypatch.setattr(runner, "is_running", lambda: False)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(runner, "run_eval", _noop)

    r = client.post("/admin/metrics/api/run", json={"suite": "both"},
                    headers={"x-admin-token": "secret"})
    assert r.status_code == 200
