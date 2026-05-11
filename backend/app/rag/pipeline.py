from __future__ import annotations
import threading
from typing import AsyncIterator, Optional, List

from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer

from app import config
from app.rag.intent import QueryIntent
from app.rag.retrieval import retrieve_by_intent
from app.rag.rerank import rerank_results
from app.rag.llm import generate_streaming
from app.rag.memory import build_search_query, build_history_messages
from app.rag.schemas import SearchResultSchema
from app.utils.nfc import normalize_nfc

# Vietnamese few-shot examples to prevent English responses
_FEW_SHOT = """Ví dụ:
Câu hỏi: Gợi ý khách sạn 4 sao ở Sơn Trà?
Trả lời: Dựa trên thông tin hiện có, đây là một số khách sạn 4 sao ở Sơn Trà: 1. Sala Danang Beach Hotel - Đánh giá 9.4/10 (2,581 đánh giá), giá từ 500,000 VND. Khách sạn nằm gần biển, được khách hàng đánh giá rất cao.

Câu hỏi: Nhà hàng hải sản nào ngon ở Đà Nẵng?
Trả lời: Đà Nẵng có nhiều nhà hàng hải sản nổi tiếng. Dựa trên dữ liệu, tôi gợi ý: ..."""

_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng chuyên nghiệp. "
    "LUÔN trả lời bằng tiếng Việt. "
    "Trả lời ngắn gọn, chính xác, thân thiện."
)


def _format_context(results: List[SearchResultSchema]) -> str:
    if not results:
        return "Không có thông tin phù hợp với yêu cầu."
    parts = []
    for i, r in enumerate(results[:8], 1):
        lines = [f"[{i}] {r.get_display_name()}"]
        lines.append(f"   - Loại: {r.collection}")
        lines.append(f"   - Quận/Huyện: {r.district or 'Chưa có'}")
        lines.append(f"   - Đánh giá: {r.get_rating_display()}")
        lines.append(f"   - Giá: {r.get_price_display()}")
        lines.append(f"   - Địa chỉ: {r.get_address_display()}")
        if r.content:
            lines.append(f"   - Nội dung: {r.content[:300]}")
        if r.room_name:
            cap = f" (Sức chứa: {r.capacity} người)" if r.capacity else ""
            lines.append(f"   - Phòng: {r.room_name}{cap}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _build_messages(
    query: str,
    results: List[SearchResultSchema],
    history: list[dict],
) -> list[dict]:
    context = _format_context(results)
    empty_note = "" if results else "\nLưu ý: Không tìm thấy kết quả phù hợp. Hãy thông báo cho người dùng và gợi ý nới lỏng bộ lọc.\n"

    user_prompt = f"""{_FEW_SHOT}

### Câu hỏi:
{query}

### Thông tin tham khảo:
{context}{empty_note}

### Hướng dẫn:
1. Trả lời bằng tiếng Việt, trực tiếp và chính xác
2. Nếu có nhiều lựa chọn, đề xuất TOP 3 với rating và giá
3. Nếu không có kết quả, nói rõ và gợi ý nới lỏng bộ lọc
4. Không bịa thông tin ngoài dữ liệu đã cung cấp

### Trả lời:"""

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(build_history_messages(history))
    messages.append({"role": "user", "content": user_prompt})
    return messages


class RAGPipeline:
    def __init__(
        self,
        encoder: SentenceTransformer,
        model,
        tokenizer,
        qdrant_client: AsyncQdrantClient,
    ) -> None:
        self.encoder = encoder
        self.model = model
        self.tokenizer = tokenizer
        self.client = qdrant_client

    async def answer_stream(
        self,
        query: str,
        history: list[dict],
        filters: Optional[dict] = None,
        stop_event: Optional[threading.Event] = None,
        max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = config.DEFAULT_TEMPERATURE,
    ) -> AsyncIterator[dict]:
        """Yield SSE-ready event dicts: intent → sources → token* → done."""
        if stop_event is None:
            stop_event = threading.Event()

        q = normalize_nfc(query)

        # 1. Build context-aware search query
        search_q = build_search_query(history, q)
        # Detect intent from the raw user query to avoid context terms
        # (e.g. previous "... Hotel") overriding the current intent.
        intent = QueryIntent.detect(q)
        yield {"type": "intent", "value": intent.value, "display": intent.display}

        # 2. Retrieve
        results = await retrieve_by_intent(
            query=search_q,
            client=self.client,
            encoder=self.encoder,
            intent=intent,
            top_k_per_collection=config.DEFAULT_TOP_K,
            filters=filters,
            score_threshold=config.SCORE_THRESHOLD,
        )
        results = rerank_results(results, search_q, intent)

        sources = [r.to_dict() for r in results[:10]]
        yield {"type": "sources", "items": sources, "total": len(sources)}

        # 3. Build prompt and stream
        messages = _build_messages(q, results, history)

        async for token in generate_streaming(
            messages,
            self.model,
            self.tokenizer,
            stop_event,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        ):
            yield {"type": "token", "text": token}

        yield {"type": "done"}

    async def warmup(self) -> None:
        """Run one dummy query to pre-load GPU kernels and CUDA cache."""
        stop = threading.Event()
        async for _ in self.answer_stream("test", [], stop_event=stop, max_new_tokens=5):
            pass
