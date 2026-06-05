"""Test db: idempotency upsert_discovered, engine_state, replace_entity_data."""
from __future__ import annotations


async def test_upsert_discovered_idempotent(tmp_db):
    db = tmp_db
    new1 = await db.upsert_discovered("id1", "https://x/q", "Tên gốc", "hai chau", 10)
    new2 = await db.upsert_discovered("id1", "https://x/q", "Tên KHÁC", "son tra", 99)
    assert new1 is True   # lần đầu = mới
    assert new2 is False  # lần 2 cùng url = không mới
    ent = await db.get_entity_by_url("https://x/q")
    assert ent["name"] == "Tên gốc"   # KHÔNG ghi đè (DO NOTHING)
    assert ent["review_count"] == 10


async def test_replace_entity_data_sets_done(tmp_db):
    db = tmp_db
    await db.ensure_entity("id1", "https://x/q", None)
    await db.set_entity_status("https://x/q", "error", "boom")
    await db.replace_entity_data("https://x/q", "KS", "son tra", '{"a":1}', 5)
    ent = await db.get_entity_by_url("https://x/q")
    assert ent["status"] == "done"
    assert ent["error"] == ""
    assert ent["name"] == "KS"
    assert ent["last_crawl_at"] is not None


async def test_engine_state_roundtrip(tmp_db):
    db = tmp_db
    await db.set_engine_state("foody", 111, "done")
    await db.set_engine_state("foody", 222, "error")  # upsert, không nhân bản
    state = await db.list_engine_state()
    assert set(state.keys()) == {"foody"}
    assert state["foody"]["last_run_at"] == 222
    assert state["foody"]["last_status"] == "error"


async def test_create_finish_run(tmp_db):
    db = tmp_db
    rid = await db.create_run(engine="traveloka", trigger="manual")
    await db.finish_run(rid, "done", 5, 4, 1)
    runs = await db.list_runs()
    assert runs[0]["id"] == rid
    assert runs[0]["engine"] == "traveloka"
    assert runs[0]["status"] == "done"
    assert (runs[0]["ok"], runs[0]["total"], runs[0]["failed"]) == (4, 5, 1)
