"""Test judge: parse JSON đủ định dạng + degrade gracefully khi không khả dụng."""
from __future__ import annotations

from app import config
from app.metrics import judge


def test_parse_plain_json():
    assert judge._parse_json('{"faithfulness": 5, "relevance": 4, "accuracy": 3}') == {
        "faithfulness": 5, "relevance": 4, "accuracy": 3}


def test_parse_fenced_json():
    raw = '```json\n{"coherence": 4, "coverage": 5}\n```'
    assert judge._parse_json(raw) == {"coherence": 4, "coverage": 5}


def test_parse_json_with_surrounding_prose():
    raw = 'Đây là điểm của tôi: {"faithfulness": 4, "relevance": 4, "accuracy": 4} — hết.'
    assert judge._parse_json(raw) == {"faithfulness": 4, "relevance": 4, "accuracy": 4}


def test_parse_garbage_returns_none(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="app.metrics.judge"):
        assert judge._parse_json("không có JSON ở đây") is None
    assert "không parse được JSON" in caplog.text


def test_parse_empty_returns_none():
    assert judge._parse_json("") is None


def test_is_available_reflects_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    assert judge.is_available() is False
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    assert judge.is_available() is True


async def test_judge_general_none_without_key(monkeypatch):
    """Không có GEMINI_API_KEY → judge trả None, eval vẫn tiếp tục được."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    assert await judge.judge_general("q", "gold", "answer") is None
    assert await judge.judge_itinerary("q", "gold", "answer") is None
