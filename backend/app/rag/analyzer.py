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
            "district": None,
            "min_rating": None,
            "max_price": None,
            "min_price": None,
            "star_rating": None,
            "price_level": None,
            "has_discount": None,
            
            # Extended restaurant / place filters
            "price_avg_vnd": None,
            "price_score": None,
            "quality_score": None,
            "service_score": None,
            "space_score": None,
            "location_score": None,
            "weather_dependent": None,
            
            # Extended hotel / room filters
            "check_in_time": None,
            "check_out_time": None,
            "room_count": None,
            "max_capacity": None,
            "image_count": None,
            "room_capacity": None,
            "area_m2": None,
            
            # Review / sentiment filters
            "sentiment_preference": None,
            "recency_min": None,
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

        # Extended restaurant / place filters
        f["price_avg_vnd"] = self._clean_price(raw.get("price_avg_vnd"))
        f["price_score"] = _to_float(raw.get("price_score"))
        f["quality_score"] = _to_float(raw.get("quality_score"))
        f["service_score"] = _to_float(raw.get("service_score"))
        f["space_score"] = _to_float(raw.get("space_score"))
        f["location_score"] = _to_float(raw.get("location_score"))
        
        if raw.get("weather_dependent") is not None:
            wd = str(raw["weather_dependent"]).strip().lower()
            if wd in {"có", "co", "yes", "true", "1"}:
                f["weather_dependent"] = "có"
            elif wd in {"không", "khong", "no", "false", "0"}:
                f["weather_dependent"] = "không"
            else:
                f["weather_dependent"] = None

        # Extended hotel / room filters
        f["check_in_time"] = raw.get("check_in_time")
        f["check_out_time"] = raw.get("check_out_time")
        f["room_count"] = _to_int(raw.get("room_count"))
        f["max_capacity"] = _to_int(raw.get("max_capacity"))
        f["image_count"] = _to_int(raw.get("image_count"))
        f["room_capacity"] = _to_int(raw.get("room_capacity"))
        f["area_m2"] = _to_float(raw.get("area_m2"))

        # Review / sentiment filters
        if raw.get("sentiment_preference"):
            sp = str(raw["sentiment_preference"]).strip().lower()
            if sp in {"positive", "tich cuc", "tích cực"}:
                f["sentiment_preference"] = "positive"
            elif sp in {"neutral", "trung lap", "trung lập"}:
                f["sentiment_preference"] = "neutral"
            elif sp in {"negative", "tieu cuc", "tiêu cực"}:
                f["sentiment_preference"] = "negative"
            else:
                f["sentiment_preference"] = None
        f["recency_min"] = _to_float(raw.get("recency_min"))

        for key in _LIST_FILTER_KEYS:
            f[key] = _split_tokens(raw.get(key))

        return f

    def analyze(self, query: str, history: Optional[list[dict]] = None) -> dict:
        """Sử dụng LLM kèm Few-shot để phân tích ngữ nghĩa chính xác cấu trúc JSON"""

        # System prompt: gộp Router (phân loại + needs_rag) và Extractor (filter giàu).
        system_content = (
            "Bạn là AI phân loại câu hỏi và trích xuất dữ liệu JSON cho chatbot du lịch Đà Nẵng.\n"
            "Chỉ trả về DUY NHẤT một khối JSON. Không giải thích, không markdown.\n\n"
            "QUY TẮC PHÂN LOẠI ƯU TIÊN:\n"
            "1. BẤT KỲ câu hỏi nào nhắc đến TÊN RIÊNG của thực thể (vd 'Chợ Cồn', 'Novotel Đà Nẵng', "
            "'Hải sản Năm Đảnh', 'Bà Nà Hills', 'A La Carte') hoặc thừa hưởng/tiếp nối từ thực thể "
            "đang được nói đến trong lịch sử hội thoại gần đây đều BẮT BUỘC là intent 'specific_search', "
            "kể cả khi hỏi địa chỉ/giờ mở cửa/phòng/review hay so sánh nhiều thực thể.\n"
            "2. Chỉ dùng 'hotel_search'/'restaurant_search'/'place_search'/'room_search' cho tìm kiếm "
            "CHUNG CHUNG (không nêu tên cụ thể và không có ngữ cảnh thực thể trước đó).\n"
            "3. 'needs_rag'=false CHỈ khi là chitchat/ngoài phạm vi du lịch Đà Nẵng "
            "(vd thời tiết, vé máy bay, 'bạn là ai').\n"
            "4. Câu hỏi về 'sự kiện/lễ hội/hoạt động/có gì chơi/có gì diễn ra' (thường kèm thời gian "
            "'gần đây/sắp tới/cuối tuần/tối nay/hôm nay') → intent 'event_search'.\n\n"
            "Schema JSON bắt buộc:\n"
            "{\n"
            '  "needs_rag": true | false,\n'
            '  "intent": "hotel_search" | "restaurant_search" | "place_search" | "room_search" | "review_search" | "event_search" | "itinerary_search" | "specific_search" | "chitchat" | "general",\n'
            '  "entity": ["tên riêng cụ thể được nhắc đến hoặc được kế thừa từ lịch sử hội thoại, [] nếu không có"],\n'
            '  "rewritten_query": "từ khóa ngắn để tạo embedding. KHÔNG chứa tên quận, giá, số sao, từ \'Đà Nẵng\', \'ở đâu\', \'mấy giờ\', \'review\'",\n'
            '  "filters": { "CHỈ ĐIỀN CÁC KEY BỘ LỌC CÓ GIÁ TRỊ. KHÔNG IN RA CÁC KEY NULL HAY [] ĐỂ TIẾT KIỆM THỜI GIAN" }\n'
            "}\n"
            "Các key bộ lọc hợp lệ (chỉ dùng khi câu hỏi có nhắc đến):\n"
            "district, min_rating, max_price, min_price, star_rating, price_level, cuisine, restaurant_type, restaurant_category, price_avg_vnd, price_score, quality_score, service_score, space_score, location_score, suitable_for, best_time_to_visit, visit_duration, tags, weather_dependent, check_in_time, check_out_time, cancellation_policy, children_policy, has_discount, room_count, max_capacity, image_count, room_capacity, bed_type, area_m2, room_view, amenities_room, sentiment_preference, recency_min."
        )

        history_str = ""
        if history:
            history_messages = []
            for msg in history[-6:]:
                role_display = "Người dùng" if msg.get("role") == "user" else "Trợ lý"
                content = msg.get("content") or ""
                if len(content) > 300:
                    content = content[:300] + "..."
                history_messages.append(f"{role_display}: {content}")
            history_str = "\n".join(history_messages)

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

### VÍ DỤ 12:
Người dùng: "Khách hàng nhận xét thế nào về quán hải sản Năm Đảnh?"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "specific_search",
  "entity": ["Hải sản Năm Đảnh"],
  "rewritten_query": "Hải sản Năm Đảnh",
  "filters": {{}}
}}

### VÍ DỤ 13 (CÓ LỊCH SỬ HỘI THOẠI):
Lịch sử hội thoại:
Người dùng: Khách hàng nhận xét thế nào về quán hải sản Năm Đảnh?
Trợ lý: Quán hải sản Năm Đảnh được đánh giá cao...
Người dùng: "vậy quán này mở cửa lúc mấy giờ"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "specific_search",
  "entity": ["Hải sản Năm Đảnh"],
  "rewritten_query": "Hải sản Năm Đảnh giờ mở cửa",
  "filters": {{}}
}}

### VÍ DỤ 14 (CÓ LỊCH SỬ HỘI THOẠI):
Lịch sử hội thoại:
Người dùng: tôi muốn biết nhận xét của khách hàng về Le Sands Oceanfront Danang Hotel
Trợ lý: Khách hàng rất hài lòng với Le Sands Oceanfront Danang Hotel...
Người dùng: "vậy khách sạn có những loại phòng nào"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "specific_search",
  "entity": ["Le Sands Oceanfront Danang Hotel"],
  "rewritten_query": "Le Sands Oceanfront Danang Hotel loại phòng",
  "filters": {{}}
}}

### VÍ DỤ 15 (HỎI CHUNG CHUNG KHI CÓ LỊCH SỬ):
Lịch sử hội thoại:
Người dùng: tôi muốn biết nhận xét của khách hàng về Le Sands Oceanfront Danang Hotel
Trợ lý: Khách hàng rất hài lòng với Le Sands Oceanfront Danang Hotel...
Người dùng: "khách sạn nào ở Hải Châu có bể bơi"
Trả về JSON:
{{
  "needs_rag": true,
  "intent": "hotel_search",
  "entity": [],
  "rewritten_query": "khách sạn có bể bơi",
  "filters": {{"district": "hai chau"}}
}}
"""

        if history_str:
            user_prompt += f"""
### BÀI TẬP THỰC TẾ (CÓ LỊCH SỬ HỘI THOẠI):
Lịch sử hội thoại:
{history_str}
Người dùng: "{query}"
Trả về JSON:"""
        else:
            user_prompt += f"""
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
