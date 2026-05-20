from __future__ import annotations
import asyncio
import threading
from typing import AsyncIterator

from llama_cpp import Llama

from app import config


def load_llm() -> Llama:
    """Load Qwen2.5-3B-Instruct GGUF Q4_K_M via llama.cpp.

    Trả về 1 Llama object — đóng vai trò cả model + tokenizer.
    Streaming và chat template do llama.cpp tự handle qua chat_format.
    """
    kwargs = dict(
        model_path=config.LLM_GGUF_PATH,
        n_ctx=config.LLM_N_CTX,
        n_gpu_layers=config.LLM_N_GPU_LAYERS,
        n_batch=512,
        verbose=False,
    )
    try:
        return Llama(**kwargs, chat_format="qwen")
    except ValueError:
        # llama-cpp-python < 0.2.85 chưa có preset "qwen" — fallback chatml.
        return Llama(**kwargs, chat_format="chatml")


async def generate_streaming(
    messages: list[dict],
    llm: Llama,
    stop_event: threading.Event,
    max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
    temperature: float = config.DEFAULT_TEMPERATURE,
) -> AsyncIterator[str]:
    """Yield generated text chunks. Chạy llama.cpp.create_chat_completion
    trong executor để không block event loop."""
    loop = asyncio.get_running_loop()

    def _start_stream():
        return llm.create_chat_completion(
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=temperature,
            top_p=0.9,
            repeat_penalty=1.1,
            stream=True,
        )

    stream = await loop.run_in_executor(None, _start_stream)

    def _next_chunk(it):
        try:
            return next(it)
        except StopIteration:
            return None

    while True:
        if stop_event.is_set():
            break
        chunk = await loop.run_in_executor(None, _next_chunk, stream)
        if chunk is None:
            break
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        text = delta.get("content")
        if text:
            yield text
