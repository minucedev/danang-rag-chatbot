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
import time
from typing import AsyncIterator

import httpx

from app import config

# Circuit breaker deadline (monotonic seconds). Read/write xảy ra trên asyncio event loop
# thread — single-threaded, không cần lock. 0.0 = không trong cooldown.
_quota_disabled_until: float = 0.0


def _arm_cooldown(status_code: int) -> None:
    global _quota_disabled_until
    if status_code == 429:
        duration = config.GEMINI_QUOTA_COOLDOWN_SECONDS
    elif status_code == 503:
        duration = config.GEMINI_503_COOLDOWN_SECONDS
    else:
        return
    if duration <= 0:
        return
    new_deadline = time.monotonic() + duration
    if new_deadline > _quota_disabled_until:
        _quota_disabled_until = new_deadline
        human = time.strftime("%H:%M:%S", time.localtime(time.time() + duration))
        print(
            f"[gemini-circuit-breaker] OPEN — HTTP {status_code}. "
            f"Suppressed for {duration:.0f}s (until ~{human})."
        )


class GeminiFallbackError(Exception):
    """Raised khi Gemini không khả dụng — pipeline catch và rơi xuống local LLM.

    `status_code` được set khi lỗi là HTTP non-200 (None nếu transport/timeout/config error).
    Cho phép caller phân biệt:
      - 401: key sai hoặc hết billing — nên alert.
      - 429/503: transient — chỉ log.
      - None: transport/timeout error.
    Lưu ý: status_code=429 cũng được set khi circuit breaker OPEN (không có HTTP call).
    Cả hai trường hợp đều nghĩa là Gemini tạm thời không khả dụng.
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
    global _quota_disabled_until
    if not config.GEMINI_API_KEY:
        raise GeminiFallbackError("GEMINI_API_KEY not configured")

    now = time.monotonic()
    if now < _quota_disabled_until:
        remaining = _quota_disabled_until - now
        raise GeminiFallbackError(
            f"Gemini circuit breaker OPEN — cooldown active ({remaining:.0f}s remaining)",
            status_code=429,
        )
    elif _quota_disabled_until > 0.0:
        _quota_disabled_until = 0.0
        print("[gemini-circuit-breaker] CLOSED — cooldown expired, resuming.")

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

    _BACKOFF = [1, 2]  # giây chờ trước attempt 2 và 3
    # yielded_any theo dõi toàn bộ vòng lặp: nếu đã stream partial thì không retry
    # (tránh gửi duplicate tokens tới client).
    yielded_any = False

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(_BACKOFF[attempt - 1])

            try:
                async with client.stream("POST", url, params=params, json=body) as resp:
                    if resp.status_code != 200:
                        # Đọc body để debug; tránh leak key bằng cách KHÔNG log url.
                        err_body = (await resp.aread()).decode("utf-8", errors="replace")
                        if resp.status_code == 503 and attempt < 2:
                            print(f"[gemini] 503 attempt {attempt+1}/3, retrying in {_BACKOFF[attempt]}s...")
                            continue
                        _arm_cooldown(resp.status_code)
                        raise GeminiFallbackError(
                            f"Gemini HTTP {resp.status_code}: {err_body[:300]}",
                            status_code=resp.status_code,
                        )

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
                        except json.JSONDecodeError as exc:
                            print(f"[gemini-fallback] SSE JSON parse error (skipping frame): {exc} — payload={payload[:80]!r}")
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
                    return  # Stream thành công, thoát retry loop

            except GeminiFallbackError:
                raise
            except httpx.TimeoutException as e:
                # Timeout thường xảy ra khi Gemini throttle bằng cách giữ connection thay vì trả 429.
                # Không retry nếu đã bắt đầu stream: tránh gửi duplicate tokens tới client.
                if attempt < 2 and not yielded_any:
                    print(f"[gemini] Timeout attempt {attempt+1}/3, retrying in {_BACKOFF[attempt]}s...")
                    continue
                _arm_cooldown(503)
                raise GeminiFallbackError(f"Gemini timeout: {type(e).__name__}: {e}") from e
            except httpx.HTTPError as e:
                raise GeminiFallbackError(f"Gemini transport error: {type(e).__name__}: {e}") from e
            except asyncio.CancelledError:
                raise
