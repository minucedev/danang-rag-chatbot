import sys

new_content = """def _build_messages(
    query: str,
    results: List[SearchResultSchema],
    history: list[dict],
    intent: QueryIntent,
) -> list[dict]:
    context = _format_context(results)
    
    if intent == QueryIntent.CHITCHAT or not results:
        messages = [{"role": "system", "content": _CHITCHAT_SYSTEM_PROMPT}]
        messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
        messages.append({"role": "user", "content": query})
        return messages

    hint = "Gợi ý TẤT CẢ các địa điểm có trong thông tin (tối đa 5 địa điểm phù hợp nhất)."
    
    if intent == QueryIntent.ITINERARY_SEARCH:
        hint = "Hãy lập lịch trình rõ ràng theo ngày. Kết hợp địa điểm, ăn uống và lưu trú phù hợp. Tuyệt đối không để một địa điểm xuất hiện 2 lần."
    elif intent == QueryIntent.REVIEW_SEARCH:
        hint = "Tổng hợp nhận xét, phân biệt điểm tốt và chưa tốt nếu có."
    elif intent == QueryIntent.ROOM_SEARCH:
        hint = "Tập trung vào thông tin phòng: loại phòng, tiện ích, diện tích, giá."
    elif intent == QueryIntent.SPECIFIC_SEARCH:
        query_lower = query.lower()
        asks_for_reviews = any(w in query_lower for w in ["đánh giá", "nhận xét", "review", "khen", "chê", "thấy sao", "tốt không"])
        if asks_for_reviews:
            hint = "CHỈ trả lời đúng thông tin được hỏi. Tổng hợp nhận xét thành điểm khen/chê."
        else:
            hint = "CHỈ trả lời đúng thông tin được hỏi (ví dụ hỏi giờ thì chỉ nói giờ). TUYỆT ĐỐI KHÔNG nhắc đến điểm đánh giá, không liệt kê lại địa chỉ/giá cả nếu khách không hỏi."

    user_prompt = f\"\"\"THÔNG TIN ĐỊA ĐIỂM DU LỊCH ĐÀ NẴNG:
{context}

---
Câu hỏi: {query}

Hướng dẫn bổ sung: {hint}\"\"\"

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(build_history_messages(history, config.MAX_HISTORY_TURNS))
    messages.append({"role": "user", "content": user_prompt})
    return messages
"""

with open('backend/app/rag/pipeline.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# indices 306 (line 307) to 360 (line 360). 
lines = lines[:306] + [new_content + '\\n'] + lines[360:]
with open('backend/app/rag/pipeline.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
