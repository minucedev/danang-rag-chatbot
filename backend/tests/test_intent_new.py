"""Test 2 intents mới: ITINERARY_SEARCH và CHITCHAT."""
from __future__ import annotations
import pytest

from app import config
from app.rag.intent import CollectionRegistry, QueryIntent


def test_itinerary_search_uses_all_three_primary_collections():
    cols = CollectionRegistry.get_collections_by_intent(QueryIntent.ITINERARY_SEARCH)
    assert config.COLLECTION_ACCOMMODATION_HOTELS in cols
    assert config.COLLECTION_RESTAURANTS in cols
    assert config.COLLECTION_PLACES in cols


def test_chitchat_returns_empty_collection_list():
    cols = CollectionRegistry.get_collections_by_intent(QueryIntent.CHITCHAT)
    assert cols == []


def test_itinerary_display_label():
    assert QueryIntent.ITINERARY_SEARCH.display == "Lịch trình"


def test_chitchat_display_label():
    assert QueryIntent.CHITCHAT.display == "Trò chuyện"


def test_all_intents_have_display_label():
    for intent in QueryIntent:
        label = intent.display
        assert isinstance(label, str) and len(label) > 0, f"Missing display for {intent}"


def test_chitchat_value():
    assert QueryIntent.CHITCHAT.value == "chitchat"


def test_itinerary_value():
    assert QueryIntent.ITINERARY_SEARCH.value == "itinerary_search"


def test_new_intents_parseable_from_string():
    """LLMQueryAnalyzer dùng QueryIntent(string) — đảm bảo parse đúng."""
    assert QueryIntent("chitchat") == QueryIntent.CHITCHAT
    assert QueryIntent("itinerary_search") == QueryIntent.ITINERARY_SEARCH
