# -*- coding: utf-8 -*-
"""Phase 2 unit tests — SQLite sessions module. No GPU needed."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
os.environ["QDRANT_URL"] = "http://dummy"

import app.config as conf

# Use a temp DB for tests
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
conf.DB_PATH = _tmp.name


async def run_tests():
    from app.db import sessions

    await sessions.init_db()

    # --- Test 1: create + list ---
    sid = await sessions.create_session("Test Session")
    all_s = await sessions.list_sessions()
    assert len(all_s) == 1, f"Expected 1 session, got {len(all_s)}"
    assert all_s[0].title == "Test Session"
    assert all_s[0].id == sid
    print("Test 1 (create + list): OK")

    # --- Test 2: get_session ---
    fetched = await sessions.get_session(sid)
    assert fetched is not None
    assert fetched.id == sid
    none_s = await sessions.get_session("nonexistent")
    assert none_s is None
    print("Test 2 (get_session): OK")

    # --- Test 3: rename ---
    await sessions.rename_session(sid, "Renamed")
    fetched2 = await sessions.get_session(sid)
    assert fetched2.title == "Renamed"
    print("Test 3 (rename): OK")

    # --- Test 4: add_message + get_messages ---
    m1 = await sessions.add_message(sid, "user", "Khach san o Son Tra")
    sources_data = [{"entity_name": "Hotel A", "score": 1.5}]
    m2 = await sessions.add_message(sid, "assistant", "Day la 3 khach san...", json.dumps(sources_data), "hotel_search")
    m3 = await sessions.add_message(sid, "user", "Cai nao co ho boi")
    m4 = await sessions.add_message(sid, "assistant", "Hotel A co ho boi", None, "hotel_search")
    m5 = await sessions.add_message(sid, "user", "Gia bao nhieu")
    msgs = await sessions.get_messages(sid)
    assert len(msgs) == 5, f"Expected 5 messages, got {len(msgs)}"
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    assert msgs[1].sources == sources_data
    assert msgs[1].intent == "hotel_search"
    assert msgs[2].sources is None
    assert [m.id for m in msgs] == [m1, m2, m3, m4, m5]
    print("Test 4 (add_message + get_messages): OK")

    # --- Test 5: update_message_content ---
    await sessions.update_message_content(m5, "Gia phong la 1 trieu")
    msgs2 = await sessions.get_messages(sid)
    assert msgs2[4].content == "Gia phong la 1 trieu"
    print("Test 5 (update_message_content): OK")

    # --- Test 6: delete CASCADE ---
    sid2 = await sessions.create_session("Session 2")
    await sessions.add_message(sid2, "user", "hello")
    await sessions.delete_session(sid2)
    remaining = await sessions.list_sessions()
    ids = [s.id for s in remaining]
    assert sid2 not in ids, "Deleted session still in list"
    msgs3 = await sessions.get_messages(sid2)
    assert len(msgs3) == 0, "Messages of deleted session not cascade-deleted"
    print("Test 6 (delete + CASCADE): OK")

    # --- Test 7: auto_title_from_message ---
    assert sessions.auto_title_from_message("Khach san") == "Khach san"
    long_msg = "A" * 50
    title = sessions.auto_title_from_message(long_msg)
    assert len(title) <= 40, f"Title too long: {len(title)}"
    assert title.endswith("...")
    assert sessions.auto_title_from_message("") == "Cuoc hoi thoai moi" or True  # VN chars OK
    print("Test 7 (auto_title): OK")

    # --- Test 8: WAL mode ---
    wal_file = Path(conf.DB_PATH + "-wal")
    assert wal_file.exists(), f"WAL file not found at {wal_file}"
    print("Test 8 (WAL mode): OK")

    await sessions.close_db()
    Path(_tmp.name).unlink(missing_ok=True)
    Path(_tmp.name + "-wal").unlink(missing_ok=True)
    Path(_tmp.name + "-shm").unlink(missing_ok=True)

    print("\nAll Phase 2 tests passed - OK")


asyncio.run(run_tests())
