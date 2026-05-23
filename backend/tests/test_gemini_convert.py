"""Unit tests cho `gemini_fallback._convert_messages` và guard của wrapper."""
from __future__ import annotations
import threading

import pytest

from app.rag.gemini_fallback import (
    GeminiFallbackError,
    _convert_messages,
    generate_gemini_streaming,
)


def test_merges_multiple_system_into_single_systemInstruction():
    msgs = [
        {"role": "system", "content": "Bạn là trợ lý"},
        {"role": "system", "content": "Trả lời ngắn"},
        {"role": "user", "content": "hi"},
    ]
    sys_inst, contents = _convert_messages(msgs)
    assert sys_inst == {"parts": [{"text": "Bạn là trợ lý"}, {"text": "Trả lời ngắn"}]}
    assert contents == [{"role": "user", "parts": [{"text": "hi"}]}]


def test_renames_assistant_to_model_and_keeps_user():
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    _, contents = _convert_messages(msgs)
    assert [c["role"] for c in contents] == ["user", "model", "user"]


def test_skips_empty_content():
    msgs = [
        {"role": "system", "content": ""},  # bị skip
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": ""},  # bị skip
        {"role": "user", "content": "y"},
    ]
    sys_inst, contents = _convert_messages(msgs)
    assert sys_inst is None  # không system nào pass → None
    assert len(contents) == 2
    assert contents[0]["parts"][0]["text"] == "x"
    assert contents[1]["parts"][0]["text"] == "y"


def test_system_instruction_none_when_no_system_role():
    sys_inst, contents = _convert_messages([{"role": "user", "content": "hi"}])
    assert sys_inst is None
    assert len(contents) == 1


async def test_raises_when_all_messages_empty(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
    stop = threading.Event()
    with pytest.raises(GeminiFallbackError, match="No user/assistant content"):
        async for _ in generate_gemini_streaming(
            [{"role": "user", "content": ""}], stop
        ):
            pass


async def test_raises_when_api_key_missing(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    stop = threading.Event()
    with pytest.raises(GeminiFallbackError, match="GEMINI_API_KEY"):
        async for _ in generate_gemini_streaming(
            [{"role": "user", "content": "hi"}], stop
        ):
            pass
