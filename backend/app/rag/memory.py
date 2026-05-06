from __future__ import annotations
from typing import List
from app.utils.nfc import normalize_nfc

# Vietnamese deictic / anaphoric references that signal the query needs prior context
_DEICTIC = {"đó", "kia", "này", "vừa rồi", "cái", "chỗ", "nó", "họ", "ấy", "trên", "đấy"}


def needs_context(query: str) -> bool:
    """Return True if the query is likely incomplete without conversation history."""
    q = normalize_nfc(query).lower().strip()
    # Short queries are almost always follow-ups
    if len(q.split()) < 6:
        return True
    # Contains a deictic reference
    return any(ref in q for ref in _DEICTIC)


def build_search_query(history: list[dict], new_query: str) -> str:
    """Enrich the new query with entity names from the last assistant turn if needed.

    history items: {"role": "user"|"assistant", "content": str, "sources": list[dict] | None}
    """
    if not needs_context(new_query):
        return new_query

    # Find the last assistant message that had sources
    last_sources: list[dict] = []
    for msg in reversed(history):
        if msg.get("role") == "assistant" and msg.get("sources"):
            last_sources = msg["sources"]
            break

    if not last_sources:
        return new_query

    names = []
    for s in last_sources[:3]:
        name = s.get("entity_name") or s.get("parent_entity_name") or s.get("place_name")
        if name and name not in ("None", "", "null"):
            names.append(name)

    if not names:
        return new_query

    return f"{new_query} ({', '.join(names)})"


def build_history_messages(history: list[dict], max_turns: int = 3) -> list[dict]:
    """Return the last max_turns user-assistant pairs as chat messages for the LLM.

    Strips sources from assistant messages — the LLM only needs the text.
    """
    pairs: list[tuple[dict, dict]] = []
    i = 0
    items = [m for m in history if m.get("role") in ("user", "assistant")]
    while i < len(items) - 1:
        if items[i]["role"] == "user" and items[i + 1]["role"] == "assistant":
            pairs.append((items[i], items[i + 1]))
            i += 2
        else:
            i += 1

    recent = pairs[-max_turns:]
    messages = []
    for user_msg, asst_msg in recent:
        messages.append({"role": "user", "content": user_msg["content"]})
        messages.append({"role": "assistant", "content": asst_msg["content"]})
    return messages
