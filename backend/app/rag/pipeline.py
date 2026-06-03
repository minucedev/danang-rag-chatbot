from __future__ import annotations
import asyncio
import re
import threading
import time
from typing import AsyncIterator, Optional, List
from difflib import SequenceMatcher

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
from app.utils.slugify_vn import slugify_vn

# Intents có thể crawl được địa điểm thực tế — log khi miss
_CRAWLABLE_INTENTS = {
    QueryIntent.HOTEL_SEARCH,
    QueryIntent.RESTAURANT_SEARCH,
    QueryIntent.PLACE_SEARCH,
    QueryIntent.SPECIFIC_SEARCH,
}

_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng thông minh, nhiệt tình và am hiểu địa phương.\n"
    "Nhiệm vụ: Trả lời câu hỏi của khách du lịch dựa trên thông tin được cung cấp.\n\n"
    "Nguyên tắc bắt buộc:\n"
    "1. TUYỆT ĐỐI KHÔNG được sử dụng các cụm từ kỹ thuật như \"dựa trên context\", \"trong context\", \"theo context cung cấp\", \"dữ liệu đã cho\", \"hệ thống\", \"cơ sở dữ liệu\", \"CONTEXT\", \"thông tin trong CONTEXT\", v.v. Hãy nói chuyện tự nhiên như một hướng dẫn viên bản địa thực thụ đang chia sẻ từ kiến thức và trải nghiệm cá nhân.\n"
    "2. Chỉ dùng các thông tin có thật về địa chỉ, giá cả, đánh giá từ mô tả địa điểm. KHÔNG bịa đặt hay suy diễn thêm.\n"
    "3. Nếu không đủ thông tin để trả lời, hãy thân thiện cho khách biết và gợi ý lựa chọn thay thế.\n"
    "4. Trả lời bằng tiếng Việt, tự nhiên, hào hứng, hiếu khách.\n"
    "5. Định dạng rõ ràng: dùng gạch đầu dòng hoặc đánh số khi liệt kê nhiều địa điểm. Với mỗi gợi ý: tên, địa chỉ (nếu có), giá tham khảo (nếu có), điểm nổi bật.\n"
    "6. Với câu hỏi lịch trình (itinerary), chia theo ngày rõ ràng.\n"
    "7. KHÔNG đề xuất địa điểm ngoài Đà Nẵng trừ khi được yêu cầu."
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


def _get_field(r: SearchResultSchema, name: str) -> Optional[Any]:
    val = getattr(r, name, None)
    if val is None and r.model_extra:
        val = r.model_extra.get(name)
    if val == "None" or val == "null" or val == "":
        return None
    return val


def _clean_repeated_phrases(text: str) -> str:
    if not text:
        return ""
    # Normalize whitespaces
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()
    n = len(words)
    if n < 4:
        return text

    l = n // 2
    while l >= 2:
        i = 0
        while i <= n - 2 * l:
            chunk1 = words[i:i+l]
            chunk2 = words[i+l:i+2*l]
            if chunk1 == chunk2:
                del words[i+l:i+2*l]
                n = len(words)
                continue
            i += 1
        l -= 1
    return " ".join(words)


def _format_context(results: List[SearchResultSchema]) -> str:
    if not results:
        return "Không có thông tin phù hợp với yêu cầu."
    parts = []
    for i, r in enumerate(results[:12], 1):
        col_type = "Địa điểm"
        is_hotel = "hotel" in r.collection or "accommodation" in r.collection
        is_room = "room" in r.collection
        is_restaurant = "restaurant" in r.collection

        if is_hotel:
            col_type = "Khách sạn"
        elif is_room:
            col_type = "Thông tin phòng"
        elif is_restaurant:
            col_type = "Nhà hàng/Quán ăn"

        lines = [f"[{i}] {r.get_display_name()} ({col_type})"]
        
        # General Fields
        district = _get_field(r, "district")
        if district:
            lines.append(f"   Quận: {district}")

        addr = r.get_address_display()
        if addr and addr != "Chưa có" and addr != "Chưa có địa chỉ":
            lines.append(f"   Địa chỉ: {addr}")
            
        rating = r.get_rating_display()
        if rating and rating != "Chưa có" and rating != "Chưa có đánh giá":
            lines.append(f"   Đánh giá: {rating}")
            
        price = r.get_price_display()
        if price and price != "Không có thông tin giá":
            lines.append(f"   Mức giá: {price}")
            
        # Hotel / Accommodation fields
        if is_hotel or is_room:
            star = _get_field(r, "star_rating")
            if star:
                lines.append(f"   Hạng sao: {star} sao")
            ci = _get_field(r, "check_in_time")
            co = _get_field(r, "check_out_time")
            if ci or co:
                lines.append(f"   Thời gian nhận/trả phòng: Nhận từ {ci or '14:00'}, Trả trước {co or '12:00'}")
            cancel = _get_field(r, "cancellation_policy")
            if cancel:
                lines.append(f"   Chính sách hủy phòng: {_clean_repeated_phrases(cancel)}")
            children = _get_field(r, "children_policy")
            if children:
                lines.append(f"   Chính sách trẻ em: {_clean_repeated_phrases(children)}")

        # Room specific fields
        if is_room:
            room = _get_field(r, "room_name")
            cap = _get_field(r, "capacity")
            bed = _get_field(r, "bed_type")
            area = _get_field(r, "area_m2")
            view = _get_field(r, "room_view")
            
            room_info = []
            if room: room_info.append(f"Tên phòng: {room}")
            if cap: room_info.append(f"Sức chứa: {cap} người")
            if bed: room_info.append(f"Loại giường: {bed}")
            if area: room_info.append(f"Diện tích: {area} m²")
            if view: room_info.append(f"Hướng nhìn: {view}")
            if room_info:
                lines.append(f"   Chi tiết phòng: {', '.join(room_info)}")

        # Restaurant specific fields
        if is_restaurant:
            cuisine = _get_field(r, "cuisine")
            rest_type = _get_field(r, "restaurant_type")
            if cuisine:
                lines.append(f"   Ẩm thực: {cuisine}")
            if rest_type:
                lines.append(f"   Loại hình: {rest_type}")
            
            t_open = _get_field(r, "time_open")
            t_close = _get_field(r, "time_close")
            if t_open or t_close:
                lines.append(f"   Giờ mở cửa: {t_open or 'Đang cập nhật'} - {t_close or 'Đang cập nhật'}")
                
            price_avg = _get_field(r, "price_avg_vnd")
            if price_avg is not None:
                lines.append(f"   Giá trung bình: {price_avg:,.0f} VND")
                
            scores = []
            for name, label in [
                ("quality_score", "Chất lượng"),
                ("service_score", "Phục vụ"),
                ("space_score", "Không gian"),
                ("location_score", "Vị trí")
            ]:
                val = _get_field(r, name)
                if val is not None:
                    scores.append(f"{label}: {val}/10")
            if scores:
                lines.append(f"   Điểm đánh giá chi tiết: {', '.join(scores)}")

        # Place specific fields
        is_place = not is_hotel and not is_room and not is_restaurant
        if is_place:
            cat = _get_field(r, "category")
            if cat:
                lines.append(f"   Danh mục: {cat}")
            suitable = _get_field(r, "suitable_for")
            if suitable:
                if isinstance(suitable, list):
                    suitable = ", ".join(suitable)
                lines.append(f"   Phù hợp: {suitable}")
            best_time = _get_field(r, "best_time_to_visit")
            if best_time:
                if isinstance(best_time, list):
                    best_time = ", ".join(best_time)
                lines.append(f"   Thời điểm đẹp nhất: {best_time}")
            duration = _get_field(r, "visit_duration")
            if duration:
                if isinstance(duration, list):
                    duration = ", ".join(duration)
                lines.append(f"   Thời lượng dự kiến: {duration}")
            weather = _get_field(r, "weather_dependent")
            if weather:
                lines.append(f"   Phụ thuộc thời tiết: {weather}")

        tags = _get_field(r, "tags")
        if tags:
            if isinstance(tags, list):
                tags = ", ".join(tags)
            lines.append(f"   Đặc điểm nổi bật: {tags}")

        # Content/Description
        if r.content:
            lines.append(f"   Mô tả: {_clean_repeated_phrases(r.content)[:600]}")
            
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
        rules = """Hướng dẫn trả lời:
- Bạn phải trả lời về đúng địa điểm được hỏi. Giữ nguyên tên gốc của địa điểm (ví dụ: "Hải Sản Năm Đảnh", "Mangata Beachfront Hotel"), không viết sai tên.
- Cung cấp đầy đủ địa chỉ, đánh giá, mức giá và mô tả của đúng địa điểm đó.
- Không tự ý bịa đặt thông tin nằm ngoài mục "Thông tin tham khảo".
- Nếu không có thông tin trong mục tham khảo, hãy báo thân thiện là chưa có dữ liệu cho địa điểm này."""
    elif intent == QueryIntent.ITINERARY_SEARCH:
        rules = """Hướng dẫn lập lịch trình chi tiết:
- Chia lịch trình theo từng ngày rõ ràng (dùng markdown header như: ### **Ngày 1: [Tiêu đề hành trình ngắn]**).
- Trong mỗi ngày, phân chia mốc thời gian chi tiết: Sáng, Trưa, Chiều, Tối và gợi ý Nơi lưu trú phù hợp vào cuối ngày.
- Đối với mỗi điểm tham quan, ăn uống hoặc lưu trú được đề xuất, bạn hãy trình bày theo cấu trúc sau:
  *   **Sáng/Trưa/Chiều/Tối: [Tên địa điểm]**
      - **Địa điểm:** [Ghi rõ địa chỉ và đánh giá/số sao của địa điểm từ thông tin tham khảo]
      - **Lý do:** [Giải thích tại sao nhóm nên đi địa điểm này dựa trên các nhãn đặc điểm nổi bật (tags), điểm đánh giá chất lượng/phục vụ/không gian, hoặc mô tả của địa điểm]
      - **Thời gian:** [Đề xuất thời gian ghé thăm thích hợp và thời lượng dự kiến]
      - **Chi phí:** [Ước lượng chi phí dựa trên mức giá tham khảo trong dữ liệu]
      - **Lưu ý:** [Nếu địa điểm có nhãn phụ thuộc thời tiết hoặc cần lưu ý gì khác, hãy ghi rõ]
- Không lặp đi lặp lại một địa điểm (khách sạn/nhà hàng) liên tục nhiều ngày một cách rập khuôn nếu trong dữ liệu tham khảo có các địa điểm thay thế khác phù hợp hơn. Hãy luân chuyển đa dạng các địa điểm để lịch trình phong phú và hấp dẫn.
- Giọng điệu tự nhiên, hào hứng như một hướng dẫn viên bản địa thực thụ đang chia sẻ cẩm nang du lịch cho nhóm bạn."""
    else:
        rules = """Hướng dẫn trả lời:
- Gợi ý từ 1 đến 3 địa điểm tốt nhất từ dữ liệu tham khảo thỏa mãn yêu cầu của người dùng.
- Với mỗi địa điểm, ghi rõ: tên, địa chỉ, đánh giá và mức giá tham khảo.
- Nếu không có dữ liệu phù hợp, hãy thông báo lịch sự là hệ thống chưa tìm thấy kết quả phù hợp."""

    user_prompt = f"""### Câu hỏi:
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

    async def _extract_specific_entity_name(self, query: str) -> str:
        messages = [
            {"role": "system", "content": "Bạn là trợ lý trích xuất tên thực thể (địa điểm du lịch, khách sạn, resort, nhà hàng, quán ăn, món ăn) từ câu hỏi của khách du lịch Đà Nẵng.\nHãy trích xuất tên chính xác của thực thể được nhắc đến trong câu hỏi.\nLưu ý:\n- Chỉ trả về tên thực thể duy nhất, không thêm bất kỳ từ ngữ nào khác, không dùng markdown, không giải thích.\n- Nếu không tìm thấy tên thực thể cụ thể nào, hãy trả về rỗng \"\".\n\nVí dụ:\nInput: \"Khách sạn Novotel Đà Nẵng có tốt không?\"\nOutput: Novotel Đà Nẵng\n\nInput: \"Bà Nà Hills có gì vui?\"\nOutput: Bà Nà Hills\n\nInput: \"Địa chỉ của quán Hải sản Năm Đảnh ở đâu?\"\nOutput: Hải sản Năm Đảnh"},
            {"role": "user", "content": query}
        ]
        loop = asyncio.get_running_loop()
        
        def _call():
            res = self.analyzer.llm.create_chat_completion(
                messages=messages,
                max_tokens=50,
                temperature=0.0,
                stream=False
            )
            return res["choices"][0]["message"]["content"]
            
        try:
            raw = await loop.run_in_executor(None, _call)
            cleaned = raw.strip()
            cleaned = re.sub(r'^["\'\`“‘]|[”’"\'\`]$', '', cleaned).strip()
            return cleaned
        except Exception as e:
            print(f"[pipeline] _extract_specific_entity_name failed: {e}")
            return ""

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

        # Specific search routing
        if intent == QueryIntent.SPECIFIC_SEARCH:
            from app.rag.memory import needs_context
            if needs_context(q):
                entity_name = rewritten if rewritten else q
            else:
                entity_name = await self._extract_specific_entity_name(q)
                if not entity_name:
                    entity_name = rewritten if rewritten else q

            print(f"[pipeline] specific search flow for entity: {entity_name}")
            
            # Step 1: Query vector search with entity_name and empty filters
            raw_results = await retrieve_by_intent(
                query=entity_name,
                client=self.client,
                encoder=self.encoder,
                intent=intent,
                top_k_per_collection=config.TOP_K_RETRIEVE,
                filters={},  # Empty filters!
                score_threshold=config.SCORE_THRESHOLD,
            )

            # Step 2: Rerank results
            if raw_results and self.reranker is not None:
                raw_results = await rerank_results(
                    raw_results, entity_name, self.reranker,
                    top_k=config.TOP_K_RERANK,
                    score_threshold=config.RERANK_SCORE_THRESHOLD,
                    intent=intent,
                )
            raw_results = _dedup_by_display_name(raw_results)

            # Find exact matches
            exact_matches = []
            entity_name_slug = slugify_vn(entity_name).replace("-", " ").strip().lower()
            for r in raw_results:
                disp_name_slug = slugify_vn(r.get_display_name()).replace("-", " ").strip().lower()
                if entity_name_slug in disp_name_slug or disp_name_slug in entity_name_slug:
                    exact_matches.append(r)

            # Step 3: If no exact matches in vector search, try exact_name_search Scroll query
            if not exact_matches:
                print(f"[pipeline] specific search: no exact match in vector results. Trying exact_name_search fallback...")
                raw_fallback = await exact_name_search(entity_name, self.client)
                results_fallback = _dedup_by_display_name(raw_fallback)
                for r in results_fallback:
                    disp_name_slug = slugify_vn(r.get_display_name()).replace("-", " ").strip().lower()
                    if entity_name_slug in disp_name_slug or disp_name_slug in entity_name_slug:
                        exact_matches.append(r)
                
                # If fallback found exact matches, use them as our primary results
                if exact_matches:
                    raw_results = results_fallback

            # Filter results to only contain exact matches if any are found
            if exact_matches:
                # Sort exact_matches so that the closest name match comes first
                exact_matches.sort(
                    key=lambda r: SequenceMatcher(
                        None, 
                        entity_name_slug, 
                        slugify_vn(r.get_display_name()).replace("-", " ").strip().lower()
                    ).ratio(),
                    reverse=True
                )
                results = exact_matches[:3]
                print(f"[pipeline] specific search: found {len(results)} exact matches. Sorted order:")
                for r in results:
                    sim = SequenceMatcher(None, entity_name_slug, slugify_vn(r.get_display_name()).replace("-", " ").strip().lower()).ratio()
                    print(f"  - {r.get_display_name()} (similarity: {sim:.4f})")
            else:
                # If no exact match at all, we build fallback suggestions (same as the notebook's fallback builder)
                print(f"[pipeline] specific search: no exact matches found. Building suggestions fallback.")
                
                # Build fallback suggestions
                suggestions = []
                for r in raw_results[:3]:
                    parts = [f"- {r.get_display_name()}"]
                    if r.address:
                        parts.append(f"  Địa chỉ: {r.address}")
                    if r.rating is not None:
                        parts.append(f"  Đánh giá: {r.rating}/10")
                    suggestions.append("\n".join(parts))
                
                suggestions_str = "\n\n".join(suggestions) if suggestions else ""
                
                if suggestions_str:
                    fallback_text = (
                        f"Dạ, tôi chưa tìm thấy thông tin chính xác tuyệt đối cho '{q}'. "
                        f"Có phải bạn đang muốn tìm một trong các địa điểm nổi bật dưới đây không:\n\n"
                        f"{suggestions_str}\n\n"
                        f"Nếu đúng, bạn vui lòng cho tôi biết tên đầy đủ hoặc địa chỉ cụ thể hơn để tôi tư vấn nhé!"
                    )
                else:
                    fallback_text = (
                        f"Dạ, tôi chưa tìm thấy thông tin chính xác cho địa điểm bạn vừa hỏi. "
                        f"Bạn có thể cung cấp thêm tên đầy đủ, địa chỉ hoặc chi nhánh để tôi hỗ trợ được không ạ?"
                    )
                
                # Yield metadata
                yield {"type": "sources", "items": [], "total": 0}
                
                # Stream this response
                chunk_size = 8
                for idx in range(0, len(fallback_text), chunk_size):
                    if stop_event.is_set():
                        break
                    yield {"type": "token", "text": fallback_text[idx:idx+chunk_size]}
                    await asyncio.sleep(0.01)
                yield {"type": "done"}
                return
        elif intent == QueryIntent.ITINERARY_SEARCH:
            # 2. Trộn filter: FE sidebar thắng, analyzer điền field trống, session context fill còn lại
            merged = _merge_filters(filters, analysis["filters"])
            merged = merge_session_prefs(session_ctx, merged)

            # Lấy core_query từ analyzer, nếu trống dùng rewritten hoặc q gốc
            core_query = rewritten or q

            # Không lột bỏ toàn bộ ngữ cảnh để tránh làm loãng hoặc mất keyword tìm kiếm.
            # Chỉ loại bỏ các từ khóa quá chung chung.
            def _clean_itinerary_core(text: str) -> str:
                words_to_remove = [
                    "lịch trình", "lich trinh", "gợi ý", "goi y"
                ]
                cleaned = text.lower()
                for w in words_to_remove:
                    cleaned = cleaned.replace(w, "")
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                return cleaned

            cleaned_core = _clean_itinerary_core(core_query)

            # Xây dựng 3 query con
            q_places = f"địa điểm du lịch vui chơi tham quan {cleaned_core}".strip()
            q_rests = f"nhà hàng quán ăn đặc sản ngon {cleaned_core}".strip()
            q_hotels = f"khách sạn homestay resort lưu trú {cleaned_core}".strip()

            print(f"[pipeline] itinerary search sub-queries:")
            print(f"  - Places: {q_places!r}")
            print(f"  - Restaurants: {q_rests!r}")
            print(f"  - Hotels: {q_hotels!r}")

            # Retrieve song song 3 mảng
            tasks = [
                retrieve_by_intent(
                    query=q_places,
                    client=self.client,
                    encoder=self.encoder,
                    intent=QueryIntent.PLACE_SEARCH,
                    top_k_per_collection=config.TOP_K_RETRIEVE,
                    filters=merged,
                    score_threshold=config.SCORE_THRESHOLD,
                ),
                retrieve_by_intent(
                    query=q_rests,
                    client=self.client,
                    encoder=self.encoder,
                    intent=QueryIntent.RESTAURANT_SEARCH,
                    top_k_per_collection=config.TOP_K_RETRIEVE,
                    filters=merged,
                    score_threshold=config.SCORE_THRESHOLD,
                ),
                retrieve_by_intent(
                    query=q_hotels,
                    client=self.client,
                    encoder=self.encoder,
                    intent=QueryIntent.HOTEL_SEARCH,
                    top_k_per_collection=config.TOP_K_RETRIEVE,
                    filters=merged,
                    score_threshold=config.SCORE_THRESHOLD,
                ),
            ]

            raw_places, raw_rests, raw_hotels = await asyncio.gather(*tasks)

            # Rerank từng mảng - tăng top_k để có nhiều lựa chọn độc đáo không bị lặp
            if self.reranker is not None:
                rerank_tasks = []
                if raw_places:
                    rerank_tasks.append(rerank_results(raw_places, q_places, self.reranker, top_k=5, score_threshold=config.RERANK_SCORE_THRESHOLD, intent=QueryIntent.PLACE_SEARCH))
                else:
                    rerank_tasks.append(asyncio.sleep(0, result=[]))

                if raw_rests:
                    rerank_tasks.append(rerank_results(raw_rests, q_rests, self.reranker, top_k=5, score_threshold=config.RERANK_SCORE_THRESHOLD, intent=QueryIntent.RESTAURANT_SEARCH))
                else:
                    rerank_tasks.append(asyncio.sleep(0, result=[]))

                if raw_hotels:
                    rerank_tasks.append(rerank_results(raw_hotels, q_hotels, self.reranker, top_k=5, score_threshold=config.RERANK_SCORE_THRESHOLD, intent=QueryIntent.HOTEL_SEARCH))
                else:
                    rerank_tasks.append(asyncio.sleep(0, result=[]))

                ranked_places, ranked_rests, ranked_hotels = await asyncio.gather(*rerank_tasks)
            else:
                ranked_places, ranked_rests, ranked_hotels = raw_places[:5], raw_rests[:5], raw_hotels[:5]

            dedup_places = _dedup_by_display_name(ranked_places)
            dedup_rests = _dedup_by_display_name(ranked_rests)
            dedup_hotels = _dedup_by_display_name(ranked_hotels)

            # Gộp phân tầng: Lấy top 4 điểm vui chơi, top 4 nhà hàng và top 3 khách sạn để xây dựng lịch trình phong phú
            results = dedup_places[:4] + dedup_rests[:4] + dedup_hotels[:3]
            print(f"[pipeline] itinerary merged: {len(results)} items (Places: {len(dedup_places[:4])}, Restaurants: {len(dedup_rests[:4])}, Hotels: {len(dedup_hotels[:3])})")

        else:
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

            # --- Dynamic Intent Self-Correction ---
            # If the query was classified as a general category search (like hotel_search or restaurant_search)
            # but the user actually asked for details about a single specific entity from the top retrieved results,
            # we correct the intent to SPECIFIC_SEARCH and filter the context to only include that specific entity.
            if results and intent in (QueryIntent.HOTEL_SEARCH, QueryIntent.RESTAURANT_SEARCH, QueryIntent.PLACE_SEARCH, QueryIntent.GENERAL):
                q_slug = slugify_vn(q).replace("-", " ").strip().lower()
                is_general_list = any(gw in q_slug for gw in [
                    "goi y khach san", "goi y nha hang", "tim khach san", "tim nha hang", 
                    "khach san nao", "nha hang nao", "quan an nao", "dia diem check in",
                    "goi y", "tim giup", "tim ho"
                ])
                
                if not is_general_list:
                    matched_result = None
                    for r in results[:3]:  # Check top 3 retrieved results
                        disp_name = r.get_display_name()
                        clean_name = disp_name
                        for pref in ["Khách sạn ", "Khách Sạn ", "Nhà hàng ", "Nhà Hàng ", "Quán ", "Chợ "]:
                            if clean_name.startswith(pref):
                                clean_name = clean_name[len(pref):]
                                break
                        
                        disp_slug = slugify_vn(clean_name).replace("-", " ").strip().lower()
                        if len(disp_slug) > 3 and disp_slug in q_slug:
                            matched_result = r
                            break
                    
                    if matched_result:
                        print(f"[pipeline] Dynamic self-correction: matching query to entity {matched_result.get_display_name()!r}. Correcting intent to specific_search.")
                        intent = QueryIntent.SPECIFIC_SEARCH
                        results = [matched_result]

            t_rerank = time.perf_counter()
            print(f"[TIMING] rerank+dedup: {(t_rerank - t_rerank_start)*1000:.0f}ms "
                  f"(-> {len(results)} after dedup)")

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
