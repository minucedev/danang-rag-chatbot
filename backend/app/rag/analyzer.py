from __future__ import annotations
import json
import re
from typing import Optional

from app.rag.intent import QueryIntent


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

    def analyze(self, query: str) -> dict:
        """Sử dụng LLM kèm Few-shot để phân tích ngữ nghĩa chính xác cấu trúc JSON"""

        # System prompt định hình rõ ràng vai trò và cung cấp ví dụ chuẩn
        system_content = (
            "Bạn là một AI chuyên trích xuất dữ liệu JSON cấu trúc từ câu hỏi du lịch Đà Nẵng.\n"
            "Chỉ trả về DUY NHẤT một khối JSON. Không giải thích, không thêm text ngoài JSON.\n"
            "Cấu trúc JSON bắt buộc phải tuân theo chính xác schema sau:\n"
            "{\n"
            '  "intent": "hotel_search" | "restaurant_search" | "place_search" | "review_search" | "event_search" | "itinerary_search" | "chitchat" | "general",\n'
            '  "rewritten_query": "chuỗi từ khóa tìm kiếm rút gọn để tạo embedding",\n'
            '  "filters": {\n'
            '    "district": "son tra" | "hai chau" | "ngu hanh son" | "cam le" | "lien chieu" | "thanh khe" | null,\n'
            '    "min_rating": float | null,\n'
            '    "max_price": int_VND | null,\n'
            '    "min_price": int_VND | null\n'
            "  }\n"
            "}"
        )

        # Cung cấp ví dụ Few-shot để mô hình học cách xử lý teencode và hướng giá (đổ lại/trở lên)
        user_prompt = f"""Hãy phân tích câu hỏi người dùng sau đây dựa trên các ví dụ mẫu:

### VÍ DỤ 1:
Người dùng: "Có ks nào xịn xịn cỡ 2 củ ở q. Hải Châu ko shop?"
Trả về JSON:
{{
  "intent": "hotel_search",
  "rewritten_query": "khách sạn xịn cao cấp Hải Châu",
  "filters": {{
    "district": "hai chau",
    "min_rating": null,
    "max_price": 2000000,
    "min_price": null
  }}
}}

### VÍ DỤ 2:
Người dùng: "Cho mình xin vài địa chỉ ăn hải sản ngon mà giá khoảng 1 triệu đổ lại nhé"
Trả về JSON:
{{
  "intent": "restaurant_search",
  "rewritten_query": "nhà hàng hải sản ngon",
  "filters": {{
    "district": null,
    "min_rating": null,
    "max_price": 1000000,
    "min_price": null
  }}
}}

### VÍ DỤ 3:
Người dùng: "quán ăn nào ở ngũ hành sơn được đánh giá trên 4.5 sao"
Trả về JSON:
{{
  "intent": "restaurant_search",
  "rewritten_query": "quán ăn ngon ngũ hành sơn",
  "filters": {{
    "district": "ngu hanh son",
    "min_rating": 4.5,
    "max_price": null,
    "min_price": null
  }}
}}

### VÍ DỤ 4:
Người dùng: "Tôi muốn biết thông tin về khách sạn Sala Danang Beach Hotel"
Trả về JSON:
{{
  "intent": "specific_search",
  "rewritten_query": "Sala Danang Beach Hotel",
  "filters": {{
    "district": null,
    "min_rating": null,
    "max_price": null,
    "min_price": null
  }}
}}

### VÍ DỤ 5:
Người dùng: "Tối nay ở Hải Châu có lễ hội gì không?"
Trả về JSON:
{{
  "intent": "event_search",
  "rewritten_query": "lễ hội sự kiện tối nay Hải Châu",
  "filters": {{
    "district": "hai chau",
    "min_rating": null,
    "max_price": null,
    "min_price": null
  }}
}}

### VÍ DỤ 6:
Người dùng: "Cuối tuần này Đà Nẵng có concert hay sự kiện gì vui không?"
Trả về JSON:
{{
  "intent": "event_search",
  "rewritten_query": "concert sự kiện cuối tuần Đà Nẵng",
  "filters": {{
    "district": null,
    "min_rating": null,
    "max_price": null,
    "min_price": null
  }}
}}

### VÍ DỤ 7:
Người dùng: "Gợi ý lịch trình 3 ngày 2 đêm Đà Nẵng cho cặp đôi"
Trả về JSON:
{{
  "intent": "itinerary_search",
  "rewritten_query": "lịch trình 3 ngày cặp đôi Đà Nẵng khách sạn nhà hàng địa điểm",
  "filters": {{
    "district": null,
    "min_rating": null,
    "max_price": null,
    "min_price": null
  }}
}}

### VÍ DỤ 8:
Người dùng: "Bạn là ai và có thể giúp gì cho mình?"
Trả về JSON:
{{
  "intent": "chitchat",
  "rewritten_query": "",
  "filters": {{
    "district": null,
    "min_rating": null,
    "max_price": null,
    "min_price": null
  }}
}}

### BÀI TẬP THỰC TẾ:
Người dùng: "{query}"
Trả về JSON:"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ]

        _fallback = {
            "intent": QueryIntent.GENERAL,
            "rewritten_query": query,
            "filters": {"district": None, "min_rating": None, "max_price": None, "min_price": None},
            "source": "LLM_Fallback",
        }

        for attempt in range(2):
            try:
                completion = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=256,
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

                cleaned_filters = {
                    "district": raw_filters.get("district"),
                    "min_rating": raw_filters.get("min_rating"),
                    "max_price": self._clean_price(raw_filters.get("max_price")),
                    "min_price": self._clean_price(raw_filters.get("min_price"))
                }

                # Chuẩn hóa district text đầu ra
                if cleaned_filters["district"]:
                    cleaned_filters["district"] = str(cleaned_filters["district"]).lower().strip()

                try:
                    intent_str = parsed_json.get("intent", "general")
                    intent_enum = QueryIntent(intent_str)
                except ValueError:
                    intent_enum = QueryIntent.GENERAL

                return {
                    "intent": intent_enum,
                    "rewritten_query": parsed_json.get("rewritten_query", query),
                    "filters": cleaned_filters,
                    "source": "LLM",
                }

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if attempt == 0:
                    print(f"  [DEBUG] Parse attempt 1 failed ({e}), retrying...")
                    continue
                print(f"  [DEBUG] Parse failed after retry: {e}. Applying fallback.")

        return _fallback
