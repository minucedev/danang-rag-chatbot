from __future__ import annotations
import asyncio
import json
import threading
import time
from typing import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.rag.schemas import ChatRequest
from app.db import sessions as db
from app import config

router = APIRouter()

# Single GPU — only one generation at a time
inference_lock = asyncio.Lock()

# Import pipeline lazily to avoid circular import at module level
def _get_pipeline():
    from app.rag import pipeline as pl_module
    return pl_module._pipeline_instance


async def _event_stream(
    req: ChatRequest,
    request: Request,
) -> AsyncIterator[dict]:
    pipeline = _get_pipeline()
    stop_event = threading.Event()

    # Ensure session exists
    session_id = req.session_id
    if not session_id or not await db.get_session(session_id):
        title = db.auto_title_from_message(req.message)
        session_id = await db.create_session(title)

    # Persist user message immediately
    user_msg_id = await db.add_message(session_id, "user", req.message)

    # Create assistant placeholder so client has the ID before streaming
    asst_msg_id = await db.add_message(session_id, "assistant", "")

    yield {
        "event": "meta",
        "data": json.dumps({
            "session_id": session_id,
            "user_message_id": user_msg_id,
            "assistant_message_id": asst_msg_id,
            "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }),
    }

    # Load history for multi-turn context (exclude the just-added placeholder)
    all_msgs = await db.get_messages(session_id)
    history = [
        {"role": m.role, "content": m.content, "sources": m.sources}
        for m in all_msgs
        if m.id not in (user_msg_id, asst_msg_id)
    ]

    filters = req.filters.model_dump(exclude_none=True) if req.filters else None

    answer_tokens: list[str] = []
    intent_value: str | None = None
    sources_data: list[dict] = []

    try:
        # Wait for lock — notify frontend if another request is ahead
        if inference_lock.locked():
            yield {"event": "waiting", "data": json.dumps({"message": "Đang chờ lượt..."})}

        async with inference_lock:
            async for event in pipeline.answer_stream(
                query=req.message,
                history=history,
                filters=filters,
                stop_event=stop_event,
                max_new_tokens=config.DEFAULT_MAX_TOKENS,
                temperature=config.DEFAULT_TEMPERATURE,
            ):
                # Check client disconnect on every event
                if await request.is_disconnected():
                    stop_event.set()
                    break

                etype = event.get("type")

                if etype == "intent":
                    intent_value = event.get("value")
                    yield {"event": "intent", "data": json.dumps({
                        "value": event.get("value"),
                        "display": event.get("display"),
                    })}

                elif etype == "sources":
                    sources_data = event.get("items", [])
                    yield {"event": "sources", "data": json.dumps({
                        "items": sources_data,
                        "total": event.get("total", 0),
                    })}

                elif etype == "token":
                    token = event.get("text", "")
                    answer_tokens.append(token)
                    yield {"event": "token", "data": json.dumps({"text": token})}

                elif etype == "done":
                    yield {"event": "done", "data": json.dumps({"finish_reason": "stop"})}

    except Exception as exc:
        stop_event.set()
        yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    finally:
        # Persist final answer regardless of abort
        full_answer = "".join(answer_tokens)
        if not full_answer and stop_event.is_set():
            full_answer = "(Đã dừng)"
        await db.update_message_content(asst_msg_id, full_answer)

        # Persist sources_json on the assistant message
        if sources_data:
            await db._db_conn().execute(
                "UPDATE messages SET sources_json = ?, intent = ? WHERE id = ?",
                (json.dumps(sources_data), intent_value, asst_msg_id),
            )
            await db._db_conn().commit()


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    return EventSourceResponse(
        _event_stream(req, request),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
        ping=15,  # heartbeat every 15s to keep proxy alive
    )
