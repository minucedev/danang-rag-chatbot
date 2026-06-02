from __future__ import annotations
import asyncio
import threading
import time
from typing import AsyncIterator, Optional, List

from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer
from app.rag.llm import QwenHF

from app import config
from app.rag.intent import QueryIntent
from app.rag.analyzer import LLMQueryAnalyzer
from app.rag.retrieval import retrieve_by_intent, exact_name_search
from app.rag.rerank import rerank_results
from app.rag.llm import generate_streaming
from app.rag.gemini_fallback import generate_gemini_streaming, GeminiFallbackError
from app.rag.memory import build_search_query, build_history_messages, extract_session_prefs, merge_session_prefs
from app.db.sessions import get_session_context, upsert_session_context
from app.rag.schemas import SearchResultSchema
from app.rag.events_retrieval import retrieve_events, format_events_context
from app.utils.nfc import normalize_nfc
from app.db.missed_queries import log_missed_query

# Intents có thể crawl được địa điểm thực tế — log khi miss
_CRAWLABLE_INTENTS = {
    QueryIntent.HOTEL_SEARCH,
    QueryIntent.RESTAURANT_SEARCH,
    QueryIntent.PLACE_SEARCH,
    QueryIntent.SPECIFIC_SEARCH,
}

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

_CHITCHAT_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng thân thiện. LUÔN trả lời bằng tiếng Việt.\n"
    "Với câu hỏi chung về bản thân: giới thiệu bạn là AI hỗ trợ du lịch Đà Nẵng, "
    "có thể giúp tìm khách sạn, nhà hàng, địa điểm tham quan và sự kiện.\n"
    "Với câu hỏi ngoài phạm vi (thời tiết, vé máy bay, ...): trả lời thân thiện và "
    "hướng dẫn người dùng hỏi về du lịch Đà Nẵng."
)

_ITINERARY_RULES = (
    "Hãy lập lịch trình theo từng ngày (Ngày 1, Ngày 2, ...). "
    "Mỗi ngày gợi ý: buổi sáng (địa điểm tham quan), trưa (nhà hàng), "
    "chiều (địa điểm hoặc hoạt động), tối (nhà hàng/giải trí), khách sạn (nếu phù hợp). "
    "Chỉ dùng thông tin từ dữ liệu tham khảo. Ghi kèm đánh giá và địa chỉ cho mỗi gợi ý."
)

# Prompt rút gọn cho nhánh Gemini fallback: không có "Reference data" nên không
# gò bám tham chiếu — chỉ cảnh báo đừng bịa thông tin cụ thể.
_GEMINI_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng. LUÔN trả lời bằng tiếng Việt, ngắn gọn, thân thiện.\n"
    "Trả lời dựa trên hiểu biết tổng quát của bạn về Đà Nẵng và Việt Nam.\n"
    "QUAN TRỌNG: Nếu không chắc chắn về một thông tin cụ thể (giá phòng, giờ mở cửa, "
    "địa chỉ chính xác), HÃY NÓI RÕ bạn không chắc thay vì bịa số liệu."
)


# Disclaimer prefix khi trả lời từ kiến thức chung của Gemini (không có dữ liệu nội bộ).
_NO_DATA_DISCLAIMER = (
    "_(Chưa có dữ liệu nội bộ cho mục này — đây là gợi ý tổng quát từ AI, "
    "vui lòng kiểm chứng thông tin chi tiết.)_\n\n"
)


def _build_gemini_messages(
    query: str,
    history: list[dict],
    intent: QueryIntent,
) -> list[dict]:
    messages = [{"role": "system", "content": _GEMINI_SYSTEM_PROMPT}]
    messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
    messages.append({"role": "user", "content": query})
    return messages


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


def _merge_filters(fe: Optional[dict], llm: dict) -> dict:
    """FE sidebar thắng theo từng field; analyzer chỉ điền field FE bỏ trống.

    `max_price` lấy min() của 2 nguồn (ngân sách chặt nhất) — không hồi quy ca
    sidebar-budget. FE là hành động tường minh; analyzer là suy luận có thể sai.
    Chỉ set key có giá trị → `_build_filter` truth-test không đổi hành vi.
    """
    fe = fe or {}
    merged: dict = {}
    for key in ("district", "min_rating", "max_price", "min_price"):
        fv = fe.get(key)
        lv = llm.get(key)
        if key == "max_price" and fv is not None and lv is not None:
            merged[key] = min(float(fv), float(lv))
        elif fv is not None:
            merged[key] = fv
        elif lv is not None:
            merged[key] = lv
    return merged


def _dedup_by_display_name(
    results: List[SearchResultSchema],
) -> List[SearchResultSchema]:
    """Gộp thực thể trùng tên: giữ bản đầu; nếu bản đang giữ thiếu `min_price`
    mà bản trùng có thì thay."""
    deduped: List[SearchResultSchema] = []
    seen: dict[str, int] = {}
    for r in results:
        key = r.get_display_name().lower().strip()
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(r)
        else:
            idx = seen[key]
            if not deduped[idx].min_price and r.min_price:
                deduped[idx] = r
    return deduped


def _build_event_messages(
    query: str,
    events: list[dict],
    history: list[dict],
) -> list[dict]:
    context = format_events_context(events)
    empty_note = "" if events else "\nLưu ý: Không tìm thấy sự kiện nào trong thời gian này.\n"
    user_prompt = f"""### Câu hỏi:
{query}

### Sự kiện đang diễn ra / sắp diễn ra tại Đà Nẵng:
{context}{empty_note}

### QUY TẮC:
1. Chỉ trả lời dựa trên danh sách sự kiện trên. Không tự sáng tạo sự kiện.
2. Trả lời ngắn gọn, thân thiện, bằng tiếng Việt.
3. Nếu không có sự kiện phù hợp, thông báo lịch sự và gợi ý người dùng hỏi lại sau.

### Trả lời:"""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _build_messages(
    query: str,
    results: List[SearchResultSchema],
    history: list[dict],
    intent: QueryIntent,
) -> list[dict]:
    context = _format_context(results)
    empty_note = "" if results else "\nLưu ý: Không tìm thấy kết quả phù hợp. Hãy thông báo cho người dùng và gợi ý nới lỏng bộ lọc.\n"

    if intent == QueryIntent.SPECIFIC_SEARCH:
        rules = """### QUY TẮC BẮT BUỘC KHI TRẢ LỜI (TUÂN THỦ TUYỆT ĐỐI):
1. TRẢ LỜI ĐÚNG TRỌNG TÂM: Chỉ tập trung cung cấp đầy đủ thông tin (Địa chỉ, Đánh giá, Giá cả, Mô tả) của ĐÚNG địa điểm/khách sạn/nhà hàng được yêu cầu trong câu hỏi.
2. TUYỆT ĐỐI KHÔNG GỢI Ý LUNG TUNG: Không liệt kê thêm các khách sạn/nhà hàng đối thủ khác mang tính chất so sánh hay đề xuất danh sách "Top 3". Người dùng chỉ cần thông tin của địa điểm họ hỏi.
3. KHÔNG ẢO GIÁC: Chỉ dùng thông tin trong mục "Thông tin tham khảo". Không tự bịa ra thông tin nằm ngoài ngữ cảnh.
4. XỬ LÝ KHI TRỐNG DỮ LIỆU: Nếu mục "Thông tin tham khảo" trống, hãy trả lời lịch sự: "Hiện hệ thống không tìm thấy thông tin của [tên địa điểm] trong cơ sở dữ liệu." """
    elif intent == QueryIntent.ITINERARY_SEARCH:
        rules = f"""### QUY TẮC BẮT BUỘC KHI TRẢ LỜI (TUÂN THỦ TUYỆT ĐỐI):
{_ITINERARY_RULES}
KHÔNG ẢO GIÁC — chỉ dùng địa điểm/nhà hàng/khách sạn có trong dữ liệu tham khảo."""
    else:
        rules = """### QUY TẮC BẮT BUỘC KHI TRẢ LỜI (TUÂN THỦ TUYỆT ĐỐI):
1. KHÔNG ẢO GIÁC: Chỉ được sử dụng thông tin được cung cấp trong mục "Thông tin tham khảo". KHÔNG TỰ Ý BỊA RA tên địa điểm, giá cả hoặc địa chỉ nằm ngoài ngữ cảnh trên.
2. XỬ LÝ KHI THIẾU THÔNG TIN: Nếu mục "Thông tin tham khảo" bị trống hoặc ghi "KHÔNG CÓ DỮ LIỆU PHÙ HỢP", hãy trả lời lịch sự rằng: "Hiện tại hệ thống không tìm thấy kết quả nào thỏa mãn chính xác các tiêu chí của bạn trong cơ sở dữ liệu." Tuyệt đối không tự suy diễn thông tin bên ngoài.
3. ĐỀ XUẤT PHÙ HỢP: Nếu dữ liệu có sẵn, hãy đề xuất tối đa TOP 3 lựa chọn phù hợp nhất, kèm theo Đánh giá (Rating), Giá cả và Địa chỉ rõ ràng.
4. Giữ phong thái chuyên nghiệp, thân thiện và phản hồi hoàn toàn bằng tiếng Việt."""

    user_prompt = f"""{_FEW_SHOT}

### Câu hỏi:
{query}

### Thông tin tham khảo:
{context}{empty_note}

{rules}

### Trả lời:"""

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
    messages.append({"role": "user", "content": user_prompt})
    return messages


class RAGPipeline:
    def __init__(
        self,
        encoder: SentenceTransformer,
        llm: QwenHF,
        qdrant_client: AsyncQdrantClient,
        reranker=None,
        analyzer_llm=None,
    ) -> None:
        self.encoder = encoder
        self.llm = llm
        self.client = qdrant_client
        self.reranker = reranker
        self.analyzer = LLMQueryAnalyzer(analyzer_llm or llm)

    async def answer_stream(
        self,
        query: str,
        history: list[dict],
        filters: Optional[dict] = None,
        stop_event: Optional[threading.Event] = None,
        max_new_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = config.DEFAULT_TEMPERATURE,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Yield SSE-ready event dicts: intent → sources → token* → done."""
        if stop_event is None:
            stop_event = threading.Event()

        # [TIMING] instrumentation — tạm thời, sẽ xóa sau khi xong tối ưu
        t_start = time.perf_counter()

        q = normalize_nfc(query)

        # 1. Enrich query với lịch sử TRƯỚC (giữ multi-turn), rồi đưa vào
        #    LLMQueryAnalyzer. Analyzer là 1 lượt generate blocking — chạy qua
        #    run_in_executor để event loop rảnh cho disconnect-check + SSE ping.
        search_q = build_search_query(history, q)
        t_history = time.perf_counter()
        print(f"[TIMING] history_enrich: {(t_history - t_start)*1000:.0f}ms")

        loop = asyncio.get_running_loop()
        analysis = await loop.run_in_executor(None, self.analyzer.analyze, search_q)
        t_analyzer = time.perf_counter()
        print(f"[TIMING] analyzer: {(t_analyzer - t_history)*1000:.0f}ms "
              f"(source={analysis['source']}, intent={analysis['intent'].value})")

        intent = analysis["intent"]
        rewritten = analysis["rewritten_query"]
        yield {"type": "intent", "value": intent.value, "display": intent.display}

        # Load session context một lần, cập nhật nếu có preference mới, rồi dùng cho filter merge
        session_ctx: Optional[dict] = None
        if session_id:
            session_ctx = await get_session_context(session_id) or {}
            prefs = extract_session_prefs(analysis)
            if prefs:
                session_ctx = {**session_ctx, **prefs}
                await upsert_session_context(session_id, session_ctx)

        # Chitchat: không cần RAG, trả lời trực tiếp từ LLM
        if intent == QueryIntent.CHITCHAT:
            yield {"type": "sources", "items": [], "total": 0}
            chitchat_messages = [{"role": "system", "content": _CHITCHAT_SYSTEM_PROMPT}]
            chitchat_messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
            chitchat_messages.append({"role": "user", "content": q})
            async for token in generate_streaming(
                chitchat_messages, self.llm, stop_event,
                max_new_tokens=max_new_tokens, temperature=temperature,
            ):
                yield {"type": "token", "text": token}
            yield {"type": "done"}
            return

        # Event search: bypass Qdrant, query SQLite events rồi stream trực tiếp.
        if intent == QueryIntent.EVENT_SEARCH:
            district = (analysis["filters"].get("district") or "").strip() or None
            try:
                events = await retrieve_events(district=district)
            except Exception as exc:
                print(f"[pipeline] events retrieval failed: {type(exc).__name__}: {exc}")
                events = []
            sources = events[:10]
            yield {"type": "sources", "items": sources, "total": len(sources)}
            messages = _build_event_messages(q, events, history)
            t_before_gen = time.perf_counter()
            first_token_logged = False
            token_count = 0
            async for token in generate_streaming(
                messages, self.llm, stop_event,
                max_new_tokens=max_new_tokens, temperature=temperature,
            ):
                if not first_token_logged:
                    t_first = time.perf_counter()
                    print(f"[TIMING] event_prefill+first_token: {(t_first - t_before_gen)*1000:.0f}ms")
                    first_token_logged = True
                token_count += 1
                yield {"type": "token", "text": token}
            print(f"[TIMING] event_generation: {token_count} tokens")
            yield {"type": "done"}
            return

        # 2. Trộn filter: FE sidebar thắng, analyzer điền field trống, session context fill còn lại
        merged = _merge_filters(filters, analysis["filters"])
        merged = merge_session_prefs(session_ctx, merged)

        # 3. Retrieve bằng rewritten_query với top_k cao hơn để reranker có đủ candidates
        t_retrieve_start = time.perf_counter()
        results = await retrieve_by_intent(
            query=rewritten,
            client=self.client,
            encoder=self.encoder,
            intent=intent,
            top_k_per_collection=config.TOP_K_RETRIEVE,
            filters=merged,
            score_threshold=config.SCORE_THRESHOLD,
        )
        t_retrieve = time.perf_counter()
        print(f"[TIMING] retrieve_total: {(t_retrieve - t_retrieve_start)*1000:.0f}ms "
              f"({len(results)} hits)")

        # 4. BGE reranker → dedup
        t_rerank_start = time.perf_counter()
        if results and self.reranker is not None:
            results = await rerank_results(
                results, rewritten, self.reranker,
                top_k=config.TOP_K_RERANK,
                score_threshold=config.RERANK_SCORE_THRESHOLD,
                intent=intent,
            )
        results = _dedup_by_display_name(results)
        t_rerank = time.perf_counter()
        print(f"[TIMING] rerank+dedup: {(t_rerank - t_rerank_start)*1000:.0f}ms "
              f"(-> {len(results)} after dedup)")

        # 4.5. Exact name fallback cho SPECIFIC_SEARCH khi không có kết quả
        if not results and intent == QueryIntent.SPECIFIC_SEARCH:
            raw_fallback = await exact_name_search(rewritten, self.client)
            results = _dedup_by_display_name(raw_fallback)
            if results:
                print(f"[pipeline] exact_name_search found {len(results)} fallback results")

        sources = [r.to_dict() for r in results[:10]]
        yield {"type": "sources", "items": sources, "total": len(sources)}

        # 4.6. Log missed query nếu không có kết quả và là intent crawlable
        if not results and intent in _CRAWLABLE_INTENTS:
            try:
                await log_missed_query(q, rewritten, intent.value, session_id)
            except Exception as _log_exc:
                print(f"[pipeline] log_missed_query failed: {type(_log_exc).__name__}: {_log_exc}")

        # 3.5. Fallback sang Gemini khi retrieve trả 0 kết quả (chỉ khi không dùng Gemini primary).
        # Khi USE_GEMINI_GENERATION=True, path này bị skip — Gemini primary xử lý luôn cả no-results.
        if not results and config.GEMINI_API_KEY and not config.USE_GEMINI_GENERATION:
            gemini_messages = _build_gemini_messages(q, history, intent)
            committed_to_gemini = False
            gemini_tokens = 0
            t_gemini_start = time.perf_counter()
            try:
                async for tok in generate_gemini_streaming(
                    gemini_messages,
                    stop_event,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                ):
                    if stop_event.is_set():
                        break
                    if not committed_to_gemini:
                        # Chunk đầu OK → giờ mới cam kết: phát fallback event + disclaimer.
                        yield {
                            "type": "fallback",
                            "reason": "no_results",
                            "provider": "gemini",
                            "model": config.GEMINI_MODEL,
                        }
                        if config.GEMINI_FALLBACK_PREFIX_DISCLAIMER:
                            yield {
                                "type": "token",
                                "text": "_(Trả lời từ AI tổng quát — không có dữ liệu nội bộ phù hợp.)_\n\n",
                            }
                        committed_to_gemini = True
                    gemini_tokens += 1
                    yield {"type": "token", "text": tok}

                if committed_to_gemini:
                    t_gemini_done = time.perf_counter()
                    print(
                        f"[TIMING] gemini_fallback: {(t_gemini_done - t_gemini_start)*1000:.0f}ms "
                        f"({gemini_tokens} chunks)"
                    )
                    yield {"type": "done"}
                    return
                # else: stream rỗng + chưa committed → rơi xuống local LLM bên dưới
                #       (nhánh _yielded_any guard trong gemini_fallback.py thường đã raise
                #       trước khi tới đây, nhưng giữ an toàn cho mọi đường thoát).
            except GeminiFallbackError as e:
                status = f" status={e.status_code}" if e.status_code is not None else ""
                print(f"[gemini-fallback] failed{status}: {type(e).__name__}: {e}")
                if committed_to_gemini:
                    # Đã ship token Gemini cho client → KHÔNG trộn Qwen vào. Báo lỗi
                    # rồi đóng stream; frontend sẽ thấy disclaimer + tokens đã nhận +
                    # error + done. `fallback_used` ở chat.py giữ True → intent lưu
                    # là "gemini_fallback" (đúng: nội dung từ Gemini, dù dở dang).
                    yield {"type": "error", "message": "Gemini bị gián đoạn giữa chừng."}
                    yield {"type": "done"}
                    return
                # Chưa committed → client chưa thấy gì về Gemini, fall through im lặng.

        # 4. Build prompt (hiển thị q gốc cho UX) — rẽ nhánh theo intent
        messages = _build_messages(q, results, history, intent)
        prompt_chars = sum(len(m["content"]) for m in messages)
        print(f"[TIMING] prompt_built: {prompt_chars} chars across {len(messages)} msgs")

        t_before_gen = time.perf_counter()
        first_token_logged = False
        token_count = 0

        # 4.1. Gemini primary generator (nhanh hơn local LLM ~5-10x)
        if config.USE_GEMINI_GENERATION:
            # Không có dữ liệu nội bộ → để Gemini trả lời từ kiến thức chung (kèm disclaimer)
            # thay vì bám reference rỗng rồi báo "không tìm thấy". Missed query vẫn được log
            # ở trên để crawler bổ sung địa điểm thật sau.
            gen_messages = messages if results else _build_gemini_messages(q, history, intent)
            # Disclaimer chỉ phát khi Gemini thực sự ra token đầu tiên — tránh trùng/mâu
            # thuẫn với disclaimer ở nhánh Gemini fail-trước-token bên dưới.
            disclaimer_pending = (not results and config.GEMINI_FALLBACK_PREFIX_DISCLAIMER)
            gemini_tokens_yielded = 0
            try:
                async for token in generate_gemini_streaming(
                    gen_messages, stop_event,
                    max_new_tokens=max_new_tokens, temperature=temperature,
                ):
                    if not first_token_logged:
                        t_first = time.perf_counter()
                        print(f"[TIMING] prefill+first_token (Gemini): {(t_first - t_before_gen)*1000:.0f}ms")
                        print(f"[TIMING] >>> TTFT: {(t_first - t_start)*1000:.0f}ms")
                        first_token_logged = True
                    if disclaimer_pending:
                        yield {"type": "token", "text": _NO_DATA_DISCLAIMER}
                        disclaimer_pending = False
                    token_count += 1
                    gemini_tokens_yielded += 1
                    yield {"type": "token", "text": token}
                t_done = time.perf_counter()
                print(f"[TIMING] generation (Gemini): {(t_done - t_before_gen)*1000:.0f}ms "
                      f"({token_count} chunks)")
                print(f"[TIMING] === TOTAL: {(t_done - t_start)*1000:.0f}ms ===")
                yield {"type": "done"}
                return
            except GeminiFallbackError as e:
                status = f" status={e.status_code}" if e.status_code is not None else ""
                if gemini_tokens_yielded > 0:
                    # Đã gửi token cho client — không thể trộn local LLM vào
                    print(f"[pipeline] Gemini primary failed mid-stream "
                          f"after {gemini_tokens_yielded} tokens{status}: {e}")
                    yield {"type": "error", "message": "Kết nối Gemini bị gián đoạn giữa chừng."}
                    yield {"type": "done"}
                    return
                print(f"[pipeline] Gemini primary failed before first token{status}: {e} "
                      f"— falling back to local LLM")
                # Thêm disclaimer khi không có kết quả Qdrant và Gemini thất bại
                if not results:
                    yield {"type": "token",
                           "text": "_(Không có dữ liệu nội bộ phù hợp và dịch vụ AI tổng quát không khả dụng.)_\n\n"}
                first_token_logged = False
                token_count = 0
                t_before_gen = time.perf_counter()

        # 4.2. Local LLM generation (primary khi Gemini không configured, hoặc fallback)
        async for token in generate_streaming(
            messages,
            self.llm,
            stop_event,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        ):
            if not first_token_logged:
                t_first = time.perf_counter()
                print(f"[TIMING] prefill+first_token: {(t_first - t_before_gen)*1000:.0f}ms")
                print(f"[TIMING] >>> TTFT (total to first token): {(t_first - t_start)*1000:.0f}ms")
                first_token_logged = True
            token_count += 1
            yield {"type": "token", "text": token}

        t_done = time.perf_counter()
        gen_dur = t_done - t_before_gen
        tok_per_s = token_count / gen_dur if gen_dur > 0 else 0
        print(f"[TIMING] generation: {gen_dur*1000:.0f}ms "
              f"({token_count} tokens, {tok_per_s:.1f} tok/s)")
        print(f"[TIMING] === TOTAL: {(t_done - t_start)*1000:.0f}ms ===")

        yield {"type": "done"}

    async def warmup(self) -> None:
        """Run one dummy hotel query để buộc encoder + reranker warmup (tránh CHITCHAT path)."""
        stop = threading.Event()
        async for _ in self.answer_stream(
            "khách sạn Đà Nẵng", [], stop_event=stop, max_new_tokens=5
        ):
            pass
