from __future__ import annotations
import json
import re
from typing import Any, Optional

from app import config
from app.rag.intent import QueryIntent

VALID_DISTRICTS = {
    "hai chau", "son tra", "thanh khe", "ngu hanh son", "cam le", "hoa vang", "lien chieu",
}

# Các trường filter dạng list (ported từ notebook) — dùng cho rerank heuristics.
_LIST_FILTER_KEYS = [
    "cuisine", "restaurant_type", "restaurant_category",
    "suitable_for", "best_time_to_visit", "visit_duration", "tags",
    "room_view", "bed_type", "amenities_room",
    "cancellation_policy", "children_policy",
]

# Tín hiệu "sự kiện" rõ ràng → ép intent=event_search dù analyzer (model nhỏ 0.5B) phân loại
# sai. Bao cả có dấu lẫn không dấu, không phân biệt hoa thường.
_EVENT_RE = re.compile(
    r"(sự kiện|su kien|lễ hội|le hoi|festival|\bevent\b|có gì chơi|co gi choi|"
    r"có gì diễn ra|co gi dien ra|hoạt động gì|hoat dong gi)",
    re.IGNORECASE,
)


def _split_tokens(value: Any) -> list[str]:
    """Chuẩn hóa giá trị (str hoặc list) thành list token chữ thường, đã dedup."""
    if value is None:
        return []
    parts = value if isinstance(value, list) else re.split(r"[\/;,|]|\s-\s", str(value))
    tokens: list[str] = []
    for part in parts:
        if part is None:
            continue
        for sub in str(part).split(","):
            item = re.sub(r"\s+", " ", sub).strip().lower()
            if item:
                tokens.append(item)
    seen: set[str] = set()
    unique: list[str] = []
    for tok in tokens:
        if tok not in seen:
            unique.append(tok)
            seen.add(tok)
    return unique


def _normalize_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in {"true", "yes", "có", "co", "1"}:
        return True
    if v in {"false", "no", "không", "khong", "0"}:
        return False
    return None


def _normalize_price_level(value: Any) -> Optional[str]:
    if value:
        v = str(value).strip().lower()
        if v in {"low", "mid", "high"}:
            return v
        if "rẻ" in v or "binh dan" in v or "bình dân" in v or "sinh viên" in v:
            return "low"
        if "trung" in v or "vừa" in v:
            return "mid"
        if "cao" in v or "sang" in v or "đắt" in v:
            return "high"
    return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


class LLMQueryAnalyzer:
    """LLM-based query analysis via llama.cpp.

    One greedy LLM pass before retrieval → {intent, rewritten_query, filters}.
    `analyze` is intentionally synchronous/blocking — the caller
    (pipeline.answer_stream) runs it via loop.run_in_executor so the asyncio
    event loop stays free for disconnect checks / SSE heartbeat.
    """

    def __init__(self, llm) -> None:
        self.llm = llm

    def _clean_price(self, value) -> Optional[int]:
        """Xử lý và chuẩn hóa mọi định dạng số tiền từ LLM về VND"""
        if value is None or value == "" or str(value).lower() == "null":
            return None
        try:
            # Chuyển về chuỗi chữ thường, xóa dấu phân cách hàng nghìn (dấu phẩy, dấu chấm)
            val_str = str(value).lower().strip()
            val_str = val_str.replace(",", "").replace(".", "")

            # Trích xuất tất cả các chữ số liên tiếp đầu tiên tìm thấy
            digits_match = re.search(r'\d+', val_str)
            if not digits_match:
                return None

            val = int(digits_match.group(0))

            # Bắt các từ khóa hàng triệu, hàng nghìn (củ, triệu, tr, k)
            if "triệu" in val_str or "trieu" in val_str or "củ" in val_str or "cu" in val_str or "tr" in val_str:
                # Nếu LLM trả về đúng "2000000" nhưng vẫn viết chữ "triệu" phía sau, tránh nhân đôi
                if val < 10000:
                    val = val * 1_000_000
            elif "ngàn" in val_str or "nghin" in val_str or "k" in val_str:
                if val < 10000:
                    val = val * 1_000

            # Giới hạn an toàn: Nếu số tiền quá nhỏ (< 5000) và không có hậu tố, khả năng cao LLM viết tắt (ví dụ: 200 tức là 200k)
            if val < 5000 and val > 0:
                val = val * 1_000  # Tự động đưa về nghìn đồng nếu là hàng quán ăn uống
                # Clause trơ: str(self) là repr mặc định nên không bao giờ chứa
                # "hotel" → không kích hoạt (giữ verbatim theo notebook).
                if val < 50000 and "hotel" in str(self).lower():  # Khách sạn thì có thể là trăm k
                    val = val * 10

            # Trần bảo vệ hệ thống tránh ảo giác quá lớn
            if val > 200_000_000:
                return 200_000_000

            return val
        except Exception as e:
            print(f"  [DEBUG] Lỗi ép kiểu giá: {e}")
            return None

    @staticmethod
    def _empty_filters() -> dict:
        """Filter rỗng đầy đủ key — dùng cho fallback và làm base cho _clean_filters."""
        f: dict = {
            "district": None, "min_rating": None, "max_price": None, "min_price": None,
            "star_rating": None, "price_level": None, "has_discount": None,
        }
        for k in _LIST_FILTER_KEYS:
            f[k] = []
        return f

    def _clean_filters(self, raw: dict) -> dict:
        """Chuẩn hóa filter thô từ LLM về đúng kiểu; key thiếu lấy default rỗng."""
        f = self._empty_filters()

        district = raw.get("district")
        if district:
            district = str(district).lower().strip()
            f["district"] = district if district in VALID_DISTRICTS else None

        f["min_rating"] = _to_float(raw.get("min_rating"))
        f["max_price"] = self._clean_price(raw.get("max_price"))
        f["min_price"] = self._clean_price(raw.get("min_price"))
        f["star_rating"] = _to_int(raw.get("star_rating"))
        f["price_level"] = _normalize_price_level(raw.get("price_level"))
        f["has_discount"] = _normalize_bool(raw.get("has_discount"))

        for key in _LIST_FILTER_KEYS:
            f[key] = _split_tokens(raw.get(key))

        return f

    def analyze(self, query: str) -> dict:
        """Sử dụng LLM kèm Few-shot để phân tích ngữ nghĩa chính xác cấu trúc JSON"""

        # System prompt: gộp Router (phân loại + needs_rag) và Extractor (filter giàu).
        system_content = (
            "Bạn là AI phân loại câu hỏi và trích xuất dữ liệu JSON cho chatbot du lịch Đà Nẵng.\n"
            "Chỉ trả về DUY NHẤT một khối JSON. Không giải thích, không markdown.\n\n"
            "QUY TẮC PHÂN LOẠI ƯU TIÊN:\n"
            "1. BẤT KỲ câu hỏi nào nhắc đến TÊN RIÊNG của thực thể (vd 'Chợ Cồn', 'Novotel Đà Nẵng', "
            "'Hải sản Năm Đảnh', 'Bà Nà Hills', 'A La Carte') đều BẮT BUỘC là intent 'specific_search', "
            "kể cả khi hỏi địa chỉ/giờ mở cửa/phòng/review hay so sánh nhiều thực thể.\n"
            "2. Chỉ dùng 'hotel_search'/'restaurant_search'/'place_search'/'room_search' cho tìm kiếm "
            "CHUNG CHUNG (không nêu tên cụ thể).\n"
            "3. 'needs_rag'=false CHỈ khi là chitchat/ngoài phạm vi du lịch Đà Nẵng "
            "(vd thời tiết, vé máy bay, 'bạn là ai').\n"
            "4. Câu hỏi về 'sự kiện/lễ hội/hoạt động/có gì chơi/có gì diễn ra' (thường kèm thời gian "
            "'gần đây/sắp tới/cuối tuần/tối nay/hôm nay') → intent 'event_search'.\n\n"
            "Schema JSON bắt buộc:\n"
            "{\n"
            '  "needs_rag": true | false,\n'
            '  "intent": "hotel_search" | "restaurant_search" | "place_search" | "room_search" | "review_search" | "event_search" | "itinerary_search" | "specific_search" | "chitchat" | "general",\n'
            '  "entity": ["tên riêng cụ thể được nhắc đến, [] nếu không có"],\n'
            '  "rewritten_query": "từ khóa ngắn để tạo embedding. KHÔNG chứa tên quận, giá, số sao, từ \'Đà Nẵng\', \'ở đâu\', \'mấy giờ\', \'review\'",\n'
            '  "filters": {\n'
            '    "district": "hai chau" | "son tra" | "thanh khe" | "ngu hanh son" | "cam le" | "hoa vang" | "lien chieu" | null,\n'
            '    "min_rating": "float thang 1-10. \'trên 8 điểm\'->8.0; theo sao \'4.5 sao\'->9.0 (số sao * 2)" | null,\n'
            '    "max_price": "int VND. \'1 triệu\'->1000000, \'500k\'->500000" | null,\n'
            '    "min_price": int_VND | null,\n'
            '    "star_rating": "int 1-5, số sao khách sạn" | null,\n'
            '    "price_level": "low" | "mid" | "high" | null,\n'
            '    "cuisine": ["vd hải sản, mì quảng, lẩu, cà phê"],\n'
            '    "restaurant_type": ["vd buffet, quán ăn, nhà hàng, café"],\n'
            '    "restaurant_category": [], "suitable_for": ["vd gia đình, cặp đôi, nhóm bạn"],\n'
            '    "best_time_to_visit": ["vd sáng, tối, cuối tuần"], "visit_duration": ["vd 1-2 giờ, cả ngày"],\n'
            '    "tags": ["vd sống ảo, check-in, view biển, tâm linh"],\n'
            '    "room_view": ["vd sea view, city view"], "bed_type": ["vd double bed, king bed"],\n'
            '    "amenities_room": ["vd wifi, bathtub, balcony"],\n'
            '    "cancellation_policy": [], "children_policy": [], "has_discount": true | false | null\n'
            "  }\n"
            "}\n"
            "Chỉ điền filter khi câu hỏi nêu rõ; còn lại để null hoặc []."
        )

        # Few-shot: dạy teencode, hướng giá (đổ lại/trở lên), needs_rag, entity, filter giàu.
        user_prompt = f"""Hãy phân tích câu hỏi người dùng sau đây dựa trên các ví dụ mẫu:

### VÍ DỤ 1:
Người dùng: "Có ks nào xịn xịn cỡ 2 củ ở q. Hải Châu ko shop?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "hotel_search",
  "entity": [],
  "rewritten_query": "khách sạn",
  "filters": {{"district": "hai chau", "max_price": 2000000, "price_level": "high"}}
}}

### VÍ DỤ 2:
Người dùng: "Cho mình xin vài địa chỉ ăn hải sản ngon mà giá khoảng 1 triệu đổ lại nhé"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "restaurant_search",
  "entity": [],
  "rewritten_query": "quán hải sản ngon",
  "filters": {{"max_price": 1000000, "cuisine": ["hải sản"]}}
}}

### VÍ DỤ 3:
Người dùng: "quán ăn nào ở ngũ hành sơn được đánh giá trên 4.5 sao"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "restaurant_search",
  "entity": [],
  "rewritten_query": "quán ăn ngon",
  "filters": {{"district": "ngu hanh son", "min_rating": 9.0}}
}}

### VÍ DỤ 4:
Người dùng: "Tìm phòng khách sạn 4 sao view biển có giường đôi cho gia đình ở Sơn Trà"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "hotel_search",
  "entity": [],
  "rewritten_query": "khách sạn",
  "filters": {{"district": "son tra", "star_rating": 4, "room_view": ["sea view"], "bed_type": ["double bed"], "suitable_for": ["gia đình"]}}
}}

### VÍ DỤ 5:
Người dùng: "So sánh khách sạn Novotel Đà Nẵng và A La Carte cái nào tốt hơn?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "specific_search",
  "entity": ["Novotel Đà Nẵng", "A La Carte"],
  "rewritten_query": "Novotel Đà Nẵng A La Carte",
  "filters": {{}}
}}

### VÍ DỤ 6:
Người dùng: "Chợ Cồn mở cửa mấy giờ?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "specific_search",
  "entity": ["Chợ Cồn"],
  "rewritten_query": "Chợ Cồn",
  "filters": {{}}
}}

### VÍ DỤ 7:
Người dùng: "Tối nay ở Hải Châu có lễ hội gì không?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "event_search",
  "entity": [],
  "rewritten_query": "lễ hội sự kiện",
  "filters": {{"district": "hai chau", "best_time_to_visit": ["tối"]}}
}}

### VÍ DỤ 8:
Người dùng: "Gợi ý lịch trình 3 ngày 2 đêm Đà Nẵng cho cặp đôi"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "itinerary_search",
  "entity": [],
  "rewritten_query": "lịch trình khách sạn nhà hàng địa điểm",
  "filters": {{"suitable_for": ["cặp đôi"]}}
}}

### VÍ DỤ 9:
Người dùng: "Bạn là ai và thời tiết Đà Nẵng tháng 7 thế nào?"
Trả về JSON:
{{
  "needs_rag": false,
  "intent": "chitchat",
  "entity": [],
  "rewritten_query": "",
  "filters": {{}}
}}

### VÍ DỤ 10:
Người dùng: "Đà Nẵng gần đây có sự kiện gì không?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "event_search",
  "entity": [],
  "rewritten_query": "sự kiện",
  "filters": {{}}
}}

### VÍ DỤ 11:
Người dùng: "Cuối tuần này có hoạt động gì vui ở Đà Nẵng?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "event_search",
  "entity": [],
  "rewritten_query": "sự kiện hoạt động",
  "filters": {{"best_time_to_visit": ["cuối tuần"]}}
}}

### BÀI TẬP THỰC TẾ:
Người dùng: "{query}"
Trả về JSON:"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ]

        _fallback = {
            "needs_rag": True,
            "intent": QueryIntent.GENERAL,
            "entity": [],
            "rewritten_query": query,
            "filters": self._empty_filters(),
            "source": "LLM_Fallback",
        }

        for attempt in range(2):
            try:
                completion = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=config.ANALYZER_MAX_TOKENS,
                    temperature=0.0,
                    top_p=1.0,
                    stream=False,
                )
                gen_text = completion["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"  [DEBUG] LLM call failed: {e}. Applying fallback.")
                return _fallback

            try:
                # Khử nhiễu văn bản bọc ngoài JSON
                json_match = re.search(r'\{.*\}', gen_text, re.DOTALL)
                raw = json_match.group(0) if json_match else gen_text
                parsed_json = json.loads(raw)

                # Đảm bảo dọn dẹp và giữ đúng cấu trúc filter mong muốn
                raw_filters = parsed_json.get("filters", {})
                if not isinstance(raw_filters, dict):
                    raw_filters = {}

                cleaned_filters = self._clean_filters(raw_filters)

                try:
                    intent_str = parsed_json.get("intent", "general")
                    intent_enum = QueryIntent(intent_str)
                except ValueError:
                    intent_enum = QueryIntent.GENERAL

                # needs_rag=false → ép về CHITCHAT (đồng bộ với nhánh chitchat ở pipeline)
                needs_rag = _normalize_bool(parsed_json.get("needs_rag"))
                if needs_rag is None:
                    needs_rag = intent_enum != QueryIntent.CHITCHAT
                if not needs_rag:
                    intent_enum = QueryIntent.CHITCHAT

                # Chốt tất định: tín hiệu sự kiện rõ ràng → event_search, kể cả khi analyzer
                # (model nhỏ 0.5B) phân loại nhầm hoặc trả needs_rag=false. KHÔNG đè
                # specific_search (hỏi đích danh 1 thực thể) để không cướp câu hỏi đó.
                if intent_enum not in (QueryIntent.EVENT_SEARCH, QueryIntent.SPECIFIC_SEARCH) \
                        and _EVENT_RE.search(query):
                    intent_enum = QueryIntent.EVENT_SEARCH
                    needs_rag = True

                # entity[] thay cho extract_specific_entities riêng của notebook
                raw_entity = parsed_json.get("entity")
                if isinstance(raw_entity, list):
                    entity = [str(x).strip() for x in raw_entity if str(x).strip()]
                elif raw_entity:
                    entity = [str(raw_entity).strip()]
                else:
                    entity = []

                # rewritten_query: nhận cả alias core_query/semantic_query của notebook
                rewritten = (
                    parsed_json.get("rewritten_query")
                    or parsed_json.get("semantic_query")
                    or parsed_json.get("core_query")
                    or query
                )

                return {
                    "needs_rag": needs_rag,
                    "intent": intent_enum,
                    "entity": entity,
                    "rewritten_query": rewritten,
                    "filters": cleaned_filters,
                    "source": "LLM",
                }

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if attempt == 0:
                    print(f"  [DEBUG] Parse attempt 1 failed ({e}), retrying...")
                    continue
                print(f"  [DEBUG] Parse failed after retry: {e}. Applying fallback.")

        return _fallback
