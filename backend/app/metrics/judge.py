"""LLM-as-a-Judge dùng Gemini có sẵn của app (port prompt từ pbl7-metrics cell 14 & 28).

Tái dùng `gemini_fallback.generate_gemini_streaming` (đã có circuit breaker + đọc key từ
env) rồi gom toàn bộ chunk thành 1 chuỗi và parse JSON. Không thêm dependency/SDK mới.

Judge là TÙY CHỌN: thiếu GEMINI_API_KEY hoặc lỗi → trả None, eval vẫn hoàn tất.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Dict, Optional

from app import config
from app.rag.gemini_fallback import GeminiFallbackError, generate_gemini_streaming

GENERAL_JUDGE_PROMPT = """Bạn là giám khảo đánh giá câu trả lời của chatbot du lịch Đà Nẵng.

Câu hỏi: {query}
Câu trả lời mẫu: {gold}
Câu trả lời của chatbot: {answer}

Hãy chấm điểm trên thang 1–5 cho 3 tiêu chí sau và trả về JSON duy nhất:
- faithfulness: câu trả lời có bịa thông tin không liên quan không? (5=hoàn toàn trung thực)
- relevance: câu trả lời có liên quan đến câu hỏi không? (5=rất liên quan)
- accuracy: thông tin có chính xác, đầy đủ không? (5=rất chính xác)

CHỈ trả về JSON, không giải thích thêm:
{{"faithfulness": <int>, "relevance": <int>, "accuracy": <int>}}"""

ITINERARY_JUDGE_PROMPT = """Bạn là chuyên gia đánh giá chatbot lập lịch trình du lịch Đà Nẵng.

Câu hỏi:
{query}

Câu trả lời mẫu:
{gold}

Câu trả lời chatbot:
{answer}

Hãy chấm điểm từ 1–5 cho các tiêu chí:
- coherence: Thứ tự các hoạt động có logic và mạch lạc không?
- coverage: Lịch trình có bao quát đầy đủ các hoạt động cần thiết cho toàn bộ chuyến đi không?
- feasibility: Lịch trình có khả thi thực tế về thời gian, khoảng cách và khối lượng hoạt động không?
- personalization: Lịch trình có đáp ứng nhu cầu hoặc sở thích được nêu trong câu hỏi không?
- local_relevance: Có sử dụng các địa điểm, nhà hàng, khách sạn thực tế tại Đà Nẵng không?

Trả về DUY NHẤT JSON:
{{"coherence": <1-5>, "coverage": <1-5>, "feasibility": <1-5>, "personalization": <1-5>, "local_relevance": <1-5>}}"""


def is_available() -> bool:
    return bool(config.GEMINI_API_KEY)


def _parse_json(text: str) -> Optional[Dict]:
    text = re.sub(r"```json|```", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Judge trả về sai định dạng → bỏ điểm câu này; log preview để chẩn đoán.
        print(f"[metrics.judge] không parse được JSON từ judge: {text[:120]!r}")
        return None


async def _gemini_complete(prompt: str, max_tokens: int = 300) -> Optional[str]:
    if not config.GEMINI_API_KEY:
        return None
    stop_event = threading.Event()
    parts = []
    try:
        async for chunk in generate_gemini_streaming(
            [{"role": "user", "content": prompt}],
            stop_event,
            max_new_tokens=max_tokens,
            temperature=0.0,
        ):
            parts.append(chunk)
    except GeminiFallbackError as exc:
        # Judge tùy chọn — vẫn degrade về None, nhưng để dấu vết phân biệt "Gemini lỗi"
        # với "judge tắt" (cả hai đều trả None nên cột judge trống khó chẩn đoán).
        print(f"[metrics.judge] Gemini judge thất bại: {type(exc).__name__}: {exc}")
        return None
    return "".join(parts)


async def judge_general(query: str, gold: str, answer: str) -> Optional[Dict]:
    """Chấm faithfulness/relevance/accuracy (1–5). None nếu judge không khả dụng/parse lỗi."""
    raw = await _gemini_complete(
        GENERAL_JUDGE_PROMPT.format(query=query, gold=gold, answer=answer)
    )
    return _parse_json(raw) if raw else None


async def judge_itinerary(query: str, gold: str, answer: str) -> Optional[Dict]:
    """Chấm coherence/coverage/feasibility/personalization/local_relevance (1–5)."""
    raw = await _gemini_complete(
        ITINERARY_JUDGE_PROMPT.format(query=query, gold=gold, answer=answer)
    )
    return _parse_json(raw) if raw else None
