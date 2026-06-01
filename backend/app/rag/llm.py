from __future__ import annotations
import asyncio
import re
import threading
from typing import AsyncIterator, Iterator

import torch
from transformers import AutoProcessor, AutoModelForImageTextToText, TextIteratorStreamer

from app import config


class QwenHF:
    """HuggingFace Transformers wrapper mimicking llama.cpp Llama interface.

    Expose create_chat_completion() để analyzer.py và pipeline.py không cần thay đổi.
    """

    def __init__(self, model, processor, device: str) -> None:
        self.model = model
        self.processor = processor
        self.device = device

    def create_chat_completion(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.2,
        stream: bool = False,
        **_ignored,
    ):
        if stream:
            return self._stream(messages, max_tokens, temperature)
        return self._generate_sync(messages, max_tokens)

    def _generate_sync(self, messages: list[dict], max_tokens: int) -> dict:
        """Blocking generation — dùng cho analyzer (JSON output, do_sample=False)."""
        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.processor([text], return_tensors="pt").to(self.device)
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                pad_token_id=self.processor.tokenizer.eos_token_id,
            )
        generated = output_ids[0][inputs["input_ids"].shape[-1]:]
        content = self.processor.decode(generated, skip_special_tokens=True).strip()
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        return {"choices": [{"message": {"content": content}}]}

    def _stream(self, messages: list[dict], max_tokens: int, temperature: float) -> Iterator:
        """Streaming generation qua TextIteratorStreamer + daemon thread.

        Yield dict cùng format llama.cpp: {"choices": [{"delta": {"content": "..."}}]}
        """
        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.processor([text], return_tensors="pt").to(self.device)
        streamer = TextIteratorStreamer(
            self.processor.tokenizer,
            skip_special_tokens=True,
            skip_prompt=True,
        )
        do_sample = temperature > 0
        gen_kwargs: dict = {
            **inputs,
            "max_new_tokens": max_tokens,
            "do_sample": do_sample,
            "streamer": streamer,
            "pad_token_id": self.processor.tokenizer.eos_token_id,
        }
        if do_sample:
            gen_kwargs["temperature"] = temperature
        thread = threading.Thread(
            target=self.model.generate, kwargs=gen_kwargs, daemon=True
        )
        thread.start()
        for chunk in streamer:
            if chunk:
                yield {"choices": [{"delta": {"content": chunk}}]}


def load_llm() -> QwenHF:
    """Load Qwen3.5-4B via HuggingFace Transformers.

    Ưu tiên: local path → HF cache → download.
    Set LLM_HF_MODEL_NAME thành đường dẫn thư mục để load offline.
    """
    import os

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    model_name = config.LLM_HF_MODEL_NAME
    is_local = os.path.isdir(model_name)
    load_kwargs = dict(torch_dtype=dtype, device_map="auto", trust_remote_code=True)

    if is_local:
        print(f"  Loading LLM from local path: {model_name}")
        processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForImageTextToText.from_pretrained(model_name, **load_kwargs)
    else:
        try:
            processor = AutoProcessor.from_pretrained(
                model_name, local_files_only=True, trust_remote_code=True
            )
            model = AutoModelForImageTextToText.from_pretrained(
                model_name, local_files_only=True, **load_kwargs
            )
            print(f"  Loaded {model_name} from cache (no download needed)")
        except OSError:
            print(f"  Downloading {model_name} from HuggingFace...")
            processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
            model = AutoModelForImageTextToText.from_pretrained(model_name, **load_kwargs)

    model.eval()
    return QwenHF(model=model, processor=processor, device=device)


async def generate_streaming(
    messages: list[dict],
    llm: QwenHF,
    stop_event: threading.Event,
    max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
    temperature: float = config.DEFAULT_TEMPERATURE,
) -> AsyncIterator[str]:
    """Yield generated text chunks. Chạy QwenHF._stream() trong executor."""
    loop = asyncio.get_running_loop()

    def _start_stream():
        return llm.create_chat_completion(
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=temperature,
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
