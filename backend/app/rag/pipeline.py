from __future__ import annotations
import asyncio
import re
import threading
import time
import json
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
    "1. TUYỆT ĐỐI KHÔNG được sử dụng các cụm từ kỹ thuật như 'dựa trên context', 'trong context', 'theo context cung cấp', 'dữ liệu đã cho', 'hệ thống', 'cơ sở dữ liệu', 'CONTEXT', 'thông tin trong CONTEXT', v.v. Hãy nói chuyện tự nhiên như một hướng dẫn viên bản địa thực thụ đang chia sẻ từ kiến thức và trải nghiệm cá nhân.\n"
    "2. Chỉ dùng các thông tin có thật về địa chỉ, giá cả, đánh giá từ mô tả địa điểm. KHÔNG bịa đặt hay suy diễn thêm.\n"
    "3. Nếu không đủ thông tin để trả lời, hãy thân thiện cho khách biết và gợi ý lựa chọn thay thế.\n"
    "4. Trả lời bằng tiếng Việt, tự nhiên, hào hứng, hiếu khách. BẮT BUỘC dịch mọi thông tin bằng tiếng Anh từ dữ liệu cung cấp (mô tả, tiện ích, lý do chọn, v.v.) sang tiếng Việt tự nhiên.\n"
    "5. Định dạng rõ ràng: dùng gạch đầu dòng hoặc đánh số khi liệt kê nhiều địa điểm. Với mỗi gợi ý: tên, địa chỉ (nếu có), giá tham khảo (nếu có), điểm nổi bật.\n"
    "6. Với câu hỏi lịch trình (itinerary), chia theo ngày rõ ràng và tuyệt đối không lặp lại địa điểm.\n"
    "7. KHÔNG đề xuất địa điểm ngoài Đà Nẵng trừ khi được yêu cầu.\n"
    "8. TUYỆT ĐỐI KHÔNG tự thêm URL, link website hay link đặt chỗ nếu không có sẵn trong dữ liệu."
)

_CHITCHAT_SYSTEM_PROMPT = (
    "Bạn là trợ lý du lịch Đà Nẵng thân thiện. LUÔN trả lời bằng tiếng Việt.\n"
    "Với câu hỏi chung về bản thân: giới thiệu bạn là AI hỗ trợ du lịch Đà Nẵng, "
    "có thể giúp tìm khách sạn, nhà hàng, địa điểm tham quan và sự kiện.\n"
    "Với câu hỏi ngoài phạm vi (thời tiết, vé máy bay, ...): trả lời thân thiện và "
    "hướng dẫn người dùng hỏi về du lịch Đà Nẵng."
)



_ITINERARY_PLANNER_SYSTEM_PROMPT = (
    "Bạn là trợ lý lập kế hoạch lịch trình du lịch Đà Nẵng.\n"
    "Nhiệm vụ của bạn là phân tích yêu cầu của người dùng và tạo ra một khung kế hoạch (skeleton itinerary) dưới dạng một JSON array thuần túy theo từng ngày và các buổi trong ngày.\n\n"
    "Quy tắc chọn số lượng ngày hoạt động (BẮT BUỘC):\n"
    "1. Đếm số ngày người dùng yêu cầu (ví dụ: '3 ngày 2 đêm' -> 3 ngày hoạt động, '2 ngày 1 đêm' -> 2 ngày hoạt động, '1 ngày' -> 1 ngày hoạt động).\n"
    "2. Nếu không nói rõ số ngày, mặc định tạo lịch trình 3 ngày hoạt động.\n"
    "3. Tạo đúng số lượng phần ngày hoạt động tương ứng (day: 1, day: 2, ...).\n"
    "4. Ở cuối mảng, LUÔN LUÔN tạo thêm một phần dành cho Lưu trú (day: 'Lưu trú').\n\n"
    "Để lịch trình hợp lý, mượt mà và tránh mất thời gian di chuyển:\n"
    "1. Phân bổ các buổi trong cùng một ngày ở các khu vực gần nhau hoặc cùng một Quận.\n"
    "2. Xác định rõ chủ đề/hoạt động cho từng buổi.\n"
    "3. Tạo câu truy vấn tìm kiếm ngắn gọn bằng tiếng Việt mô tả địa điểm mong muốn.\n"
    "4. Xác định loại hình địa điểm cần tìm kiếm để chọn collection tương ứng:\n"
    "   - \"place\" (địa điểm du lịch, vui chơi, tham quan)\n"
    "   - \"restaurant\" (nhà hàng, quán ăn, quán cà phê)\n"
    "   - \"hotel\" (nơi lưu trú, khách sạn. LUÔN LUÔN tạo 1 object riêng ở CUỐI mảng JSON với day='Lưu trú')\n\n"
    "Hãy xem các ví dụ mẫu sau đây để làm theo:\n\n"
    "### VÍ DỤ 1:\n"
    "Người dùng: \"Gợi ý lịch trình 2 ngày 1 đêm\"\n"
    "Trả về JSON:\n"
    "[\n"
    "  {\n"
    "    \"day\": 1,\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Sáng\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"tham quan\",\n"
    "        \"query\": \"cầu sông hàn\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Chiều\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"vui chơi\",\n"
    "        \"query\": \"công viên châu á\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Tối\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"ăn hải sản\",\n"
    "        \"query\": \"nhà hàng hải sản ngon\",\n"
    "        \"collection_type\": \"restaurant\"\n"
    "      }\n"
    "    ]\n"
    "  },\n"
    "  {\n"
    "    \"day\": 2,\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Sáng\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"tắm biển\",\n"
    "        \"query\": \"bãi biển mỹ khê\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Chiều\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"tham quan\",\n"
    "        \"query\": \"chùa linh ứng bán đảo sơn trà\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Tối\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"ăn tối\",\n"
    "        \"query\": \"quán ăn sơn trà\",\n"
    "        \"collection_type\": \"restaurant\"\n"
    "      }\n"
    "    ]\n"
    "  },\n"
    "  {\n"
    "    \"day\": \"Lưu trú\",\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Gợi ý\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"Khách sạn/Homestay\",\n"
    "        \"query\": \"khách sạn tiện nghi\",\n"
    "        \"collection_type\": \"hotel\"\n"
    "      }\n"
    "    ]\n"
    "  }\n"
    "]\n\n"
    "### VÍ DỤ 2:\n"
    "Người dùng: \"Gợi ý lịch trình 3 ngày 2 đêm cho gia đình\"\n"
    "Trả về JSON:\n"
    "[\n"
    "  {\n"
    "    \"day\": 1,\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Sáng\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"tham quan\",\n"
    "        \"query\": \"cầu sông hàn\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Chiều\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"vui chơi\",\n"
    "        \"query\": \"công viên châu á\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Tối\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"ăn hải sản\",\n"
    "        \"query\": \"nhà hàng hải sản ngon\",\n"
    "        \"collection_type\": \"restaurant\"\n"
    "      }\n"
    "    ]\n"
    "  },\n"
    "  {\n"
    "    \"day\": 2,\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Sáng\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"tắm biển\",\n"
    "        \"query\": \"bãi biển mỹ khê\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Chiều\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"tham quan\",\n"
    "        \"query\": \"chùa linh ứng bán đảo sơn trà\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Tối\",\n"
    "        \"district\": \"son tra\",\n"
    "        \"theme\": \"ăn tối\",\n"
    "        \"query\": \"quán ăn sơn trà\",\n"
    "        \"collection_type\": \"restaurant\"\n"
    "      }\n"
    "    ]\n"
    "  },\n"
    "  {\n"
    "    \"day\": 3,\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Sáng\",\n"
    "        \"district\": \"ngu hanh son\",\n"
    "        \"theme\": \"leo núi tham quan\",\n"
    "        \"query\": \"chùa non nước ngũ hành sơn\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Chiều\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"mua sắm đặc sản\",\n"
    "        \"query\": \"chợ hàn mua sắm\",\n"
    "        \"collection_type\": \"place\"\n"
    "      },\n"
    "      {\n"
    "        \"session\": \"Tối\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"cà phê\",\n"
    "        \"query\": \"quán cà phê đẹp hải châu\",\n"
    "        \"collection_type\": \"restaurant\"\n"
    "      }\n"
    "    ]\n"
    "  },\n"
    "  {\n"
    "    \"day\": \"Lưu trú\",\n"
    "    \"slots\": [\n"
    "      {\n"
    "        \"session\": \"Gợi ý\",\n"
    "        \"district\": \"hai chau\",\n"
    "        \"theme\": \"Khách sạn/Homestay\",\n"
    "        \"query\": \"khách sạn tiện nghi\",\n"
    "        \"collection_type\": \"hotel\"\n"
    "      }\n"
    "    ]\n"
    "  }\n"
    "]\n\n"
    "Chỉ trả về duy nhất chuỗi JSON array hợp lệ. Không giải thích, không markdown."
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
    session_summary: Optional[str] = None
) -> list[dict]:
    messages = [{"role": "system", "content": _GEMINI_SYSTEM_PROMPT}]
    from app.rag.manager import build_final_context_prompt
    history_msgs = build_final_context_prompt(session_summary, history)
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": query})
    return messages


def _format_context(results: List[SearchResultSchema], max_items: int = 8, max_chars: int = 4000) -> str:
    if not results:
        return "Không có thông tin phù hợp với yêu cầu."
    parts = []
    total = 0
    for i, r in enumerate(results[:max_items], 1):
        lines = [f"[{i}] {r.get_display_name()}"]
        
        coll_type = r.collection
        if "restaurant" in coll_type:
            coll_type = "Nhà hàng/Quán ăn"
        elif "place" in coll_type:
            coll_type = "Điểm tham quan/Vui chơi"
        elif "accommodation" in coll_type:
            coll_type = "Khách sạn/Lưu trú"
            
        lines.append(f"   - Loại: {coll_type}")
        lines.append(f"   - Quận/Huyện: {r.district or 'Chưa có'}")
        lines.append(f"   - Đánh giá: {r.get_rating_display()}")
        price_display = r.get_price_display()
        if price_display and price_display != "Không có thông tin giá":
            lines.append(f"   - Giá: {price_display}")
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
        if r.opening_hours:
            lines.append(f"   - Giờ mở cửa: {r.opening_hours}")
        elif r.time_open and r.time_close:
            lines.append(f"   - Giờ mở cửa: {r.time_open} - {r.time_close}")
        elif r.time_open:
            lines.append(f"   - Giờ mở cửa: {r.time_open}")
        if r.content:
            lines.append(f"   - Nội dung: {r.content[:1000]}")
        if r.room_name:
            cap = f" (Sức chứa: {r.capacity} người)" if r.capacity else ""
            area = f", {r.area_m2:.0f} m²" if r.area_m2 else ""
            bed = f", {r.bed_type}" if r.bed_type else ""
            lines.append(f"   - Phòng: {r.room_name}{cap}{area}{bed}")
        block = "\n".join(lines)
        # Cắt theo ngân sách ký tự để prompt không phình quá lớn.
        if total + len(block) > max_chars and parts:
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


_UNKNOWN_NAMES = {"Không có thông tin", "đang cập nhật"}


def _unaccent(s: str) -> str:
    s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
    s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
    s = re.sub(r'[ìíịỉĩ]', 'i', s)
    s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
    s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
    s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
    s = re.sub(r'[đ]', 'd', s)
    return s

def _get_sig_words(text: str) -> set[str]:
    text = _unaccent(str(text).lower())
    words = set(re.findall(r'\b\w+\b', text))
    stopwords = {"khach", "san", "nha", "hang", "quan", "co", "khong", "la", "va", "cua", "o", "da", "nang", "danang", "banh", "xeo", "hai", "san", "hotel", "restaurant", "cafe", "coffee", "ba", "chu", "ong", "di"}
    return {w for w in words if w not in stopwords and len(w) > 1}

def _find_exact_matches(
    query: str, results: List[SearchResultSchema], extracted_entity: str = ""
) -> List[SearchResultSchema]:
    """Lọc các kết quả mà TÊN thực thể thực sự xuất hiện trong câu hỏi hoặc là một phần của tên DB."""
    query_lower = _norm_match_text(query)
    
    # Ưu tiên dùng thực thể LLM bóc tách, nếu không có thì dùng query
    entity_to_check = extracted_entity if extracted_entity else query
    query_words = _get_sig_words(entity_to_check)
    
    matches: List[SearchResultSchema] = []
    for r in results:
        name = _norm_match_text(r.get_display_name())
        if not name or name in _UNKNOWN_NAMES:
            continue
        
        base_name, branch_name = name, ""
        if " - " in name:
            base_name, branch_name = name.split(" - ", 1)
            
        # 1. Match substring truyền thống
        if len(base_name) >= 4 and base_name in query_lower:
            if branch_name:
                branch_words = [w for w in branch_name.split() if len(w) > 3]
                if branch_name not in query_lower and not any(w in query_lower for w in branch_words):
                    continue
            matches.append(r)
            continue
            
        # 2. Match theo token (từ khóa đặc trưng)
        db_words = _get_sig_words(base_name)
        if query_words and query_words.issubset(db_words):
            matches.append(r)
            
    return matches


def _build_specific_fallback(query: str, results: List[SearchResultSchema]) -> str:
    """Thông điệp gợi ý 'có phải bạn muốn tìm...' khi không khớp đúng tên (ported từ notebook)."""
    lines = []
    for r in results[:config.MAX_ALTERNATIVES]:
        name = r.get_display_name()
        if not name or name in ("Không có thông tin", "Đang cập nhật"):
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
    standalone_q: str,
    results: list[SearchResultSchema],
    history: list[dict],
    intent: QueryIntent,
    session_summary: Optional[str] = None,
    prebuilt_context: Optional[str] = None,
) -> list[dict]:
    if prebuilt_context is not None:
        context = prebuilt_context
    else:
        max_ctx_items = 30 if intent == QueryIntent.ITINERARY_SEARCH else 8
        max_ctx_chars = 15000 if intent == QueryIntent.ITINERARY_SEARCH else config.MAX_CONTEXT_CHARS
        context = _format_context(results, max_items=max_ctx_items, max_chars=max_ctx_chars)

    hint = ""
    if intent == QueryIntent.CHITCHAT or (not results and prebuilt_context is None):
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        from app.rag.manager import build_final_context_prompt
        history_msgs = build_final_context_prompt(session_summary, history)
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": standalone_q})
        return messages

    if intent == QueryIntent.ITINERARY_SEARCH:
        hint = (
            "Hãy lập lịch trình chi tiết theo ngày. BẮT BUỘC viết dựa trên khung lịch trình và các địa điểm thực tế gợi ý tương ứng với từng Buổi (Sáng/Chiều/Tối) trong thông tin được cung cấp.\n"
            "Về định dạng, hãy sử dụng Markdown. Với mỗi ngày, phải có tiêu đề ngày in đậm, sau đó là danh sách lồng nhau cho từng buổi như sau:\n\n"
            "### **Ngày [X]**\n"
            "*   **Buổi [Sáng/Chiều/Tối]: **\n"
            "    *   **Địa điểm:** [Tên địa điểm]\n"
            "    *   **Địa chỉ:** [Lấy từ dữ liệu]\n"
            "    *   **Điểm nổi bật:** [Mô tả vài điểm nổi bật, lời lời lẽ trau chút vừa đủ, không quá ngắn , không quá dài ]\n"
            "    *   **Chi phí:** [Lấy đúng thông tin từ trường 'Giá:' trong dữ liệu cung cấp, nếu là 0 VND hãy ghi 'Miễn phí'. Nếu dữ liệu thực sự không có trường Giá, mới ghi 'Không có thông tin']\n"
            "    *   **Lưu ý:** Giờ mở cửa: [Lấy thời gian từ trường 'Giờ mở cửa' trong dữ liệu cung cấp]\n\n"
            "ĐẶC BIỆT: NẾU trong dữ liệu cung cấp có địa điểm lưu trú (khách sạn/homestay/resort), HÃY TÁCH NÓ RA và đặt ở CUỐI CÙNG của toàn bộ lịch trình dưới dạng một phần riêng (KHÔNG nằm trong ngày nào):\n\n"
            "### **Gợi ý Lưu trú**\n"
            "*   **Tên:** [Tên khách sạn]\n"
            "    *   **Địa chỉ:** [Địa chỉ]\n"
            "    *   **Lý do nên chọn:** [BẮT BUỘC viết bằng tiếng Việt. Nếu dữ liệu nguồn là tiếng Anh, hãy dịch nghĩa và diễn đạt lại một cách tự nhiên bằng tiếng Việt]\n"
            "    *   **Chi phí tham khảo từ:** [lấy đúng từ dữ liệu]\n\n"
            "TUYỆT ĐỐI KHÔNG tự bịa tên địa điểm hoặc giữ nguyên các chữ [Tên địa điểm], [Lấy từ dữ liệu]. Nếu dữ liệu thực tế cho một buổi ghi 'Không tìm thấy địa điểm thực tế phù hợp', hãy ghi rõ: 'Hiện chưa có gợi ý phù hợp cho buổi này'.\n"
            "Tuyệt đối không gộp chung thành một đoạn văn."
        )
    elif intent == QueryIntent.REVIEW_SEARCH:
        hint = "Tổng hợp nhận xét, phân biệt điểm tốt và chưa tốt nếu có."
    elif intent == QueryIntent.ROOM_SEARCH:
        hint = "Tập trung vào thông tin phòng: loại phòng, tiện ích, diện tích, giá."
    elif intent == QueryIntent.SPECIFIC_SEARCH:
        query_lower = standalone_q.lower()
        asks_for_reviews = any(w in query_lower for w in ["đánh giá", "nhận xét", "review", "khen", "chê", "thấy sao", "tốt không"])
        if asks_for_reviews:
            hint = "Tổng hợp nhận xét thành các điểm khen/chê nổi bật, trình bày tự nhiên, lưu loát."
        else:
            hint = "Hãy trả lời tự nhiên, thân thiện và lưu loát. Bạn có thể khéo léo lồng ghép thêm địa chỉ, giá cả, và các thông tin thú vị (ví dụ: đặc điểm nổi bật, món ăn ngon, phong cách) để giống một trợ lý du lịch nhiệt tình. LUÔN thêm câu: 'Ngoài ra, bạn có thể tham khảo thêm thông tin chi tiết trên thẻ địa điểm nhé!' vào cuối."

    user_prompt = f"""THÔNG TIN ĐỊA ĐIỂM DU LỊCH ĐÀ NẴNG:
{context}

---
Câu hỏi: {standalone_q}

Hướng dẫn bổ sung: {hint}

LƯU Ý BẮT BUỘC: Tất cả các trường thông tin trong câu trả lời (bao gồm 'Lý do nên chọn' và 'Điểm nổi bật') PHẢI được viết bằng TIẾNG VIỆT. Nếu thông tin địa điểm cung cấp bằng tiếng Anh, bạn phải tự dịch nghĩa và diễn đạt lại bằng tiếng Việt. TUYỆT ĐỐI KHÔNG để nguyên văn câu tiếng Anh nào."""

    system_content = _SYSTEM_PROMPT

    messages = [{"role": "system", "content": system_content}]
    from app.rag.manager import build_final_context_prompt
    history_msgs = build_final_context_prompt(session_summary, history)
    messages.extend(history_msgs)
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
        from app.rag.manager import ConversationManager
        self.conversation_manager = ConversationManager(analyzer_llm or llm)

    async def _background_update_summary(self, session_id: str, history: list[dict]):
        from app.db import sessions as db
        loop = asyncio.get_running_loop()
        summary_str = await loop.run_in_executor(None, self.conversation_manager.summarize_history, history)
        if summary_str:
            await db.update_session_summary(session_id, summary_str)

    def _run_itinerary_planner(self, query: str) -> list[dict]:
        """Tạo một khung lịch trình (plan skeleton) từ yêu cầu người dùng."""
        messages = [
            {"role": "system", "content": _ITINERARY_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        
        fallback = [
            {
                "day": 1,
                "slots": [
                    {"session": "Sáng", "district": "hai chau", "theme": "vui chơi giải trí", "query": "địa điểm du lịch nổi tiếng hải châu", "collection_type": "place"},
                    {"session": "Chiều", "district": "son tra", "theme": "tắm biển tham quan", "query": "bãi biển Mỹ Khê chùa linh ứng", "collection_type": "place"},
                    {"session": "Tối", "district": "son tra", "theme": "hải sản ăn uống", "query": "quán ăn hải sản sơn trà ngon", "collection_type": "restaurant"}
                ]
            },
            {
                "day": 2,
                "slots": [
                    {"session": "Sáng", "district": "ngu hanh son", "theme": "tham quan leo núi", "query": "chùa non nước ngũ hành sơn", "collection_type": "place"},
                    {"session": "Chiều", "district": "ngu hanh son", "theme": "vui chơi giải trí", "query": "phố cổ hội an hoặc bãi tắm ngũ hành sơn", "collection_type": "place"},
                    {"session": "Tối", "district": "hai chau", "theme": "ăn vặt đường phố", "query": "chợ đêm helio chợ cồn hải châu", "collection_type": "restaurant"}
                ]
            },
            {
                "day": 3,
                "slots": [
                    {"session": "Sáng", "district": "son tra", "theme": "thư giãn", "query": "cà phê đẹp sơn trà", "collection_type": "restaurant"},
                    {"session": "Chiều", "district": "hai chau", "theme": "mua sắm", "query": "chợ hàn mua sắm đặc sản", "collection_type": "place"},
                    {"session": "Tối", "district": "hai chau", "theme": "dạo phố", "query": "đi dạo ven sông hàn", "collection_type": "place"}
                ]
            },
            {
                "day": "Lưu trú",
                "slots": [
                    {"session": "Gợi ý", "district": "hai chau", "theme": "Khách sạn/Homestay", "query": "khách sạn trung tâm tiện nghi", "collection_type": "hotel"}
                ]
            }
        ]

        # Hàm chuẩn hóa tên quận từ planner LLM về đúng format Qdrant
        _DISTRICT_ALIASES = {
            "hai chau": "hai chau", "hải châu": "hai chau", "quận hai": "hai chau",
            "quan hai": "hai chau", "hải châu": "hai chau",
            "son tra": "son tra", "sơn trà": "son tra", "quan son tra": "son tra",
            "thanh khe": "thanh khe", "thanh khê": "thanh khe", "thanh khê": "thanh khe",
            "ngu hanh son": "ngu hanh son", "ngũ hành sơn": "ngu hanh son",
            "ngu hanh son": "ngu hanh son", "quan ngu hanh son": "ngu hanh son",
            "cam le": "cam le", "cẩm lệ": "cam le",
            "hoa vang": "hoa vang", "hòa vang": "hoa vang",
            "lien chieu": "lien chieu", "liên chiểu": "lien chieu",
        }
        _VALID_DISTRICTS = set(_DISTRICT_ALIASES.values())

        def _normalize_district(raw: str | None) -> str | None:
            if not raw:
                return None
            key = re.sub(r"\s+", " ", str(raw).lower()).strip()
            if key in _DISTRICT_ALIASES:
                return _DISTRICT_ALIASES[key]
            # Khớp một phần với tên quận hợp lệ
            for alias, canonical in _DISTRICT_ALIASES.items():
                if alias in key or key in alias:
                    return canonical
            return None  # Không nhận dạng được → bỏ filter quận

        def _normalize_plan(plan: list) -> list:
            """Chuẩn hóa district trong plan do LLM sinh ra."""
            for day_info in plan:
                for slot in day_info.get("slots", []):
                    raw_district = slot.get("district")
                    slot["district"] = _normalize_district(raw_district)
            return plan

        try:
            completion = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=3000,
                temperature=0.0,
                stream=False,
            )
            gen_text = completion["choices"][0]["message"]["content"].strip()

            # extract JSON array
            json_match = re.search(r'\[.*\]', gen_text, re.DOTALL)
            raw = json_match.group(0) if json_match else gen_text
            result = json.loads(raw)

            if not isinstance(result, list) or len(result) == 0:
                print("[pipeline] itinerary_planner: LLM trả về plan rỗng → dùng fallback")
                return fallback

            # Đếm số ngày thực (không tính Lưu trú)
            num_days_llm = sum(1 for d in result if isinstance(d.get("day"), int))
            if num_days_llm == 0:
                print(f"[pipeline] itinerary_planner: LLM tạo {num_days_llm} ngày → dùng fallback")
                return fallback

            return _normalize_plan(result)
        except Exception as exc:
            print(f"[pipeline] itinerary_planner failed: {type(exc).__name__}: {exc}")
            return fallback

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
        session_summary = None
        if session_id:
            from app.db import sessions as db
            session = await db.get_session(session_id)
            if session:
                session_summary = session.summary
            if len(history) >= 10:
                asyncio.create_task(self._background_update_summary(session_id, history))

        t_start = time.perf_counter()

        loop = asyncio.get_running_loop()

        # 1. Phân tích ngữ cảnh hội thoại (Follow-up, Topic shift) bằng ConversationManager
        t_resolve_start = time.perf_counter()
        resolved = await loop.run_in_executor(None, self.conversation_manager.resolve_context, query, history)
        
        standalone_q = normalize_nfc(resolved["standalone_query"])
        is_topic_shift = resolved.get("is_topic_shift", False)
        
        # Nếu đổi chủ đề hoàn toàn, ta có thể clear history cho lần query này để tránh nhiễu
        if is_topic_shift:
            history = []
            
        t_resolve_done = time.perf_counter()
        print(f"[TIMING] resolve_context: {(t_resolve_done - t_resolve_start)*1000:.0f}ms")

        # 2. Phân tích Intent & Filter từ câu hỏi độc lập (standalone_q)
        analysis = await loop.run_in_executor(None, self.analyzer.analyze, standalone_q)
        t_analyzer = time.perf_counter()
        print(f"[TIMING] analyzer: {(t_analyzer - t_resolve_done)*1000:.0f}ms "
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
            chitchat_messages.append({"role": "user", "content": standalone_q})
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
            messages = _with_profile(_build_event_messages(standalone_q, events, history))
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
        skip_global_rerank = False
        prebuilt_context = None
        
        if intent == QueryIntent.ITINERARY_SEARCH:
            plan = await loop.run_in_executor(None, self._run_itinerary_planner, standalone_q)
            
            seen_itinerary_places = set()  # Dedup: ưu tiên địa điểm chưa xuất hiện
            all_itinerary_docs = []
            structured_context_parts = []
            
            for day_info in plan:
                day_num = day_info.get("day", 1)
                slots = day_info.get("slots", [])
                
                for slot in slots:
                    session = slot.get("session", "")
                    district = slot.get("district")
                    theme = slot.get("theme", "")
                    slot_query = slot.get("query", "")
                    col_type = slot.get("collection_type", "place")
                    
                    
                    slot_intent = QueryIntent.PLACE_SEARCH
                    if col_type == "restaurant":
                        slot_intent = QueryIntent.RESTAURANT_SEARCH
                    elif col_type == "hotel":
                        slot_intent = QueryIntent.HOTEL_SEARCH
                        
                    slot_filters = merged.copy() if merged else {}
                    if district:
                        slot_filters["district"] = district
                        
                    raw_docs = await retrieve_by_intent(
                        query=slot_query,
                        client=self.client,
                        encoder=self.encoder,
                        intent=slot_intent,
                        top_k_per_collection=15,
                        filters=slot_filters,
                        score_threshold=config.SCORE_THRESHOLD,
                    )
                    
                    # Nếu retrieve với district trả rỗng → mở rộng không giới hạn quận
                    if not raw_docs and district:
                        slot_filters_broad = slot_filters.copy()
                        slot_filters_broad["district"] = None
                        raw_docs = await retrieve_by_intent(
                            query=slot_query,
                            client=self.client,
                            encoder=self.encoder,
                            intent=slot_intent,
                            top_k_per_collection=15,
                            filters=slot_filters_broad,
                            score_threshold=config.SCORE_THRESHOLD,
                        )
                    
                    ranked_docs = await rerank_results(
                        results=raw_docs,
                        query=slot_query,
                        reranker=self.reranker,
                        top_k=15,
                        score_threshold=config.RERANK_SCORE_THRESHOLD,
                        intent=slot_intent,
                        extracted={"filters": slot_filters}
                    )
                    
                    # Ưu tiên chọn 2 địa điểm chưa xuất hiện trong lịch trình
                    slot_top_docs = []
                    for doc in ranked_docs:
                        name = doc.get_display_name().lower().strip()
                        if name and name not in seen_itinerary_places:
                            slot_top_docs.append(doc)
                        if len(slot_top_docs) >= 2:
                            break
                    
                    # Fallback: nếu DB cạn kiệt địa điểm mới, dùng lại doc tốt nhất
                    # để context không bị rỗng (tránh LLM giữ nguyên placeholder)
                    if not slot_top_docs and ranked_docs:
                        slot_top_docs = ranked_docs[:2]
                    elif not slot_top_docs and raw_docs:
                        slot_top_docs = raw_docs[:2]
                    
                    # Đánh dấu seen chỉ với docs thực sự mới
                    for doc in slot_top_docs:
                        name = doc.get_display_name().lower().strip()
                        if name:
                            seen_itinerary_places.add(name)
                    
                    all_itinerary_docs.extend(slot_top_docs)
                    
                    slot_context_str = _format_context(slot_top_docs, max_items=4, max_chars=1000)
                    
                    if slot_context_str.strip() and slot_context_str != "Không có thông tin phù hợp với yêu cầu.":
                        print(f"       ✅ {len(slot_top_docs)} địa điểm gợi ý cho buổi {session}")
                    else:
                        print(f"       ❌ Không có dữ liệu cho buổi {session}")
                    
                    slot_block = (
                        f"=== Ngày {day_num} - Buổi {session} ===\n"
                        f"Quận dự kiến: {district or 'Không chỉ định'}\n"
                        f"Chủ đề hoạt động: {theme}\n"
                        f"Thông tin địa điểm thực tế gợi ý từ database:\n"
                        f"{slot_context_str if slot_context_str.strip() else 'Không tìm thấy địa điểm thực tế phù hợp.'}"
                    )
                    structured_context_parts.append(slot_block)
            
            prebuilt_context = "\n\n".join(structured_context_parts)
            results = all_itinerary_docs
            skip_global_rerank = True
        else:
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
        print(f"[TIMING] retrieve_total: {(t_retrieve - t_retrieve_start)*1000:.0f}ms ({len(results)} hits)")

        # 4. BGE reranker (+ heuristic) → dedup. Heuristic chạy cả khi reranker tắt:
        t_rerank_start = time.perf_counter()
        if results and not skip_global_rerank:
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

        # 4.5. Exact name fallback cho SPECIFIC_SEARCH (bypass reranker)
        if intent == QueryIntent.SPECIFIC_SEARCH:
            search_name = " ".join(analysis.get("entity") or []).strip() or rewritten
            # raw_fallback = await exact_name_search(search_name, self.client)
            # if raw_fallback:
            #     # Ưu tiên fallback lên đầu, sau đó đến kết quả vector
            #     results = _dedup_by_display_name(raw_fallback + results)
            #     print(f"[pipeline] exact_name_search added {len(raw_fallback)} fallback results")

        # 4.55. SPECIFIC_SEARCH: nếu có khớp đúng tên → thu hẹp về đúng thực thể được hỏi;
        #       nếu chỉ có gần đúng → phát thông điệp gợi ý "có phải bạn muốn tìm..." rồi dừng.
        specific_no_exact = False
        if intent == QueryIntent.SPECIFIC_SEARCH and results:
            extracted_ent = " ".join(analysis.get("entity") or []).strip()
            exact = _find_exact_matches(standalone_q, results, extracted_entity=extracted_ent)
            if exact:
                results = exact[:config.MAX_ALTERNATIVES]
            else:
                specific_no_exact = True

        max_sources = 30 if intent == QueryIntent.ITINERARY_SEARCH else 10
        sources = [r.to_dict() for r in results[:max_sources]]
        yield {"type": "sources", "items": sources, "total": len(sources)}

        if specific_no_exact:
            # Không tìm thấy đúng thực thể — log để crawler bổ sung + trả gợi ý tương tự.
            if intent in _CRAWLABLE_INTENTS:
                try:
                    await log_missed_query(standalone_q, rewritten, intent.value, session_id)
                except Exception as _log_exc:
                    print(f"[pipeline] log_missed_query failed: {type(_log_exc).__name__}: {_log_exc}")
            
            display_name = " ".join(analysis.get("entity") or []).strip() or standalone_q
            yield {"type": "token", "text": _build_specific_fallback(display_name, results)}
            yield {"type": "done"}
            return

        # 4.6. Log missed query nếu không có kết quả và là intent crawlable
        if not results and intent in _CRAWLABLE_INTENTS:
            try:
                await log_missed_query(standalone_q, rewritten, intent.value, session_id)
            except Exception as _log_exc:
                print(f"[pipeline] log_missed_query failed: {type(_log_exc).__name__}: {_log_exc}")

        # 3.5. Fallback sang Gemini khi retrieve trả 0 kết quả (chỉ khi không dùng Gemini primary).
        # Khi USE_GEMINI_GENERATION=True, path này bị skip — Gemini primary xử lý luôn cả no-results.
        if not results and config.GEMINI_API_KEY and not config.USE_GEMINI_GENERATION:
            gemini_messages = _with_profile(_build_gemini_messages(standalone_q, history, intent, session_summary))
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

        # 4. Build prompt (hiển thị standalone_q gốc cho UX) — rẽ nhánh theo intent
        messages = _with_profile(_build_messages(
            standalone_q, results, history, intent, session_summary, prebuilt_context=prebuilt_context
        ))
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
            gen_messages = messages if results else _with_profile(_build_gemini_messages(standalone_q, history, intent, session_summary))
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
