import json
import logging
import re
from typing import Optional

from app.rag.memory import build_history_messages
from app import config

logger = logging.getLogger(__name__)

_RESOLVE_CONTEXT_PROMPT = """Bạn là chuyên gia ngôn ngữ và am hiểu ngữ cảnh.
Nhiệm vụ: Phân tích câu hỏi mới nhất của người dùng dựa trên Lịch sử Hội thoại.

Hãy trả về JSON có định dạng sau:
{{
  "is_followup": true/false, // true nếu câu hỏi mới đang hỏi thêm thông tin về thực thể/chủ đề trong lịch sử (chứa đại từ: nó, chỗ đó, giá bao nhiêu, ở đâu...).
  "is_topic_shift": true/false, // true nếu người dùng chuyển hoàn toàn sang chủ đề/địa điểm mới không liên quan.
  "standalone_query": "Câu hỏi hoàn chỉnh, độc lập. Nếu là followup, hãy thay thế các đại từ (nó, chỗ đó,...) bằng tên thực thể cụ thể từ lịch sử. Nếu không phải followup, giữ nguyên câu hỏi gốc."
}}
CHỈ TRẢ VỀ JSON HỢP LỆ, KHÔNG GIẢI THÍCH THÊM BẤT CỨ LỜI NÀO.

### VÍ DỤ 1:
Lịch sử hội thoại gần đây:
USER: Khách sạn Novotel Đà Nẵng có tốt không?
ASSISTANT: Khách sạn Novotel rất tốt, đạt chuẩn 5 sao.

Câu hỏi mới: "Giá bao nhiêu?"
Trả về JSON:
```json
{{
  "is_followup": true,
  "is_topic_shift": false,
  "standalone_query": "Khách sạn Novotel Đà Nẵng giá bao nhiêu?"
}}
```

### VÍ DỤ 2:
Lịch sử hội thoại gần đây:
USER: quán hải sản Năm Đảnh ở đâu?
ASSISTANT: Quán nằm ở Thọ Quang, Sơn Trà.

Câu hỏi mới: "có chỗ đậu xe không"
Trả về JSON:
```json
{{
  "is_followup": true,
  "is_topic_shift": false,
  "standalone_query": "quán hải sản Năm Đảnh có chỗ đậu xe không"
}}
```

### VÍ DỤ 3:
Lịch sử hội thoại gần đây:
USER: tôi cần biết thông tin về Khách sạn Novotel Danang Premier Han River
ASSISTANT: Đến Novotel Danang Premier Han River, một khách sạn 5 sao...

Câu hỏi mới: "Khách sạn này có những loại phòng nào và giá của từng phòng"
Trả về JSON:
```json
{{
  "is_followup": true,
  "is_topic_shift": false,
  "standalone_query": "Khách sạn Novotel Danang Premier Han River có những loại phòng nào và giá của từng phòng"
}}
```
### VÍ DỤ 4:
Lịch sử hội thoại gần đây:
USER: Phòng khách sạn dưới 1 triệu mỗi đêm?
ASSISTANT: Dưới 1 triệu mỗi đêm, bạn có thể tham khảo Khách sạn A, Khách sạn B...

Câu hỏi mới: "còn khách sạn nào khác không?"
Trả về JSON:
```json
{{
  "is_followup": true,
  "is_topic_shift": false,
  "standalone_query": "Ngoài những khách sạn trên còn khách sạn nào khác không"
}}
```

### BÀI TẬP THỰC TẾ:
Lịch sử hội thoại gần đây:
{history_str}

Câu hỏi mới: "{query}"
Trả về JSON:
"""

_SUMMARIZE_HISTORY_PROMPT = """Bạn là chuyên gia phân tích ngữ cảnh.
Hãy tóm tắt lịch sử hội thoại dưới đây thành định dạng JSON để lưu trữ ngữ cảnh dài hạn:
{history_str}

Cấu trúc JSON mong muốn:
{{
  "current_topic": "Chủ đề chính đang thảo luận",
  "mentioned_entities": ["Tên địa điểm 1", "Tên địa điểm 2"],
  "user_preferences": {{
     "budget": "Khoảng giá (nếu có)",
     "district": "Quận/Khu vực (nếu có)"
  }}
}}
CHỈ TRẢ VỀ JSON HỢP LỆ, KHÔNG GIẢI THÍCH.
"""

def extract_json(text: str) -> dict:
    """Trích xuất khối JSON từ output của LLM."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1)
    else:
        # Xóa prefix/suffix dư thừa
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    
    try:
        return json.loads(text)
    except Exception as e:
        logger.error(f"[ConversationManager] JSON parse error: {e}. Raw text: {text}")
        return {}


class ConversationManager:
    """Quản lý ngữ cảnh hội thoại, lịch sử, và resolve multi-turn queries."""
    
    def __init__(self, llm):
        self.llm = llm

    def resolve_context(self, query: str, history: list[dict]) -> dict:
        """
        Sử dụng LLM để phân tích query có phải là followup hay topic shift không.
        Sinh ra standalone_query.
        Hàm này là blocking (chạy đồng bộ), nên chạy trong executor.
        """
        if not history:
            return {
                "is_followup": False,
                "is_topic_shift": False,
                "standalone_query": query
            }

        history_msgs = build_history_messages(history, max_turns=config.MAX_HISTORY_TURNS)
        if not history_msgs:
            return {
                "is_followup": False,
                "is_topic_shift": False,
                "standalone_query": query
            }

        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history_msgs])

        prompt = _RESOLVE_CONTEXT_PROMPT.format(history_str=history_str, query=query)
        messages = [{"role": "user", "content": prompt}]

        raw_out = ""
        try:
            if callable(self.llm): # litellm style
                response = self.llm(
                    messages=messages,
                    max_tokens=256,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                raw_out = response["choices"][0]["message"]["content"]
            else: # llama.cpp style
                response = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=256,
                    temperature=0.0,
                )
                raw_out = response["choices"][0]["message"]["content"]
                
            parsed = extract_json(raw_out)
            
            # Đảm bảo fallback an toàn nếu LLM trả thiếu
            return {
                "is_followup": bool(parsed.get("is_followup", False)),
                "is_topic_shift": bool(parsed.get("is_topic_shift", False)),
                "standalone_query": parsed.get("standalone_query", query)
            }
        except Exception as e:
            logger.error(f"[ConversationManager] Failed to resolve context: {e}")
            return {
                "is_followup": False,
                "is_topic_shift": False,
                "standalone_query": query
            }

    def summarize_history(self, history: list[dict]) -> str:
        """Tạo summary từ lịch sử hội thoại."""
        if not history:
            return ""
            
        history_msgs = build_history_messages(history, max_turns=20) # Lấy nhiều turn hơn để tóm tắt
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history_msgs])

        prompt = _SUMMARIZE_HISTORY_PROMPT.format(history_str=history_str)
        messages = [{"role": "user", "content": prompt}]

        try:
            if callable(self.llm):
                response = self.llm(
                    messages=messages,
                    max_tokens=300,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                raw_out = response["choices"][0]["message"]["content"]
            else:
                response = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=300,
                    temperature=0.0,
                )
                raw_out = response["choices"][0]["message"]["content"]
                
            parsed = extract_json(raw_out)
            return json.dumps(parsed, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ConversationManager] Failed to summarize history: {e}")
            return ""

def build_final_context_prompt(summary_json: Optional[str], history: list[dict], max_turns=config.MAX_HISTORY_TURNS) -> list[dict]:
    """
    Xây dựng list messages chứa ngữ cảnh để đưa vào Generator LLM.
    """
    messages = []
    if summary_json:
        try:
            summary = json.loads(summary_json)
            summary_text = (
                "SESSION SUMMARY:\n"
                f"- Chủ đề: {summary.get('current_topic', '')}\n"
                f"- Thực thể đã nhắc tới: {', '.join(summary.get('mentioned_entities', []))}\n"
                f"- Sở thích user: {json.dumps(summary.get('user_preferences', {}), ensure_ascii=False)}"
            )
            messages.append({"role": "system", "content": summary_text})
        except:
            pass
            
    # Lấy recent history
    history_msgs = build_history_messages(history, max_turns=max_turns)
    messages.extend(history_msgs)
    return messages



