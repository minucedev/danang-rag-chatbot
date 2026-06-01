from __future__ import annotations
import asyncio
import json
import threading
import time
import uuid
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
    fallback_used: bool = False
    error_flag: bool = False

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
                session_id=session_id,
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

                elif etype == "fallback":
                    fallback_used = True
                    yield {"event": "fallback", "data": json.dumps({
                        "reason": event.get("reason"),
                        "provider": event.get("provider"),
                        "model": event.get("model"),
                    })}

                elif etype == "token":
                    token = event.get("text", "")
                    answer_tokens.append(token)
                    yield {"event": "token", "data": json.dumps({"text": token})}

                elif etype == "error":
                    # Pipeline-internal error (vd Gemini fail giữa chừng). Forward
                    # nguyên message; KHÔNG set stop_event để không cản `done` ngay sau.
                    yield {"event": "error", "data": json.dumps({
                        "message": event.get("message", "Lỗi không xác định"),
                    })}

                elif etype == "done":
                    yield {"event": "done", "data": json.dumps({"finish_reason": "stop"})}

    except Exception as exc:
        stop_event.set()
        error_flag = True
        # Tracked error: trả về error_id cho user, log đầy đủ phía server (không
        # leak `str(exc)` cho client — exception text có thể chứa path/stack-trace).
        err_id = uuid.uuid4().hex[:8]
        print(f"[chat-stream] error_id={err_id} {type(exc).__name__}: {exc}")
        yield {"event": "error", "data": json.dumps({
            "message": f"Lỗi xử lý (id={err_id})",
            "error_id": err_id,
        })}

    finally:
        # Persist final answer regardless of abort. KHÔNG để DB write làm crash
        # SSE response — wrap try/except và log nếu fail.
        full_answer = "".join(answer_tokens)
        if not full_answer and stop_event.is_set():
            full_answer = "(Đã dừng)"
        # Intent ưu tiên: error > gemini_fallback > intent gốc từ analyzer.
        # Để reload conversation không bị lừa rằng answer crashed là answer hoàn chỉnh.
        if error_flag:
            persisted_intent = "error"
        elif fallback_used:
            persisted_intent = "gemini_fallback"
        else:
            persisted_intent = intent_value

        try:
            await db.update_message_content(asst_msg_id, full_answer)
            if sources_data or fallback_used or error_flag:
                await db._db_conn().execute(
                    "UPDATE messages SET sources_json = ?, intent = ? WHERE id = ?",
                    (json.dumps(sources_data), persisted_intent, asst_msg_id),
                )
                await db._db_conn().commit()
        except Exception as persist_exc:
            print(
                f"[chat-stream] persist failed: "
                f"{type(persist_exc).__name__}: {persist_exc}"
            )


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
