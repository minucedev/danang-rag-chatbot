from __future__ import annotations
import asyncio
import json
import re
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
from app.rag.schemas import ChatFilters, SearchResultSchema
from app.rag.events_retrieval import retrieve_events, format_events_context
from app.utils.nfc import normalize_nfc
from app.db.missed_queries import log_missed_query
from app.db import qa_cache

# Intents có thể crawl được địa điểm thực tế — log khi miss
_CRAWLABLE_INTENTS = {
    QueryIntent.HOTEL_SEARCH,
    QueryIntent.RESTAURANT_SEARCH,
    QueryIntent.PLACE_SEARCH,
    QueryIntent.SPECIFIC_SEARCH,
}

# Intents được phép cache câu trả lời (tra cứu tĩnh). KHÔNG cache event/itinerary/chitchat
# (động hoặc đã có nhánh riêng).
_CACHEABLE_INTENTS = {
    QueryIntent.HOTEL_SEARCH,
    QueryIntent.RESTAURANT_SEARCH,
    QueryIntent.PLACE_SEARCH,
    QueryIntent.REVIEW_SEARCH,
    QueryIntent.ROOM_SEARCH,
    QueryIntent.PRICE_SEARCH,
    QueryIntent.SPECIFIC_SEARCH,
    QueryIntent.GENERAL,
}


async def _store_qa_cache(question, qvec, answer, intent, merged, sources) -> None:
    """Lưu câu trả lời grounded vào cache (best-effort — lỗi cache KHÔNG ảnh hưởng câu trả lời)."""
    try:
        await qa_cache.store(
            question, qvec, answer, intent.value, merged,
            json.dumps(sources, ensure_ascii=False),
        )
    except Exception as exc:
        print(f"[pipeline] qa_cache store failed: {type(exc).__name__}: {exc}")

# Vietnamese few-shot examples to prevent English responses
_FEW_SHOT = """Ví dụ:
Câu hỏi: Gợi ý khách sạn 4 sao ở Sơn Trà?
Trả lời: Dựa trên thông tin hiện có, đây là một số khách sạn 4 sao ở Sơn Trà: 1. Sala Danang Beach Hotel - Đánh giá 9.4/10 (2,581 đánh giá), giá từ 500,000 VND. Khách sạn nằm gần biển, được khách hàng đánh giá rất cao.

Câu hỏi: Nhà hàng hải sản nào ngon ở Đà Nẵng?
Trả lời: Đà Nẵng có nhiều nhà hàng hải sản nổi tiếng. Dựa trên dữ liệu, tôi gợi ý: ..."""

_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng thông minh, nhiệt tình và am hiểu địa phương.\n"
    "Nhiệm vụ: Trả lời câu hỏi của khách du lịch dựa trên thông tin được cung cấp.\n\n"
    "Nguyên tắc bắt buộc:\n"
    "1. TUYỆT ĐỐI KHÔNG dùng các cụm kỹ thuật như \"dựa trên context\", \"theo dữ liệu\", "
    "\"hệ thống\", \"cơ sở dữ liệu\". Hãy nói chuyện tự nhiên như một hướng dẫn viên bản địa "
    "đang chia sẻ từ trải nghiệm cá nhân.\n"
    "2. Chỉ dùng thông tin có thật về địa chỉ, giá cả, đánh giá. KHÔNG bịa đặt hay suy diễn thêm.\n"
    "3. Nếu không đủ thông tin, thân thiện cho khách biết và gợi ý lựa chọn thay thế.\n"
    "4. Trả lời bằng tiếng Việt, tự nhiên, hào hứng, hiếu khách.\n"
    "5. Định dạng rõ ràng: gạch đầu dòng/đánh số khi liệt kê. Mỗi gợi ý: tên, địa chỉ, "
    "giá tham khảo, điểm nổi bật.\n"
    "6. Với câu hỏi lịch trình, chia theo ngày rõ ràng.\n"
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


# ─── Cá nhân hoá theo hồ sơ ────────────────────────────────────────────────
_COMPANION_VI = {"solo": "một mình", "couple": "cặp đôi", "family": "gia đình",
                 "friends": "bạn bè", "business": "công tác"}
_BUDGET_VI = {"low": "tiết kiệm", "mid": "trung bình", "high": "cao cấp"}
_INTEREST_VI = {"beach": "biển", "food": "ẩm thực", "cafe": "cà phê", "culture": "văn hoá",
                "nightlife": "về đêm", "family": "gia đình", "adventure": "phiêu lưu",
                "shopping": "mua sắm"}


def _build_profile_note(p) -> str:
    """Tóm tắt UserProfile thành đoạn chèn vào system prompt để cá nhân hoá câu trả lời.
    Trả "" nếu hồ sơ rỗng."""
    lines = []
    if p.display_name:
        lines.append(f"- Tên: {p.display_name}")
    if p.companions:
        lines.append(f"- Đi cùng: {_COMPANION_VI.get(p.companions, p.companions)}")
    if p.budget_level:
        lines.append(f"- Ngân sách: {_BUDGET_VI.get(p.budget_level, p.budget_level)}")
    if p.interests:
        lines.append("- Sở thích: " + ", ".join(_INTEREST_VI.get(i, i) for i in p.interests))
    if p.dietary:
        lines.append(f"- Ăn kiêng/lưu ý: {p.dietary}")
    if p.trip_dates:
        lines.append(f"- Thời gian đi: {p.trip_dates.start} → {p.trip_dates.end}")
    if not lines:
        return ""
    return (
        "\n\nHỒ SƠ NGƯỜI DÙNG (dùng để cá nhân hoá: ưu tiên gợi ý hợp sở thích/ngân sách "
        "và TÔN TRỌNG yêu cầu ăn kiêng. Nếu người dùng hỏi bạn có biết/đọc được hồ sơ của họ "
        "không, hãy xác nhận là CÓ và tóm tắt ngắn gọn):\n" + "\n".join(lines)
    )


def _inject_profile(msgs: list[dict], note: str) -> list[dict]:
    """Nối profile note vào nội dung system message (msgs[0]). No-op nếu note rỗng
    hoặc msgs[0] không phải system. Tách module-level để test được."""
    if note and msgs and msgs[0].get("role") == "system":
        msgs[0] = {**msgs[0], "content": msgs[0]["content"] + note}
    return msgs


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
    total = 0
    for i, r in enumerate(results[:8], 1):
        lines = [f"[{i}] {r.get_display_name()}"]
        lines.append(f"   - Loại: {r.collection}")
        lines.append(f"   - Quận/Huyện: {r.district or 'Chưa có'}")
        lines.append(f"   - Đánh giá: {r.get_rating_display()}")
        lines.append(f"   - Giá: {r.get_price_display()}")
        lines.append(f"   - Địa chỉ: {r.get_address_display()}")
        # Trường giàu (đã có sẵn trên SearchResultSchema) — giúp synthesizer trả lời sát hơn.
        if r.cuisine:
            lines.append(f"   - Ẩm thực: {r.cuisine}")
        if r.restaurant_type:
            lines.append(f"   - Loại hình: {r.restaurant_type}")
        if r.star_rating:
            lines.append(f"   - Hạng sao: {r.star_rating:.0f} sao")
        if r.room_view:
            lines.append(f"   - View: {r.room_view}")
        if r.tags:
            lines.append(f"   - Đặc điểm: {', '.join(r.tags)}")
        if r.time_open and r.time_close:
            lines.append(f"   - Giờ mở cửa: {r.time_open} - {r.time_close}")
        if r.content:
            lines.append(f"   - Nội dung: {r.content[:300]}")
        if r.room_name:
            cap = f" (Sức chứa: {r.capacity} người)" if r.capacity else ""
            area = f", {r.area_m2:.0f} m²" if r.area_m2 else ""
            bed = f", {r.bed_type}" if r.bed_type else ""
            lines.append(f"   - Phòng: {r.room_name}{cap}{area}{bed}")
        block = "\n".join(lines)
        # Cắt theo ngân sách ký tự để prompt không phình quá lớn.
        if total + len(block) > config.MAX_CONTEXT_CHARS and parts:
            break
        total += len(block)
        parts.append(block)
    return "\n\n".join(parts)


def _merge_filters(fe: Optional[dict], llm: dict) -> dict:
    """FE sidebar thắng theo từng field; analyzer chỉ điền field FE bỏ trống.

    `max_price` lấy min() của 2 nguồn (ngân sách chặt nhất) — không hồi quy ca
    sidebar-budget. FE là hành động tường minh; analyzer là suy luận có thể sai.
    Chỉ set key có giá trị → `_build_filter` truth-test không đổi hành vi.
    """
    fe = fe or {}
    merged: dict = {}
    # Lấy thẳng danh sách field từ ChatFilters → không lệch khi schema thêm/bớt filter.
    for key in ChatFilters.model_fields:
        fv = fe.get(key)
        lv = llm.get(key)
        # List rỗng coi như "không lọc" để không ghi đè giá trị FE/analyzer.
        if isinstance(fv, list) and not fv:
            fv = None
        if isinstance(lv, list) and not lv:
            lv = None
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


def _norm_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip() if text else ""


_UNKNOWN_NAMES = {"unknown", "đang cập nhật"}


def _find_exact_matches(
    query: str, results: List[SearchResultSchema]
) -> List[SearchResultSchema]:
    """Lọc các kết quả mà TÊN thực thể thực sự xuất hiện trong câu hỏi (ported từ notebook).

    Hỗ trợ dạng 'Tên gốc - Chi nhánh': base phải nằm trong query, và nếu có chi nhánh thì
    chi nhánh (hoặc 1 từ >3 ký tự của nó) cũng phải xuất hiện để tránh nhầm chi nhánh khác.
    """
    query_lower = _norm_match_text(query)
    matches: List[SearchResultSchema] = []
    for r in results:
        name = _norm_match_text(r.get_display_name())
        if not name or name in _UNKNOWN_NAMES:
            continue
        base_name, branch_name = name, ""
        if " - " in name:
            base_name, branch_name = name.split(" - ", 1)
        if len(base_name) >= 4 and base_name in query_lower:
            if branch_name:
                branch_words = [w for w in branch_name.split() if len(w) > 3]
                if branch_name not in query_lower and not any(w in query_lower for w in branch_words):
                    continue
            matches.append(r)
    return matches


def _build_specific_fallback(query: str, results: List[SearchResultSchema]) -> str:
    """Thông điệp gợi ý 'có phải bạn muốn tìm...' khi không khớp đúng tên (ported từ notebook)."""
    lines = []
    for r in results[:config.MAX_ALTERNATIVES]:
        name = r.get_display_name()
        if not name or name in ("Unknown", "Đang cập nhật"):
            continue
        parts = [f"- {name}"]
        addr = r.get_address_display()
        if addr and addr != "Chưa có địa chỉ":
            parts.append(f"  Địa chỉ: {addr}")
        if r.rating is not None:
            parts.append(f"  Đánh giá: {r.rating}/10")
        lines.append("\n".join(parts))

    suggestions = "\n\n".join(lines)
    if suggestions:
        return (
            f"Dạ, tôi chưa tìm thấy thông tin chính xác tuyệt đối cho '{query}'. "
            "Có phải bạn đang muốn tìm một trong các địa điểm nổi bật dưới đây không:\n\n"
            f"{suggestions}\n\n"
            "Nếu đúng, bạn vui lòng cho tôi biết tên đầy đủ hoặc địa chỉ cụ thể hơn để tôi tư vấn nhé!"
        )
    return (
        "Dạ, tôi chưa tìm thấy thông tin chính xác cho địa điểm bạn vừa hỏi. "
        "Bạn có thể cung cấp thêm tên đầy đủ, địa chỉ hoặc chi nhánh để tôi hỗ trợ được không ạ?"
    )


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
    elif intent == QueryIntent.REVIEW_SEARCH:
        rules = """### QUY TẮC BẮT BUỘC KHI TRẢ LỜI (TUÂN THỦ TUYỆT ĐỐI):
1. Tổng hợp nhận xét của khách, phân biệt rõ điểm tốt và điểm chưa tốt nếu có.
2. KHÔNG ẢO GIÁC: chỉ dùng thông tin trong "Thông tin tham khảo".
3. Nếu trống dữ liệu, lịch sự thông báo chưa có đánh giá phù hợp.
4. Trả lời bằng tiếng Việt, thân thiện."""
    elif intent == QueryIntent.ROOM_SEARCH:
        rules = """### QUY TẮC BẮT BUỘC KHI TRẢ LỜI (TUÂN THỦ TUYỆT ĐỐI):
1. Tập trung thông tin phòng: loại phòng, tiện ích, diện tích, sức chứa, giá, view.
2. KHÔNG ẢO GIÁC: chỉ dùng thông tin trong "Thông tin tham khảo".
3. Đề xuất tối đa 3-5 lựa chọn phù hợp nhất kèm giá và đánh giá.
4. Trả lời bằng tiếng Việt, thân thiện."""
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
        profile_session_id: Optional[str] = None,
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

        # Cá nhân hoá: nạp hồ sơ (nếu có) → chèn vào system prompt của mọi nhánh sinh.
        profile_note = ""
        if profile_session_id:
            try:
                from app.db.profiles import get_profile
                prof = await get_profile(profile_session_id)
                if prof:
                    profile_note = _build_profile_note(prof)
            except Exception as exc:
                print(f"[pipeline] load profile failed: {type(exc).__name__}: {exc}")

        def _with_profile(msgs: list[dict]) -> list[dict]:
            return _inject_profile(msgs, profile_note)

        # Chitchat: không cần RAG, trả lời trực tiếp từ LLM
        if intent == QueryIntent.CHITCHAT:
            yield {"type": "sources", "items": [], "total": 0}
            chitchat_messages = [{"role": "system", "content": _CHITCHAT_SYSTEM_PROMPT}]
            chitchat_messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
            chitchat_messages.append({"role": "user", "content": q})
            chitchat_messages = _with_profile(chitchat_messages)
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
            messages = _with_profile(_build_event_messages(q, events, history))
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

        # 2.5. Cache câu trả lời: câu gần trùng (cùng intent + filters, KHÔNG cá nhân hoá) → trả ngay,
        #      bỏ qua retrieve + Gemini. qvec embed 1 lần, tái dùng cho cả check lẫn store grounded sau.
        qvec = None
        cache_ok = config.QA_CACHE_ENABLED and intent in _CACHEABLE_INTENTS and not profile_note
        if cache_ok:
            qvec = await loop.run_in_executor(
                None, lambda: self.encoder.encode([q], normalize_embeddings=True)[0]
            )
            try:
                hit = await qa_cache.find_similar(qvec, intent.value, merged)
            except Exception as exc:
                print(f"[pipeline] qa_cache lookup failed: {type(exc).__name__}: {exc}")
                hit = None
            if hit:
                cached_sources = json.loads(hit["sources_json"]) if hit["sources_json"] else []
                yield {"type": "sources", "items": cached_sources, "total": len(cached_sources)}
                if config.QA_CACHE_NOTE:
                    yield {"type": "token", "text": "_(Dùng lại câu trả lời tương tự đã lưu)_\n\n"}
                yield {"type": "token", "text": hit["answer"]}
                print(f"[TIMING] qa_cache HIT score={hit['score']:.3f} — bỏ qua Gemini")
                yield {"type": "done"}
                return

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

        # 4. BGE reranker (+ heuristic) → dedup. Heuristic chạy cả khi reranker tắt:
        #    rerank_results tự dùng điểm cosine làm base khi self.reranker is None.
        t_rerank_start = time.perf_counter()
        if results:
            results = await rerank_results(
                results, rewritten, self.reranker,
                top_k=config.TOP_K_RERANK,
                score_threshold=config.RERANK_SCORE_THRESHOLD,
                intent=intent,
                extracted=analysis,
            )
        results = _dedup_by_display_name(results)
        t_rerank = time.perf_counter()
        print(f"[TIMING] rerank+dedup: {(t_rerank - t_rerank_start)*1000:.0f}ms "
              f"(-> {len(results)} after dedup)")

        # 4.5. Exact name fallback cho SPECIFIC_SEARCH khi không có kết quả.
        #      Ưu tiên tên thực thể đã trích (analysis["entity"]) — sạch hơn rewritten
        #      vì không lẫn từ hỏi đáp; rỗng thì lùi về rewritten.
        if not results and intent == QueryIntent.SPECIFIC_SEARCH:
            search_name = " ".join(analysis.get("entity") or []).strip() or rewritten
            raw_fallback = await exact_name_search(search_name, self.client)
            results = _dedup_by_display_name(raw_fallback)
            if results:
                print(f"[pipeline] exact_name_search found {len(results)} fallback results")

        # 4.55. SPECIFIC_SEARCH: nếu có khớp đúng tên → thu hẹp về đúng thực thể được hỏi;
        #       nếu chỉ có gần đúng → phát thông điệp gợi ý "có phải bạn muốn tìm..." rồi dừng.
        specific_no_exact = False
        if intent == QueryIntent.SPECIFIC_SEARCH and results:
            exact = _find_exact_matches(q, results)
            if exact:
                results = exact[:config.MAX_ALTERNATIVES]
            else:
                specific_no_exact = True

        sources = [r.to_dict() for r in results[:10]]
        yield {"type": "sources", "items": sources, "total": len(sources)}

        if specific_no_exact:
            # Không tìm thấy đúng thực thể — log để crawler bổ sung + trả gợi ý tương tự.
            if intent in _CRAWLABLE_INTENTS:
                try:
                    await log_missed_query(q, rewritten, intent.value, session_id)
                except Exception as _log_exc:
                    print(f"[pipeline] log_missed_query failed: {type(_log_exc).__name__}: {_log_exc}")
            yield {"type": "token", "text": _build_specific_fallback(q, results)}
            yield {"type": "done"}
            return

        # 4.6. Log missed query nếu không có kết quả và là intent crawlable
        if not results and intent in _CRAWLABLE_INTENTS:
            try:
                await log_missed_query(q, rewritten, intent.value, session_id)
            except Exception as _log_exc:
                print(f"[pipeline] log_missed_query failed: {type(_log_exc).__name__}: {_log_exc}")

        # 3.5. Fallback sang Gemini khi retrieve trả 0 kết quả (chỉ khi không dùng Gemini primary).
        # Khi USE_GEMINI_GENERATION=True, path này bị skip — Gemini primary xử lý luôn cả no-results.
        if not results and config.GEMINI_API_KEY and not config.USE_GEMINI_GENERATION:
            gemini_messages = _with_profile(_build_gemini_messages(q, history, intent))
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
        messages = _with_profile(_build_messages(q, results, history, intent))
        prompt_chars = sum(len(m["content"]) for m in messages)
        print(f"[TIMING] prompt_built: {prompt_chars} chars across {len(messages)} msgs")

        t_before_gen = time.perf_counter()
        first_token_logged = False
        token_count = 0

        # 4.1. Gemini primary generator (nhanh hơn local LLM ~5-10x).
        # BUFFER toàn bộ output rồi mới phát: nếu Gemini bị CẮT / hết quota / lỗi
        # (generate_gemini_streaming raise khi finishReason ngoài {STOP, MAX_TOKENS}) thì CHƯA
        # gửi gì cho client → sinh lại bằng local LLM thay vì để câu trả lời cụt giữa từ.
        # Lưu ý: nhánh no-results, local dùng prompt grounded RỖNG (messages) nên có thể trả
        # "không tìm thấy" thay vì kiến thức chung — chấp nhận khi Gemini không khả dụng.
        # Đánh đổi: mất hiệu ứng stream từng chữ ở nhánh Gemini, đổi lấy câu trả lời trọn vẹn.
        if config.USE_GEMINI_GENERATION:
            # Không có dữ liệu nội bộ → để Gemini trả lời từ kiến thức chung (kèm disclaimer)
            # thay vì bám reference rỗng rồi báo "không tìm thấy". Missed query vẫn được log
            # ở trên để crawler bổ sung địa điểm thật sau.
            gen_messages = messages if results else _with_profile(_build_gemini_messages(q, history, intent))
            buffered: list[str] = []
            try:
                async for token in generate_gemini_streaming(
                    gen_messages, stop_event,
                    max_new_tokens=max_new_tokens, temperature=temperature,
                ):
                    if stop_event.is_set():
                        break
                    buffered.append(token)
                # User abort giữa lúc buffer → bỏ partial, để chat.py lưu "(Đã dừng)".
                if stop_event.is_set():
                    yield {"type": "done"}
                    return
                # Thành công + đầy đủ (finishReason=STOP). Phát disclaimer (nếu 0 kết quả) rồi text.
                t_done = time.perf_counter()
                print(f"[TIMING] generation (Gemini, buffered): {(t_done - t_before_gen)*1000:.0f}ms "
                      f"({len(buffered)} chunks)")
                print(f"[TIMING] === TOTAL: {(t_done - t_start)*1000:.0f}ms ===")
                if not results and config.GEMINI_FALLBACK_PREFIX_DISCLAIMER:
                    yield {"type": "token", "text": _NO_DATA_DISCLAIMER}
                for tok in buffered:
                    yield {"type": "token", "text": tok}
                # Lưu cache chỉ khi grounded (có dữ liệu nội bộ) + không cá nhân hoá.
                if cache_ok and results and not stop_event.is_set():
                    final = "".join(buffered).strip()
                    if final:
                        await _store_qa_cache(q, qvec, final, intent, merged, sources)
                yield {"type": "done"}
                return
            except GeminiFallbackError as e:
                status = f" status={e.status_code}" if e.status_code is not None else ""
                # Chưa phát gì cho client (đang buffer) → rơi xuống local LLM sạch sẽ.
                print(f"[pipeline] Gemini primary unusable{status} ({type(e).__name__}: {e}) "
                      f"— regenerate with local LLM")
                if not results:
                    yield {"type": "token",
                           "text": "_(Dịch vụ AI tổng quát tạm không khả dụng — trả lời bằng mô hình nội bộ.)_\n\n"}
                first_token_logged = False
                token_count = 0
                t_before_gen = time.perf_counter()

        # 4.2. Local LLM generation (primary khi Gemini không configured, hoặc fallback)
        local_parts: list[str] = []
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
            local_parts.append(token)
            yield {"type": "token", "text": token}

        t_done = time.perf_counter()
        gen_dur = t_done - t_before_gen
        tok_per_s = token_count / gen_dur if gen_dur > 0 else 0
        print(f"[TIMING] generation: {gen_dur*1000:.0f}ms "
              f"({token_count} tokens, {tok_per_s:.1f} tok/s)")
        print(f"[TIMING] === TOTAL: {(t_done - t_start)*1000:.0f}ms ===")

        if cache_ok and results and not stop_event.is_set():
            final = "".join(local_parts).strip()
            if final:
                await _store_qa_cache(q, qvec, final, intent, merged, sources)

        yield {"type": "done"}

    async def warmup(self) -> None:
        """Run one dummy hotel query để buộc encoder + reranker warmup (tránh CHITCHAT path)."""
        stop = threading.Event()
        async for _ in self.answer_stream(
            "khách sạn Đà Nẵng", [], stop_event=stop, max_new_tokens=5
        ):
            pass
