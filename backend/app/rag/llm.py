from __future__ import annotations
import asyncio
import os
import re
import threading
from pathlib import Path
from typing import AsyncIterator, Iterator

import torch
from transformers import (
    AutoProcessor, AutoModelForImageTextToText, AutoModelForCausalLM,
    AutoTokenizer, TextIteratorStreamer,
)

from app import config


class QwenHF:
    """HuggingFace Transformers wrapper mimicking llama.cpp Llama interface.

    Expose create_chat_completion() để analyzer.py và pipeline.py không cần thay đổi.
    """

    def __init__(self, model, processor, device: str) -> None:
        self.model = model
        self.processor = processor
        self.device = device

    def _get_tokenizer(self):
        """Trả về tokenizer đúng: VLM dùng processor.tokenizer, text-only dùng processor."""
        return self.processor.tokenizer if hasattr(self.processor, "tokenizer") else self.processor

    def _decode(self, token_ids) -> str:
        """Decode token IDs — dùng tokenizer đúng cho cả VLM và text-only."""
        return self._get_tokenizer().decode(token_ids, skip_special_tokens=True).strip()

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
        inputs = self.processor(text=text, return_tensors="pt").to(self.device)
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                pad_token_id=self._get_tokenizer().eos_token_id,
            )
        generated = output_ids[0][inputs["input_ids"].shape[-1]:]
        content = self._decode(generated)
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
        inputs = self.processor(text=text, return_tensors="pt").to(self.device)
        streamer = TextIteratorStreamer(
            self._get_tokenizer(),
            skip_special_tokens=True,
            skip_prompt=True,
        )
        do_sample = temperature > 0
        gen_kwargs: dict = {
            **inputs,
            "max_new_tokens": max_tokens,
            "do_sample": do_sample,
            "streamer": streamer,
            "pad_token_id": self._get_tokenizer().eos_token_id,
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


class QwenGGUF:
    """llama-cpp-python Llama wrapper mimicking QwenHF interface.

    Expose create_chat_completion() để analyzer.py và pipeline.py không cần thay đổi.
    """

    def __init__(self, model_path: str, n_ctx: int, n_gpu_layers: int) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "llama-cpp-python is not installed. Please run `pip install llama-cpp-python` to use GGUF models."
            ) from exc

        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers

        kwargs = dict(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_batch=512,
            verbose=False,
        )
        try:
            self.model = Llama(**kwargs, chat_format="qwen")
        except ValueError:
            # llama-cpp-python < 0.2.85 chưa có preset "qwen" — fallback chatml.
            self.model = Llama(**kwargs, chat_format="chatml")

    def create_chat_completion(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.2,
        stream: bool = False,
        **kwargs,
    ):
        if not stream:
            res = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
                **kwargs,
            )
            content = res["choices"][0]["message"]["content"]
            res["choices"][0]["message"]["content"] = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
            return res
        else:
            return self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
                **kwargs,
            )


def get_gguf_absolute_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    backend_dir = Path(__file__).resolve().parent.parent
    candidate = backend_dir / path
    if candidate.exists():
        return str(candidate.resolve())
    return path


def _build_load_kwargs(device: str, dtype, use_4bit: bool = False) -> dict:
    """Tạo kwargs load model, tuỳ chọn 4-bit quantization."""
    kwargs = dict(device_map="auto", trust_remote_code=True)
    if use_4bit and device == "cuda":
        try:
            from transformers import BitsAndBytesConfig
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            print("  [4-bit quantization enabled]")
        except (ImportError, RuntimeError, OSError, AttributeError) as bnb_exc:
            print(f"  [WARNING] 4-bit unavailable ({type(bnb_exc).__name__}: {bnb_exc}) — loading in fp16")
            kwargs["torch_dtype"] = dtype
    else:
        kwargs["torch_dtype"] = dtype
    return kwargs


def _load_processor_and_model(model_name: str, load_kwargs: dict, is_vlm: bool, local_only: bool = False):
    """Load processor + model. VLM dùng AutoModelForImageTextToText, text-only dùng AutoModelForCausalLM."""
    extra = {"trust_remote_code": True}
    if local_only:
        extra["local_files_only"] = True

    if is_vlm:
        processor = AutoProcessor.from_pretrained(model_name, **extra)
        model = AutoModelForImageTextToText.from_pretrained(model_name, **load_kwargs, **({"local_files_only": True} if local_only else {}))
    else:
        processor = AutoTokenizer.from_pretrained(model_name, **extra)
        model = AutoModelForCausalLM.from_pretrained(model_name, **load_kwargs, **({"local_files_only": True} if local_only else {}))
    return processor, model


def _load_model_from_name(
    model_name: str, device: str, dtype, use_4bit: bool = False, is_vlm: bool = True
) -> QwenHF:
    """Load QwenHF từ HF model name/local path. Ưu tiên: local → cache → download.

    is_vlm=True: dùng AutoModelForImageTextToText (vision-language model)
    is_vlm=False: dùng AutoModelForCausalLM (text-only model)
    """
    is_local = os.path.isdir(model_name)
    load_kwargs = _build_load_kwargs(device, dtype, use_4bit)

    if is_local:
        print(f"  Loading from local path: {model_name}")
        processor, model = _load_processor_and_model(model_name, load_kwargs, is_vlm)
    else:
        try:
            processor, model = _load_processor_and_model(model_name, load_kwargs, is_vlm, local_only=True)
            print(f"  Loaded {model_name} from cache (no download needed)")
        except OSError as cache_exc:
            print(f"  [INFO] Cache miss ({type(cache_exc).__name__}) — downloading {model_name}...")
            processor, model = _load_processor_and_model(model_name, load_kwargs, is_vlm)

    model.eval()
    return QwenHF(model=model, processor=processor, device=device)


def load_llm() -> QwenHF | QwenGGUF:
    """Load generator LLM (text-only Qwen, optional 4-bit, supports HF and GGUF)."""
    if config.USE_GGUF:
        print(f"Loading local GGUF model via llama.cpp: {config.LLM_GGUF_PATH}")
        return QwenGGUF(
            model_path=get_gguf_absolute_path(config.LLM_GGUF_PATH),
            n_ctx=config.LLM_N_CTX,
            n_gpu_layers=config.LLM_N_GPU_LAYERS,
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    return _load_model_from_name(
        config.LLM_HF_MODEL_NAME, device, dtype, use_4bit=config.LLM_LOAD_IN_4BIT, is_vlm=False
    )


def load_analyzer_llm() -> QwenHF | QwenGGUF:
    """Load analyzer LLM (supports HF and GGUF)."""
    if config.USE_GGUF:
        print(f"Loading local GGUF analyzer via llama.cpp: {config.LLM_GGUF_PATH}")
        return QwenGGUF(
            model_path=get_gguf_absolute_path(config.LLM_GGUF_PATH),
            n_ctx=config.LLM_N_CTX,
            n_gpu_layers=config.LLM_N_GPU_LAYERS,
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    return _load_model_from_name(
        config.ANALYZER_HF_MODEL_NAME, device, dtype, use_4bit=False, is_vlm=False
    )


async def generate_streaming(
    messages: list[dict],
    llm: QwenHF | QwenGGUF,
    stop_event: threading.Event,
    max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
    temperature: float = config.DEFAULT_TEMPERATURE,
) -> AsyncIterator[str]:
    """Yield generated text chunks. Chạy Qwen LLM stream trong executor."""
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
