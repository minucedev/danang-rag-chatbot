"""Streaming wrapper gọi Gemini REST khi local RAG không có dữ liệu.

Gọi endpoint:
    POST {GEMINI_BASE_URL}/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse&key={KEY}

Không dùng SDK `google-generativeai` để khỏi thêm dependency — `httpx` đã có sẵn
trong requirements.txt. API key đọc từ `config.GEMINI_API_KEY` (env), KHÔNG hard-code.
"""
from __future__ import annotations
import asyncio
import json
import threading
from typing import AsyncIterator

import httpx

from app import config


class GeminiFallbackError(Exception):
    """Raised khi Gemini không khả dụng — pipeline catch và rơi xuống local LLM.

    `status_code` được set khi lỗi là HTTP non-200 (None nếu transport / timeout / config error).
    Cho phép caller phân biệt 401 (key sai — nên alert) vs 429/503 (transient — chỉ log).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _convert_messages(messages: list[dict]) -> tuple[dict | None, list[dict]]:
    """OpenAI-style messages → (systemInstruction, contents) cho Gemini.

    - role "system" → gộp tất cả vào `systemInstruction.parts[].text`.
    - role "assistant" → "model" (Gemini không nhận "assistant").
    - role "user" → giữ nguyên.
    """
    system_parts: list[dict] = []
    contents: list[dict] = []
    for m in messages:
        role = m.get("role")
        text = m.get("content", "")
        if not text:
            continue
        if role == "system":
            system_parts.append({"text": text})
        else:
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


async def generate_gemini_streaming(
    messages: list[dict],
    stop_event: threading.Event,
    max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
    temperature: float = config.DEFAULT_TEMPERATURE,
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """Yield chunk text từ Gemini stream. Cùng signature/style với `generate_streaming`."""
    if not config.GEMINI_API_KEY:
        raise GeminiFallbackError("GEMINI_API_KEY not configured")

    timeout = timeout if timeout is not None else config.GEMINI_TIMEOUT_SECONDS
    system_instruction, contents = _convert_messages(messages)
    if not contents:
        raise GeminiFallbackError("No user/assistant content to send to Gemini")

    body: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_new_tokens,
        },
    }
    if system_instruction:
        body["systemInstruction"] = system_instruction

    url = (
        f"{config.GEMINI_BASE_URL.rstrip('/')}"
        f"/models/{config.GEMINI_MODEL}:streamGenerateContent"
    )
    params = {"alt": "sse", "key": config.GEMINI_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, params=params, json=body) as resp:
                if resp.status_code != 200:
                    # Đọc body để debug; tránh leak key bằng cách KHÔNG log url.
                    err_body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise GeminiFallbackError(
                        f"Gemini HTTP {resp.status_code}: {err_body[:300]}",
                        status_code=resp.status_code,
                    )

                yielded_any = False
                async for raw_line in resp.aiter_lines():
                    if stop_event.is_set():
                        break
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    payload = raw_line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # candidates[0].content.parts[*].text
                    for cand in obj.get("candidates", []) or []:
                        parts = (cand.get("content") or {}).get("parts") or []
                        for p in parts:
                            text = p.get("text")
                            if text:
                                yielded_any = True
                                yield text

                # Nếu stream kết thúc bình thường nhưng không có text nào (wire-format
                # thay đổi, hoặc safety filter chặn) → raise để pipeline biết fallback
                # thất bại và dùng local LLM thay vì trả bubble rỗng.
                if not yielded_any and not stop_event.is_set():
                    raise GeminiFallbackError(
                        "Gemini stream returned no text chunks (possibly safety-blocked or format changed)"
                    )
    except httpx.HTTPError as e:
        raise GeminiFallbackError(f"Gemini transport error: {type(e).__name__}: {e}") from e
    except asyncio.CancelledError:
        raise
