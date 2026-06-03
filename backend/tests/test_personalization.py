"""Tests cho cá nhân hoá chat: _build_profile_note + _inject_profile (pipeline.py)."""
from __future__ import annotations

import pytest

# pipeline.py import transformers ở top-level → skip nếu env nhẹ chưa cài.
pytest.importorskip("transformers", reason="pipeline imports transformers")

from app.rag import pipeline as pl  # noqa: E402
from app.rag.schemas import UserProfile  # noqa: E402


def test_profile_note_includes_fields_with_vi_mapping():
    note = pl._build_profile_note(
        UserProfile(
            display_name="Olivia",
            companions="couple",
            budget_level="low",
            interests=["beach", "food"],
            dietary="ăn chay",
        )
    )
    assert "Olivia" in note
    assert "cặp đôi" in note          # _COMPANION_VI[couple]
    assert "tiết kiệm" in note         # _BUDGET_VI[low]
    assert "biển, ẩm thực" in note     # _INTEREST_VI[beach,food]
    assert "ăn chay" in note


def test_empty_profile_note_is_empty():
    assert pl._build_profile_note(UserProfile()) == ""


def test_inject_appends_to_system_message_only():
    msgs = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "hi"},
    ]
    out = pl._inject_profile(msgs, "\nNOTE")
    assert out[0]["content"] == "BASE\nNOTE"
    assert out[1]["content"] == "hi"  # user message không đổi


def test_inject_noop_when_note_empty():
    msgs = [{"role": "system", "content": "BASE"}]
    assert pl._inject_profile(msgs, "")[0]["content"] == "BASE"


def test_inject_noop_when_first_msg_not_system():
    msgs = [{"role": "user", "content": "hi"}]
    assert pl._inject_profile(msgs, "\nNOTE")[0]["content"] == "hi"
