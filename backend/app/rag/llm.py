from __future__ import annotations
import asyncio
import threading
from typing import AsyncIterator

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
    StoppingCriteria,
    StoppingCriteriaList,
)

from app import config


class StopOnEvent(StoppingCriteria):
    """StoppingCriteria that checks a threading.Event set by the SSE abort handler."""

    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor, **kwargs) -> bool:
        return self.stop_event.is_set()


def load_model_and_tokenizer(
    model_name: str = config.LLM_MODEL_NAME,
    use_4bit: bool = config.USE_4BIT,
):
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs: dict = {"trust_remote_code": True}

    if torch.cuda.is_available():
        model_kwargs["torch_dtype"] = torch.float16
        model_kwargs["device_map"] = {"": 0}
        if use_4bit:
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
    else:
        model_kwargs["device_map"] = "cpu"

    model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
    model.eval()
    return model, tokenizer


async def generate_streaming(
    messages: list[dict],
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    stop_event: threading.Event,
    max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
    temperature: float = config.DEFAULT_TEMPERATURE,
) -> AsyncIterator[str]:
    """Yield generated tokens one by one without blocking the asyncio event loop.

    Uses TextIteratorStreamer with model.generate in a background thread,
    and run_in_executor on each streamer.__next__ so the event loop stays responsive.
    """
    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
        timeout=60.0,
    )
    criteria = StoppingCriteriaList([StopOnEvent(stop_event)])

    # Prepare model inputs (sync, fast)
    try:
        encoded = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
    except TypeError:
        input_ids = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        )
        encoded = {"input_ids": input_ids}

    model_inputs = {
        k: v.to(model.device) if hasattr(v, "to") else v
        for k, v in encoded.items()
    }

    gen_kwargs = {
        **model_inputs,
        "streamer": streamer,
        "max_new_tokens": max_new_tokens,
        "do_sample": temperature > 0,
        "temperature": temperature,
        "top_p": 0.9,
        "repetition_penalty": 1.1,
        "stopping_criteria": criteria,
        "pad_token_id": tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }

    def _run_generate():
        with torch.no_grad():
            model.generate(**gen_kwargs)

    # Start generation in background thread
    gen_thread = threading.Thread(target=_run_generate, daemon=True)
    gen_thread.start()

    # Read tokens asynchronously — each next() blocks ~(1 token time) in the executor,
    # freeing the event loop to handle other coroutines (disconnect checks, heartbeat).
    loop = asyncio.get_running_loop()
    streamer_iter = iter(streamer)

    def _get_next():
        try:
            return next(streamer_iter)
        except StopIteration:
            return None

    while True:
        token = await loop.run_in_executor(None, _get_next)
        if token is None or stop_event.is_set():
            break
        yield token

    gen_thread.join(timeout=5)
