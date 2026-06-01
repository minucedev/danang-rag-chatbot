# Phân tích cải tiến Query Routing và Advanced RAG

Tài liệu này tổng hợp các ý tưởng cải tiến cho chatbot du lịch Đà Nẵng, đối chiếu với code hiện tại và chỉ ra phần nào đã có, phần nào còn thiếu. Cấu trúc mỗi mục gồm: vấn đề, giải pháp hiện tại, giải pháp đề xuất, lý do và bối cảnh áp dụng.

## 1. Query Routing & Logic

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Bot có nhiều nguồn trả lời: RAG nội bộ, Gemini fallback, và ý tưởng API sự kiện/thời tiết. Nếu không có bộ định tuyến rõ ràng, mọi câu hỏi dễ bị đẩy vào RAG trước, kể cả câu ngoài domain hoặc câu cần dữ liệu thời gian thực. |
| Giải pháp hiện tại | Đã có `LLMQueryAnalyzer`: trước khi retrieve, backend dùng LLM để phân loại intent, rewrite query và trích filter. Sau đó route vào collection Qdrant phù hợp như hotel, restaurant, place, review. |
| Giải pháp đề xuất | Nâng cấp thành router cấp nguồn dữ liệu: `RAG`, `EVENT_API`, `WEATHER_API`, `GEMINI_OUT_OF_DOMAIN`. Analyzer nên trả thêm field như `route` hoặc `source_type`, không chỉ `intent`. |
| Lý do | Intent hiện tại chỉ route trong phạm vi RAG collections. Nó chưa quyết định dùng API, Gemini hay RAG. Vì vậy câu hỏi như "Tối nay ở Hải Châu có lễ hội gì?" chưa được route sang API sự kiện. |
| Bối cảnh áp dụng | Áp dụng khi hệ thống có nhiều nguồn dữ liệu khác nhau: dữ liệu tĩnh nội bộ, dữ liệu realtime và câu hỏi ngoài phạm vi du lịch. Đây là phần tốt để đưa vào sequence diagram báo cáo. |

Luồng hiện tại:

```text
User query
-> LLMQueryAnalyzer
-> intent + rewritten_query + filters
-> Qdrant collections
-> nếu không có kết quả: Gemini fallback
```

Luồng nên có:

```text
User query
-> Router
-> route = rag | event_api | weather_api | gemini
-> handler tương ứng
-> stream response
```

## 2. Gemini Fallback

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Gemini đang được gọi khi RAG không tìm thấy kết quả, nhưng chưa được dùng để xử lý câu hỏi ngoài domain ngay từ đầu. |
| Giải pháp hiện tại | Trong pipeline, nếu `results` rỗng và có `GEMINI_API_KEY`, backend gọi Gemini fallback. Nếu Gemini fail trước khi trả token, hệ thống rơi lại local LLM; nếu fail giữa stream, emit error và dừng. |
| Giải pháp đề xuất | Thêm intent hoặc route `out_of_domain`. Ví dụ câu "Làm sao để code RAG?" nên được route thẳng sang Gemini thay vì retrieve Qdrant trước. |
| Lý do | Nếu vector search trả về kết quả nhiễu, Gemini sẽ không được gọi. Khi đó bot có thể cố trả lời dựa trên dữ liệu du lịch không liên quan. |
| Bối cảnh áp dụng | Áp dụng cho câu hỏi không thuộc domain du lịch Đà Nẵng, câu hỏi lập trình, kiến thức chung hoặc câu hỏi mà dữ liệu nội bộ không nên trả lời. |

## 3. API sự kiện / dữ liệu realtime

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Những câu hỏi như "Tối nay ở Hải Châu có lễ hội gì không?" cần dữ liệu theo thời gian thực hoặc bán realtime. RAG với dữ liệu tĩnh không phù hợp. |
| Giải pháp hiện tại | Chưa thấy chat pipeline route sang API sự kiện/thời tiết. Repo có API `recommend` và `profile`, nhưng không có event/weather handler trong luồng chat. |
| Giải pháp đề xuất | Thêm route `event_search` hoặc `realtime_event_search`. Router nhận diện thời gian + địa điểm + từ khóa sự kiện, sau đó gọi API sự kiện. |
| Lý do | Dữ liệu sự kiện thay đổi theo ngày/giờ. Nếu nhét vào vector DB tĩnh, câu trả lời dễ lỗi thời. |
| Bối cảnh áp dụng | Áp dụng cho câu hỏi có yếu tố thời gian: "hôm nay", "tối nay", "cuối tuần này", "tháng này", "lễ hội", "concert", "sự kiện". |

Ví dụ:

```text
"Tối nay ở Hải Châu có lễ hội gì không?"
-> route = event_api
-> extract district = hai chau, date = today evening
-> call Event API
-> format answer
```

## 4. Hybrid Search / BM25

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Vector search mạnh về ngữ nghĩa, nhưng có thể bỏ sót khi người dùng gõ chính xác tên quán hoặc địa danh. Ví dụ "Sala Danang Beach Hotel" hoặc một tên nhà hàng cụ thể. |
| Giải pháp hiện tại | Backend đang dùng vector search Qdrant, sau đó rerank bằng collection weight, district boost, rating boost và keyword penalty. Đây là "vector search + rerank", chưa phải hybrid search. |
| Giải pháp đề xuất | Thêm keyword/exact-name retrieval trước hoặc song song với vector retrieval. Sau đó fusion điểm: `final_score = vector_score * alpha + keyword_score * beta + rerank_boost`. |
| Lý do | Rerank chỉ xử lý các item đã được vector search trả về. Nếu exact match không nằm trong candidate set, rerank không thể cứu. |
| Bối cảnh áp dụng | Áp dụng mạnh cho `specific_search`, câu hỏi có tên riêng, tên khách sạn, nhà hàng, địa điểm hoặc query ngắn nhưng chính xác. |

Luồng đề xuất:

```text
query
-> vector search candidates
-> keyword/exact-name candidates
-> merge + dedupe
-> rerank
-> answer
```

## 5. Reranking chống nhiễu

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Vector search có thể trả kết quả lệch ngành: hỏi "mì Quảng" nhưng ra pizza/cafe, hỏi "hải sản" nhưng ra fast food. |
| Giải pháp hiện tại | Đã có rerank penalty trong `rerank.py`: nếu query chứa từ khóa như "hải sản", "mì quảng", "đồ nướng", hệ thống trừ điểm các entity có từ lệch như pizza, burger, cafe. |
| Giải pháp đề xuất | Giữ logic này, nhưng tách thành cấu hình hoặc rule table rõ ràng hơn. Có thể bổ sung positive keyword boost, ví dụ query "mì quảng" thì boost entity/cuisine/tags chứa "mì quảng". |
| Lý do | Hiện có penalty âm, nhưng chưa có keyword boost dương đủ rõ. Nếu thêm boost, hệ thống vừa đẩy nhiễu xuống vừa kéo đúng intent lên. |
| Bối cảnh áp dụng | Áp dụng cho domain nhà hàng/ẩm thực, nơi từ khóa cụ thể rất quan trọng. |

## 6. Conversational Memory

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Người dùng thường hỏi nối tiếp: "Khách sạn nào tốt ở Sơn Trà?" rồi "Cái nào có hồ bơi?". Nếu không nhớ ngữ cảnh, bot không biết "cái nào" là danh sách khách sạn trước đó. |
| Giải pháp hiện tại | Đã có memory cơ bản. Backend load lịch sử session, truyền vào pipeline. Nếu câu mới ngắn hoặc có từ chỉ định như "đó", "này", "chỗ", hệ thống thêm tên các source gần nhất vào query search. Đồng thời đưa vài cặp user/assistant gần nhất vào prompt sinh câu trả lời. |
| Giải pháp đề xuất | Nâng cấp thành structured memory/contextual compression: lưu state ngắn gọn như `last_entities`, `last_intent`, `last_filters`, `user_constraints`, `weather_context`. |
| Lý do | Memory hiện tại chủ yếu dựa vào entity names từ source cards. Nó chưa hiểu sâu các điều kiện trừu tượng như "dựa trên thời tiết vừa nói", "ngân sách như trên", "đi cùng gia đình". |
| Bối cảnh áp dụng | Áp dụng cho multi-turn planning, itinerary, câu hỏi nối tiếp hoặc khi người dùng liên tục tinh chỉnh yêu cầu. |

Ví dụ memory nâng cấp:

```json
{
  "last_intent": "hotel_search",
  "last_filters": {"district": "son tra", "min_rating": 8},
  "last_entities": ["Sala Danang Beach Hotel", "Minh Toan SAFI Ocean"],
  "user_constraints": ["có hồ bơi", "gần biển"]
}
```

## 7. Contextual Compression

| Mục | Nội dung |
| --- | --- |
| Vấn đề | Nhét toàn bộ lịch sử vào prompt gây dài, nhiễu và vẫn không đảm bảo lấy đúng thông tin quan trọng. |
| Giải pháp hiện tại | Code lấy vài cặp user/assistant gần nhất, bỏ sources khỏi assistant message. Đây là history window đơn giản. |
| Giải pháp đề xuất | Sau mỗi lượt, tóm tắt state hội thoại thành memory ngắn. Khi query mới đến, dùng state đó để rewrite query và filter. |
| Lý do | Giảm token, giảm nhiễu, giúp bot hiểu ý định nối tiếp ổn định hơn. |
| Bối cảnh áp dụng | Hữu ích khi demo hội thoại dài, lập kế hoạch du lịch nhiều bước hoặc yêu cầu "dựa trên các lựa chọn ở trên". |

## Tổng quan trạng thái

| Hạng mục | Trạng thái hiện tại |
| --- | --- |
| Intent classification | Đã có |
| Route theo collection RAG | Đã có |
| Route sang Gemini khi no-result | Đã có |
| Route Gemini cho out-of-domain | Chưa có |
| Route API sự kiện/thời tiết | Chưa có |
| Vector search | Đã có |
| Rerank chống nhiễu | Đã có |
| Hybrid search/BM25 | Chưa có |
| Conversational memory cơ bản | Đã có |
| Contextual compression nâng cao | Chưa có |

## Ưu tiên cải tiến

1. Thêm router cấp nguồn: `rag | event_api | gemini`.
2. Thêm `out_of_domain` để Gemini xử lý câu ngoài phạm vi.
3. Thêm `event_search` cho câu hỏi sự kiện/thời gian thực.
4. Thêm keyword/exact-name retrieval cho `specific_search`.
5. Nâng memory từ history window lên structured session state.

