!pip install --upgrade transformers

# ============================================================
# Cell 1 – Cài đặt dependencies
# ============================================================
import sys, subprocess, importlib

REQUIRED = [
    "qdrant-client>=1.9.0",
    "sentence-transformers>=2.6.0",
    "transformers>=5.9.0",   # Qwen3.5 yêu cầu transformers >= 5.9.0
    "bitsandbytes>=0.43.0",
    "accelerate>=0.27.0",
    "python-dotenv>=1.0.0",
    "tqdm>=4.66.0",
    "pillow>=10.0.0",         # Qwen3.5 là vision model, cần Pillow
]

def ensure_packages(packages):
    for pkg in packages:
        module_name = pkg.split(">=")[0].split("==")[0].replace("-", "_")
        try:
            importlib.import_module(module_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])

ensure_packages(REQUIRED)
print("✅ Packages sẵn sàng.")

# ============================================================
# Cell 2 – Imports & Cấu hình
# ============================================================
import os, re, json, gc, importlib, warnings
from typing import Optional, List, Dict, Any, Tuple

import torch
from tqdm.auto import tqdm

# Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, Range

# Sentence Transformers
from sentence_transformers import SentenceTransformer, CrossEncoder

# HuggingFace – Qwen3.5 là vision model, dùng AutoProcessor
from transformers import (
    AutoProcessor,
    AutoModelForImageTextToText,
    BitsAndBytesConfig,
 )

warnings.filterwarnings("ignore")

# ─── Đọc Qdrant Credentials ───────────────────────────────
def _read_kaggle_secret(key_name: str) -> Optional[str]:
    try:
        ks = importlib.import_module("kaggle_secrets")
        return ks.UserSecretsClient().get_secret(key_name)
    except Exception:
        return None

QDRANT_API_KEY = (
    _read_kaggle_secret("QDRAN_API_KEY")
    or _read_kaggle_secret("QDRANT_API_KEY")
)
QDRANT_URL = (
    _read_kaggle_secret("QDRAN_API_URL")
    or _read_kaggle_secret("QDRANT_API_URL")
)

if not QDRANT_API_KEY or not QDRANT_URL:
    try:
        import dotenv; dotenv.load_dotenv()
    except Exception:
        pass
    QDRANT_API_KEY = QDRANT_API_KEY or os.getenv("QDRAN_API_KEY") or os.getenv("QDRANT_API_KEY")
    QDRANT_URL     = QDRANT_URL     or os.getenv("QDRAN_API_URL") or os.getenv("QDRANT_API_URL")

if not QDRANT_API_KEY or not QDRANT_URL:
    raise ValueError(
        "Thiếu Qdrant credentials. "
        "Vui lòng thiết lập QDRAN_API_KEY và QDRAN_API_URL trong Kaggle Secrets."
    )

# ─── Collection Names ─────────────────────────────────────
COL_PLACES              = "places_danang"
COL_PLACE_REVIEWS       = "place_reviews_danang"
COL_RESTAURANTS         = "restaurants_danang"
COL_RESTAURANT_REVIEWS  = "restaurant_reviews_danang"
COL_HOTELS              = "accommodation_hotels_danang"
COL_ROOMS               = "accommodation_rooms_danang"
COL_HOTEL_REVIEWS       = "accommodation_reviews_danang"

# ─── Model Names ──────────────────────────────────────────
EMBED_MODEL_NAME    = "BAAI/bge-m3"
RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
LLM_MODEL_NAME      = "Qwen/Qwen3.5-4B"   # Vision-Language Model

# ─── RAG Params ───────────────────────────────────────────
TOP_K_RETRIEVE         = 15    # số docs retrieve mỗi collection
TOP_K_RERANK           = 5     # số docs sau rerank
MAX_CONTEXT_CHARS      = 4000  # tổng ký tự context tối đa
RERANK_SCORE_THRESHOLD = 0.3
MAX_NEW_TOKENS         = 2048
MAX_ALTERNATIVES       = 3

# ─── GPU Device Placement cho 2xT4 trên Kaggle ─────────────
if torch.cuda.is_available() and torch.cuda.device_count() >= 2:
    DEVICE_LLM = "cuda:0"
    DEVICE_EMBED = "cuda:1"
    DEVICE_RERANK = "cuda:1"
    print("Detected 2 GPUs. LLM -> cuda:0, Embedder/Reranker -> cuda:1")
else:
    _dev = "cuda" if torch.cuda.is_available() else "cpu"
    DEVICE_LLM = _dev
    DEVICE_EMBED = _dev
    DEVICE_RERANK = _dev
    print(f"Device: {_dev}")

print(f"QDRANT_URL: {QDRANT_URL}")
print(f"LLM: {LLM_MODEL_NAME}")

# ============================================================
# Cell 3 – Kết nối Qdrant
# ============================================================
qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)

collections = qdrant.get_collections().collections
print(f"✅ Đã kết nối Qdrant. Số collections: {len(collections)}")
for c in collections:
    cnt = qdrant.count(collection_name=c.name, exact=False).count
    print(f"   - {c.name}: ~{cnt:,} points")

# ============================================================
# Cell 4 – Embedding Model (BAAI/bge-m3)
# ============================================================
print(f"⏳ Đang tải Embedding model: {EMBED_MODEL_NAME} ...")
embedder = SentenceTransformer(EMBED_MODEL_NAME, device=DEVICE_EMBED)

_probe = embedder.encode(["du lịch Đà Nẵng"], normalize_embeddings=True)
VECTOR_DIM = _probe.shape[1]
print(f"✅ Embedding model sẵn sàng. Vector dim: {VECTOR_DIM}")

# ============================================================
# Cell 5 – Reranker (BAAI/bge-reranker-v2-m3)
# ============================================================
print(f"⏳ Đang tải Reranker: {RERANKER_MODEL_NAME} ...")
reranker = CrossEncoder(
    RERANKER_MODEL_NAME,
    max_length=512,
    device=DEVICE_RERANK,
)
print(f"✅ Reranker sẵn sàng.")

# ============================================================
# Cell 6 – LLM: Qwen/Qwen3.5-4B (fp16 quantization)
#
# Qwen3.5-4B là vision-language model với 2 chế độ:
#   - Thinking mode ON  (enable_thinking=True)  : model suy luận trước khi trả lời
#   - Thinking mode OFF (enable_thinking=False) : trả lời nhanh, phù hợp cho JSON output
#
# Dùng AutoProcessor thay vì AutoTokenizer để xử lý đúng chat template.
# Note: Sử dụng fp16 thay vì 4-bit vì bitsandbytes không có GPU support trên Kaggle.
# ============================================================
print(f"⏳ Đang tải LLM: {LLM_MODEL_NAME} (fp16) ...")

_processor = AutoProcessor.from_pretrained(
    LLM_MODEL_NAME,
    trust_remote_code=True,
)

# Để tối ưu hóa tốc độ trên 2 GPU:
# Load toàn bộ mô hình LLM nhỏ (4B) lên GPU 0, tránh sharding layer gây giao tiếp chậm
if torch.cuda.is_available() and torch.cuda.device_count() >= 2:
    _llm_device_map = {"": "cuda:0"}
else:
    _llm_device_map = "auto"

_llm_model = AutoModelForImageTextToText.from_pretrained(
    LLM_MODEL_NAME,
    dtype=torch.float16,
    device_map=_llm_device_map,
    trust_remote_code=True,
)
_llm_model.eval()

print(f"✅ LLM sẵn sàng.")
if torch.cuda.is_available():
    print(f"   GPU memory allocated: {torch.cuda.memory_allocated() / 1e9:.1f} GB")


def llm_chat(
    messages: List[Dict[str, str]],
    max_new_tokens: int = 150,
    temperature: float = 0.1,
    do_sample: bool = False,
    enable_thinking: bool = False,
 ) -> str:
    """
    Gọi Qwen3.5-4B với danh sách messages (OpenAI-style chat format).
    """
    text = _processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    inputs = _processor(
        text=[text],
        return_tensors="pt",
    ).to(_llm_model.device)

    gen_kwargs = dict(
        max_new_tokens=max_new_tokens,
        do_sample=do_sample,
        pad_token_id=_processor.tokenizer.eos_token_id,
    )
    if do_sample:
        gen_kwargs["temperature"] = temperature

    with torch.no_grad():
        output_ids = _llm_model.generate(**inputs, **gen_kwargs)

    generated = output_ids[0][inputs["input_ids"].shape[-1]:]
    full_text  = _processor.decode(generated, skip_special_tokens=True).strip()

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", full_text).strip()
    cleaned = re.sub(r"^</think>\s*", "", cleaned).strip()
    return cleaned if cleaned else full_text


def _parse_json_from_llm(text: str) -> Optional[Dict]:
    """Trích xuất JSON từ output của LLM, xử lý code block nếu có."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# Smoke test
_test_resp = llm_chat(
    [{"role": "user", "content": "Xin chào! Bạn là trợ lý gì?"}],
    max_new_tokens=80,
    enable_thinking=False,
)
print(f"   Smoke test: {_test_resp[:150]}")

# ============================================================
# Cell 7 – Router
# Nhiệm vụ: Phân loại câu hỏi và quyết định hướng xử lý
# Dùng enable_thinking=False → output JSON nhanh và chính xác
# ============================================================

ROUTER_SYSTEM_PROMPT = """\
Bạn là bộ phận phân loại câu hỏi cho chatbot tư vấn du lịch Đà Nẵng.

Nhiệm vụ: Phân tích câu hỏi của người dùng và trả về JSON với các trường sau:
- "needs_rag": true/false – câu hỏi có cần tra cứu dữ liệu du lịch không?
- "intent": loại câu hỏi, một trong các giá trị:
    * "place_search"       – tìm kiếm chung địa điểm du lịch, tham quan, vui chơi (không nêu tên cụ thể)
    * "restaurant_search"  – tìm kiếm chung nhà hàng, quán ăn, cà phê (không nêu tên cụ thể)
    * "hotel_search"       – tìm kiếm chung khách sạn, resort, homestay (không nêu tên cụ thể)
    * "room_search"        – hỏi chung về loại phòng, tiện ích phòng (không chỉ rõ khách sạn cụ thể)
    * "review_search"      – hỏi chung về đánh giá, nhận xét
    * "itinerary_search"   – lập lịch trình, gợi ý tổng hợp nhiều loại
    * "specific_search"    – hỏi hoặc so sánh về một hoặc nhiều thực thể cụ thể (địa điểm, quán ăn, khách sạn, resort) THEO TÊN RIÊNG được nhắc đến
    * "chitchat"           – trò chuyện thông thường, không liên quan du lịch
- "reason": lý do ngắn gọn (1 câu)

QUY TẮC PHÂN LOẠI ƯU TIÊN BẮT BUỘC:
1. BẤT KỲ câu hỏi nào đề cập đến tên riêng hoặc tên cụ thể của một hoặc nhiều thực thể (ví dụ: 'Chợ Cồn', 'Khách sạn Novotel', 'Novotel Đà Nẵng', 'Hải sản Năm Đảnh', 'Bà Nà Hills', 'A La Carte') đều BẮT BUỘC phải phân loại là "specific_search".
2. Quy tắc 1 áp dụng ngay cả khi so sánh các thực thể cụ thể với nhau hoặc hỏi nhiều thực thể cùng lúc (ví dụ: "So sánh khách sạn Novotel và A La Carte", "Novotel với A La Carte cái nào tốt hơn?").
3. Quy tắc 1 áp dụng ngay cả khi câu hỏi có chứa các từ khóa về địa chỉ, giờ mở cửa (dễ nhầm với place_search), thông tin phòng (dễ nhầm với room_search/hotel_search), review (dễ nhầm với review_search).
   - Ví dụ: "Chợ Cồn mở cửa mấy giờ?" -> "specific_search" (vì hỏi đích danh Chợ Cồn).
   - Ví dụ: "Novotel Đà Nẵng có phòng suite cho 2 người không?" -> "specific_search" (vì hỏi đích danh Novotel Đà Nẵng).
   - Ví dụ: "Review hải sản Năm Đảnh" -> "specific_search" (vì hỏi đích danh hải sản Năm Đảnh).
4. Chỉ dùng "place_search", "restaurant_search", "hotel_search", "room_search" khi câu hỏi mang tính tìm kiếm chung chung, gợi ý danh sách (ví dụ: 'tìm khách sạn gần biển', 'phòng suite 2 người giá bao nhiêu').

Chỉ trả về JSON thuần túy, không giải thích thêm, không markdown.

Ví dụ:
Input: "Bà Nà Hills có gì vui?"
Output: {"needs_rag": true, "intent": "specific_search", "reason": "Hỏi về địa điểm cụ thể Bà Nà Hills"}

Input: "Cho mình hỏi thời tiết Đà Nẵng tháng 7 thế nào?"
Output: {"needs_rag": false, "intent": "chitchat", "reason": "Câu hỏi về thời tiết không cần tra cứu database"}
"""


def router(query: str) -> Dict[str, Any]:
    """
    Phân loại câu hỏi người dùng.
    Trả về dict với keys: needs_rag, intent, reason
    """
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user",   "content": query},
    ]
    # thinking=False → output JSON nhanh, không cần suy luận dài
    raw = llm_chat(messages, max_new_tokens=150, do_sample=False, enable_thinking=False)
    result = _parse_json_from_llm(raw)

    if result is None:
        print(f"  [Router Warning] Không parse được JSON: {raw!r}")
        result = {"needs_rag": True, "intent": "place_search", "reason": "Fallback"}

    result.setdefault("needs_rag", True)
    result.setdefault("intent", "place_search")
    result.setdefault("reason", "")
    return result


# Test
print("Test Router:")
_tests = [
    "Có quán hải sản nào ở Sơn Trà ngon không?",
    "Khách sạn Novotel Đà Nẵng có tốt không?",
    "Bạn tên gì?",
]
for t in _tests:
    r = router(t)
    print(f"  Q: {t!r}")
    print(f"  → needs_rag={r['needs_rag']}, intent={r['intent']!r}, reason={r['reason']!r}\n")


# ============================================================
# Cell 8 – Extractor
# Nhiệm vụ: Trích xuất entities, filters, semantic_query từ câu hỏi
# Loại bỏ hoàn toàn trường keywords để tối giản hóa.
# ============================================================

import re

EXTRACTOR_SYSTEM_PROMPT = """\
Bạn là trợ lý trích xuất thông tin có cấu trúc cho chatbot du lịch Đà Nẵng.

Nhiệm vụ: Phân tích câu hỏi người dùng và trả về một đối tượng JSON có cấu trúc chính xác như sau:
{
  "entity": ["tên địa điểm/quán ăn/khách sạn cụ thể được nhắc đến"],
  "intent": "intent_phù_hợp",
  "core_query": "từ khóa thực thể hoặc chủ đề cốt lõi, ví dụ: 'chợ cồn', 'khách sạn', 'quán hải sản'",
  "filters": {
    "district": "quận/huyện chuẩn hóa (chỉ lấy 1 trong: 'hai chau','son tra','thanh khe','ngu hanh son','cam le','hoa vang','lien chieu', null nếu không đề cập)",
    "min_rating": "float 1-10 hoặc null. Lưu ý: Thang điểm đánh giá là 1-10. Nếu khách hỏi 'trên 8 điểm' -> 8.0. Nếu khách hỏi theo sao như '4.5 sao' -> quy đổi sang thang điểm 10 là 9.0 (số sao * 2.0)",
    "max_price": "integer VND hoặc null. Quy đổi: '1 triệu'→1000000, '500k'→500000, '2tr5'→2500000. Lọc theo giá phòng khách sạn, giá món ăn hoặc vé tham quan",
    "min_price": "integer VND hoặc null",
    "star_rating": "số sao của khách sạn integer 1-5 hoặc null",
    "price_level": "'low'|'mid'|'high'|null. Quy đổi: rẻ/binh dan/sinh vien -> 'low', trung bình/vừa tầm -> 'mid', cao cấp/sang trọng/đắt -> 'high'",
    "cuisine": ["danh sách món ăn hoặc ẩm thực, ví dụ: 'hải sản','mì quảng','bánh xèo','món nhật','món hàn','món việt','món thái','món trung hoa','món âu','pizza','gà rán','lẩu','nướng','cà phê','chè'"],
    "restaurant_type": ["danh sách loại hình quán ăn, ví dụ: 'buffet','quán ăn','nhà hàng','tiệm bánh','shop online','ăn vặt','vỉa hè','giao cơm văn phòng','khu ẩm thực','bar','pub','café','chợ'"],
    "restaurant_category": ["danh mục nhà hàng, ví dụ: 'Khu Ẩm Thực','Nhà Hàng','Quán Ăn'"],
    "price_avg_vnd": "integer trung bình giá hoặc null",
    "price_score": "float 1-10 điểm giá cả hoặc null",
    "quality_score": "float 1-10 điểm chất lượng hoặc null",
    "service_score": "float 1-10 điểm phục vụ hoặc null. Điền khi khách muốn phục vụ tốt, nhiệt tình",
    "space_score": "float 1-10 điểm không gian hoặc null. Điền khi khách thích view đẹp, không gian rộng/yên tĩnh",
    "location_score": "float 1-10 điểm vị trí hoặc null. Điền khi khách thích vị trí đắc địa, dễ tìm",
    "suitable_for": ["đối tượng phù hợp, ví dụ: 'gia đình','cặp đôi','nhóm bạn','solo','có trẻ em','sinh viên','giới văn phòng','khách du lịch'"],
    "best_time_to_visit": ["thời điểm đẹp nhất, ví dụ: 'sáng','trưa','chiều','tối','sáng sớm','mùa khô','mùa hè','cuối tuần','mùa xuân','mùa thu'"],
    "visit_duration": ["thời gian tham quan dự kiến, ví dụ: '30-60 phút','1-2 giờ','2-3 giờ','nửa ngày','cả ngày','qua đêm'"],
    "tags": ["danh sách nhãn đặc điểm nổi bật, ví dụ: 'sống ảo','check-in','cáp treo','núi cao','kiến trúc','tâm linh','hang động','leo núi','lịch sử','văn hoá','view biển','phiêu lưu','thiên nhiên','biểu tượng','phun lửa','view sông','về đêm','lãng mạn','làng nghề','mua sắm','vui chơi','ăn vặt','chợ đêm','đặc sản','cắm trại','lặn san hô','hoang sơ','bình minh','hoàng hôn','trekking','farmstay','healing','onsen','khoáng nóng','tắm bùn','thư giãn','picnic','yên tĩnh','thiền','vintage','bảo tàng'"],
    "weather_dependent": "'có'|'không'|null. 'có' cho địa điểm ngoài trời dễ bị ảnh hưởng bởi thời tiết như bãi biển, núi, suối, cắm trại. 'không' cho địa điểm trong nhà như bảo tàng, trung tâm thương mại",
    "check_in_time": "string format 'HH:MM' hoặc null. Giờ nhận phòng khách sạn",
    "check_out_time": "string format 'HH:MM' hoặc null. Giờ trả phòng khách sạn",
    "cancellation_policy": ["chính sách hủy phòng khách sạn, ví dụ: 'free cancellation','non-refundable','cancellation policy applies'"],
    "children_policy": ["chính sách trẻ em của khách sạn"],
    "has_discount": "true|false|null. Có khuyến mãi/giảm giá hay không",
    "room_count": "integer hoặc null. Số lượng phòng khách sạn. LƯU Ý: Chỉ điền khi người dùng chỉ rõ số lượng phòng muốn đặt (ví dụ: 'tìm 2 phòng', 'đặt 3 phòng'). TUYỆT ĐỐI KHÔNG tự ý quy đổi số lượng khách thành số lượng phòng (ví dụ: '4 người' -> room_count = 2 là SAI, room_count phải là null).",
    "max_capacity": "integer hoặc null. Sức chứa tối đa của khách sạn (ví dụ: 'cho 4 người', 'gia đình 4 người' -> max_capacity là 4, không được điền vào room_count)",
    "image_count": "integer hoặc null. Số lượng hình ảnh minh họa",
    "room_capacity": "integer hoặc null. Sức chứa của phòng cụ thể (ví dụ: 'phòng cho 4 người' -> room_capacity là 4, không được điền vào room_count)",
    "bed_type": ["loại giường trong phòng, ví dụ: 'single bed','double bed','queen bed','king bed'"],
    "area_m2": "float hoặc null. Diện tích phòng tính bằng mét vuông",
    "room_view": ["hướng phòng/view phòng, ví dụ: 'city view','sea view','river view','garden view','mountain view'"],
    "amenities_room": ["tiện ích trong phòng, ví dụ: 'shower','refrigerator','hot water','air conditioning','tv','wifi','desk','mini bar','bathtub','balcony'"],
    "sentiment_preference": "'positive'|'neutral'|'negative'|null. Đánh giá tích cực/trung lập/tiêu cực khi tìm kiếm review",
    "recency_min": "float 0-1 hoặc null. Mức độ mới của review"
  },
  "semantic_query": "truy vấn ngữ nghĩa viết bằng tiếng Việt tự nghĩa dùng để tìm kiếm vector. LƯU Ý BẮT BUỘC: 1. TUYỆT ĐỐI KHÔNG chứa các thông tin đã trích xuất được vào bộ lọc 'filters' (như tên quận/huyện, mức giá số/chữ, đánh giá/số sao). 2. TUYỆT ĐỐI KHÔNG chứa các từ chỉ địa danh chung như 'Đà Nẵng', 'đà nẵng'. 3. TUYỆT ĐỐI KHÔNG chứa các từ khóa hành động/hỏi đáp như 'ở đâu', 'mấy giờ', 'mở cửa', 'địa chỉ', 'review'. 4. Chỉ giữ lại thể loại địa điểm cốt lõi + đặc điểm không gian/trải nghiệm/phong cách thực tế."
}

Ví dụ trích xuất:
- Hỏi: 'Tìm homestay giá sinh viên ở Đà Nẵng tầm 500k' ->
{
  "entity": [],
  "intent": "hotel_search",
  "core_query": "homestay",
  "filters": {
    "price_level": "low",
    "max_price": 500000
  },
  "semantic_query": "homestay" (không được dùng homestay rẻ do có giá rồi)
}
- Hỏi: 'Quán hải sản ngon view đẹp ở Sơn Trà tối nay' ->
{
  "entity": [],
  "intent": "restaurant_search",
  "core_query": "quán hải sản",
  "filters": {
    "district": "son tra",
    "cuisine": ["hải sản"],
    "space_score": 8.0,
    "best_time_to_visit": ["tối"]
  },
  "semantic_query": "quán hải sản ngon view đẹp"
}
- Hỏi: 'Tìm phòng khách sạn 4 sao view biển, có giường đôi' ->
{
  "entity": [],
  "intent": "hotel_search",
  "core_query": "khách sạn",
  "filters": {
    "star_rating": 4,
    "room_view": "sea view",
    "bed_type": "double bed"
  },
  "semantic_query": "Khách sạn" (không đề cập 4 sao, view biển, giường đôi do có trong filter rồi)
}

Chỉ trả về JSON thuần túy, không giải thích thêm, không markdown.
"""


def _split_tokens(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[\/;,|]|\s-\s", str(value))
    tokens = []
    for part in parts:
        if part is None:
            continue
        for sub in str(part).split(","):
            item = re.sub(r"\s+", " ", sub).strip().lower()
            if item:
                tokens.append(item)
    seen = set()
    unique = []
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


def extractor(query: str, intent: str) -> Dict[str, Any]:
    """
    Trích xuất entities, filters, semantic_query từ query.
    """
    messages = [
        {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user",   "content": f"Intent đã xác định: {intent}\nCâu hỏi: {query}"},
    ]
    raw = llm_chat(messages, max_new_tokens=450, do_sample=False, enable_thinking=False)
    result = _parse_json_from_llm(raw)

    if result is None:
        print(f"  [Extractor Warning] Không parse được JSON: {raw!r}")
        result = {}

    # ── Top-level defaults ──
    result.setdefault("entity", [])
    result.setdefault("intent", intent)
    result.setdefault("core_query", "")
    result.setdefault("semantic_query", "")

    # ── Nested filters defaults ──
    if "filters" not in result or not isinstance(result["filters"], dict):
        result["filters"] = {}

    f = result["filters"]
    f.setdefault("district", None)
    f.setdefault("min_rating", None)
    f.setdefault("max_price", None)
    f.setdefault("min_price", None)
    f.setdefault("star_rating", None)
    f.setdefault("price_level", None)

    f.setdefault("cuisine", [])
    f.setdefault("restaurant_type", [])
    f.setdefault("restaurant_category", [])
    f.setdefault("price_avg_vnd", None)
    f.setdefault("price_score", None)
    f.setdefault("quality_score", None)
    f.setdefault("service_score", None)
    f.setdefault("space_score", None)
    f.setdefault("location_score", None)

    f.setdefault("suitable_for", [])
    f.setdefault("best_time_to_visit", [])
    f.setdefault("visit_duration", [])
    f.setdefault("tags", [])
    f.setdefault("weather_dependent", None)

    f.setdefault("check_in_time", None)
    f.setdefault("check_out_time", None)
    f.setdefault("cancellation_policy", [])
    f.setdefault("children_policy", [])
    f.setdefault("has_discount", None)
    f.setdefault("room_count", None)
    f.setdefault("max_capacity", None)
    f.setdefault("image_count", None)

    f.setdefault("room_capacity", None)
    f.setdefault("bed_type", [])
    f.setdefault("area_m2", None)
    f.setdefault("room_view", [])
    f.setdefault("amenities_room", [])

    f.setdefault("sentiment_preference", None)
    f.setdefault("recency_min", None)

    # ── Chuẩn hóa kiểu dữ liệu ──
    def _to_float(v):
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    def _to_int(v):
        try:
            return int(float(v)) if v is not None else None
        except Exception:
            return None

    f["min_rating"]    = _to_float(f["min_rating"])
    f["max_price"]     = _to_int(f["max_price"])
    f["min_price"]     = _to_int(f["min_price"])
    f["star_rating"]   = _to_int(f["star_rating"])
    f["price_avg_vnd"] = _to_int(f["price_avg_vnd"])
    f["price_score"]   = _to_float(f["price_score"])
    f["quality_score"] = _to_float(f["quality_score"])
    f["service_score"] = _to_float(f["service_score"])
    f["space_score"]   = _to_float(f["space_score"])
    f["location_score"]= _to_float(f["location_score"])

    f["room_count"]    = _to_int(f["room_count"])
    f["max_capacity"]  = _to_int(f["max_capacity"])
    f["image_count"]   = _to_int(f["image_count"])
    f["room_capacity"] = _to_int(f["room_capacity"])
    f["area_m2"]       = _to_float(f["area_m2"])

    f["has_discount"]  = _normalize_bool(f["has_discount"])
    f["recency_min"]   = _to_float(f["recency_min"])

    # List-like fields
    for key in [
        "cuisine", "restaurant_type", "restaurant_category",
        "suitable_for", "best_time_to_visit", "visit_duration", "tags",
        "cancellation_policy", "children_policy",
        "bed_type", "room_view", "amenities_room",
    ]:
        f[key] = _split_tokens(f.get(key))

    # Normalize weather_dependent
    if f.get("weather_dependent") is not None:
        wd = str(f["weather_dependent"]).strip().lower()
        if wd in {"có", "co", "yes", "true", "1"}:
            f["weather_dependent"] = "có"
        elif wd in {"không", "khong", "no", "false", "0"}:
            f["weather_dependent"] = "không"
        else:
            f["weather_dependent"] = None

    # Normalize sentiment
    if f.get("sentiment_preference"):
        sp = str(f["sentiment_preference"]).strip().lower()
        if sp in {"positive", "tich cuc", "tích cực"}:
            f["sentiment_preference"] = "positive"
        elif sp in {"neutral", "trung lap", "trung lập"}:
            f["sentiment_preference"] = "neutral"
        elif sp in {"negative", "tieu cuc", "tiêu cực"}:
            f["sentiment_preference"] = "negative"
        else:
            f["sentiment_preference"] = None

    # Normalize price level
    f["price_level"] = _normalize_price_level(f.get("price_level"))

    # Normalize district
    VALID_DISTRICTS = {"hai chau", "son tra", "thanh khe", "ngu hanh son", "cam le", "hoa vang", "lien chieu"}
    if f["district"] and f["district"].lower() not in VALID_DISTRICTS:
        f["district"] = None

    return result


# ============================================================
# Cell 9 – RAG Retriever
# Nhiệm vụ: Multi-collection retrieval + metadata filtering
# Cập nhật: Truy xuất filters từ extracted["filters"]
# ============================================================

_parent_cache: Dict[str, Dict[str, Any]] = {}

# Map intent → collections ưu tiên
INTENT_TO_COLLECTIONS: Dict[str, List[str]] = {
    "place_search":      [COL_PLACES, COL_PLACE_REVIEWS],
    "restaurant_search": [COL_RESTAURANTS, COL_RESTAURANT_REVIEWS],
    "hotel_search":      [COL_HOTELS, COL_HOTEL_REVIEWS, COL_ROOMS],
    "room_search":       [COL_ROOMS, COL_HOTELS],
    "review_search":     [COL_PLACE_REVIEWS, COL_RESTAURANT_REVIEWS, COL_HOTEL_REVIEWS],
    "specific_search":   [COL_PLACES, COL_RESTAURANTS, COL_HOTELS, COL_ROOMS],
    "itinerary_search":  [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
    "chitchat":          [],
}


def _normalize_text(value: Any) -> str:
    return str(value).lower().strip() if value is not None else ""


def _match_any(payload_value: Any, wanted_tokens: List[str]) -> bool:
    if not wanted_tokens:
        return True
    if payload_value is None:
        return False
    if isinstance(payload_value, list):
        text = " ".join([_normalize_text(x) for x in payload_value])
    else:
        text = _normalize_text(payload_value)
    return any(tok in text for tok in wanted_tokens)


def _get_rating_key(collection: str) -> str:
    return "avg_rating" if collection == COL_PLACES else "rating"


def _get_price_min_key(collection: str) -> str:
    return "price_min_vnd" if collection == COL_PLACES else "min_price_vnd"


def _build_qdrant_filter(
    extracted: Dict[str, Any],
    collection: str,
) -> Optional[Filter]:
    """Xây dựng Qdrant Filter từ extracted["filters"]."""
    f = extracted.get("filters", {})
    conditions = []

    # Rating
    min_rating = f.get("min_rating")
    if min_rating is not None:
        rating_key = _get_rating_key(collection)
        conditions.append(FieldCondition(key=rating_key, range=Range(gte=float(min_rating))))

    # Price range
    max_price = f.get("max_price")
    if max_price is not None:
        price_key = _get_price_min_key(collection)
        conditions.append(FieldCondition(key=price_key, range=Range(lte=float(max_price))))

    min_price = f.get("min_price")
    if min_price is not None:
        price_key = _get_price_min_key(collection)
        conditions.append(FieldCondition(key=price_key, range=Range(gte=float(min_price))))

    # District (only entity collections)
    district = f.get("district")
    if district and collection in {COL_PLACES, COL_RESTAURANTS, COL_HOTELS}:
        conditions.append(FieldCondition(key="district", match=MatchValue(value=district.lower())))

    # Star rating (hotels only)
    star_rating = f.get("star_rating")
    if star_rating is not None and collection == COL_HOTELS:
        conditions.append(FieldCondition(key="star_rating", range=Range(gte=float(star_rating))))

    # Price level (entities)
    price_level = f.get("price_level")
    if price_level and collection in {COL_PLACES, COL_RESTAURANTS, COL_HOTELS, COL_ROOMS}:
        conditions.append(FieldCondition(key="price_level", match=MatchValue(value=price_level)))

    # Weather dependent (places)
    weather_dependent = f.get("weather_dependent")
    if weather_dependent and collection == COL_PLACES:
        conditions.append(FieldCondition(key="weather_dependent", match=MatchValue(value=weather_dependent)))

    # Review defaults
    sentiment_pref = f.get("sentiment_preference")
    if collection == COL_PLACE_REVIEWS:
        sentiment = sentiment_pref or "positive"
        conditions.append(FieldCondition(key="sentiment", match=MatchValue(value=sentiment)))

    if collection == COL_RESTAURANT_REVIEWS:
        recency_min = f.get("recency_min")
        if recency_min is None:
            recency_min = 0.6
        conditions.append(FieldCondition(key="recency_score", range=Range(gte=float(recency_min))))

    return Filter(must=conditions) if conditions else None


def _passes_price_filters(payload: Dict[str, Any], extracted: Dict[str, Any], collection: str) -> bool:
    """Áp dụng lọc giá mềm dùng extracted["filters"]."""
    f = extracted.get("filters", {})
    max_price = f.get("max_price")
    min_price = f.get("min_price")
    price_avg_target = f.get("price_avg_vnd")

    if max_price is None and min_price is None and price_avg_target is None:
        return True

    min_price_vnd = payload.get("min_price_vnd") or payload.get("price_min_vnd")
    max_price_vnd = payload.get("max_price_vnd") or payload.get("price_max_vnd")
    price_avg_vnd = payload.get("price_avg_vnd")

    if max_price is not None:
        if min_price_vnd is not None and min_price_vnd > max_price:
            return False
        if max_price_vnd is not None and max_price_vnd > (max_price * 1.5):
            return False
        if price_avg_vnd is not None and price_avg_vnd > (max_price * 1.5):
            return False

    if min_price is not None:
        if max_price_vnd is not None and max_price_vnd < min_price:
            return False
        if min_price_vnd is not None and min_price_vnd < min_price:
            return False
        if price_avg_vnd is not None and price_avg_vnd < (min_price * 0.7):
            return False

    if price_avg_target is not None and price_avg_vnd is not None:
        if price_avg_vnd > price_avg_target * 1.5:
            return False
        if price_avg_vnd < price_avg_target * 0.7:
            return False

    return True


def _passes_collection_filters(payload: Dict[str, Any], extracted: Dict[str, Any], collection: str) -> bool:
    """Lọc cứng chỉ áp dụng cho các trường số có chuẩn hóa cao (capacity, area).
    Các trường text mềm (cuisine, suitable_for, ...) được xử lý bằng Reranker."""
    f = extracted.get("filters", {})

    # Hotels (Chỉ lọc trên entity COL_HOTELS, review được xử lý riêng bằng post-filter)
    if collection == COL_HOTELS:
        if f.get("check_in_time"):
            if not _match_any(payload.get("check_in_time"), [f.get("check_in_time")]):
                return False
        if f.get("check_out_time"):
            if not _match_any(payload.get("check_out_time"), [f.get("check_out_time")]):
                return False
        if f.get("room_count") is not None:
            if (payload.get("room_count") or 0) < f.get("room_count"):
                return False
        needed_capacity = f.get("max_capacity") or f.get("room_capacity")
        if needed_capacity is not None:
            room_count = f.get("room_count") or 1
            min_required_room_cap = (needed_capacity + room_count - 1) // room_count
            if (payload.get("max_capacity") or 0) < min_required_room_cap:
                return False

    # Rooms
    if collection == COL_ROOMS:
        needed_capacity = f.get("room_capacity") or f.get("max_capacity")
        if needed_capacity is not None:
            room_count = f.get("room_count") or 1
            min_required_room_cap = (needed_capacity + room_count - 1) // room_count
            if (payload.get("capacity") or 0) < min_required_room_cap:
                return False
        if f.get("area_m2") is not None:
            if (payload.get("area_m2") or 0) < f.get("area_m2"):
                return False
                
    return True


def retrieve(
    query_vec: List[float],
    collections: List[str],
    extracted: Dict[str, Any],
    top_k: int = TOP_K_RETRIEVE,
) -> List[Dict[str, Any]]:
    """
    Tìm kiếm vector trên nhiều collections với metadata filtering.
    Trả về list dicts: {id, score, collection, payload, text}
    """
    all_hits = []
    f = extracted.get("filters", {})
    district = f.get("district")
    star_rating = f.get("star_rating")
    price_level = f.get("price_level")

    for col in collections:
        q_filter = _build_qdrant_filter(extracted, col)
        try:
            result = qdrant.query_points(
                collection_name=col,
                query=query_vec,
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
            hits = result.points if hasattr(result, "points") else result
        except Exception:
            # Fallback cho Qdrant client cũ hơn
            hits = qdrant.search(
                collection_name=col,
                query_vector=query_vec,
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )

        for h in hits:
            payload = h.payload if hasattr(h, "payload") else h.get("payload", {})
            
            # Post-filter cho các child collections (Rooms, Reviews) dựa trên parent entity
            if col in {COL_ROOMS, COL_PLACE_REVIEWS, COL_RESTAURANT_REVIEWS, COL_HOTEL_REVIEWS}:
                parent_id = payload.get("parent_entity_id")
                if parent_id:
                    parent_doc = fetch_parent_entity({"payload": payload, "collection": col})
                    if parent_doc:
                        parent_payload = parent_doc.get("payload", {})
                        
                        # 1. Check district
                        if district:
                            parent_district = parent_payload.get("district", "")
                            if _normalize_text(parent_district) != _normalize_text(district):
                                continue
                        
                        # 2. Check star_rating (cho Rooms và Hotel Reviews)
                        if col in {COL_ROOMS, COL_HOTEL_REVIEWS} and star_rating is not None:
                            parent_star = parent_payload.get("star_rating")
                            if parent_star is not None and float(parent_star) < float(star_rating):
                                continue
                                
                        # 3. Check price_level
                        if price_level:
                            parent_price_level = parent_payload.get("price_level")
                            if parent_price_level and parent_price_level != price_level:
                                continue

                        # 4. Check check-in/out policies (chỉ cho hotel reviews)
                        if col == COL_HOTEL_REVIEWS:
                            check_in = f.get("check_in_time")
                            if check_in and not _match_any(parent_payload.get("check_in_time"), [check_in]):
                                continue
                            check_out = f.get("check_out_time")
                            if check_out and not _match_any(parent_payload.get("check_out_time"), [check_out]):
                                continue
                    else:
                        continue
                else:
                    continue

            if not _passes_price_filters(payload, extracted, col):
                continue
            if not _passes_collection_filters(payload, extracted, col):
                continue
            score   = h.score   if hasattr(h, "score")   else h.get("score", 0.0)
            doc_id  = str(h.id  if hasattr(h, "id")      else h.get("id", ""))
            text    = payload.get("content", "")

            all_hits.append({
                "id":         doc_id,
                "score":      float(score),
                "collection": col,
                "payload":    payload,
                "text":       text,
            })

    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits


def fetch_parent_entity(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Với review/room doc, lấy thêm entity doc (parent) để bổ sung context.
    """
    payload    = doc.get("payload", {})
    parent_id  = payload.get("parent_entity_id")
    collection = doc.get("collection", "")

    if not parent_id:
        return None
    if parent_id in _parent_cache:
        return _parent_cache[parent_id]

    entity_col_map = {
        COL_PLACE_REVIEWS:      COL_PLACES,
        COL_RESTAURANT_REVIEWS: COL_RESTAURANTS,
        COL_HOTEL_REVIEWS:      COL_HOTELS,
        COL_ROOMS:              COL_HOTELS,
    }
    entity_col = entity_col_map.get(collection)
    if not entity_col:
        return None

    try:
        result = qdrant.retrieve(
            collection_name=entity_col,
            ids=[parent_id],
            with_payload=True,
        )
        if result:
            p       = result[0]
            payload = p.payload if hasattr(p, "payload") else p.get("payload", {})
            parent = {
                "id":         str(p.id if hasattr(p, "id") else p.get("id")),
                "collection": entity_col,
                "payload":    payload,
                "text":       payload.get("content", ""),
            }
            _parent_cache[parent_id] = parent
            return parent
    except Exception:
        pass
    return None


print("✅ Retriever sẵn sàng.")


# ============================================================
# Cell 10 – Reranker & Context Builder
# Cập nhật: Loại bỏ keywords hoàn toàn khỏi Reranker.
# ============================================================

def extract_specific_entities(query: str) -> List[str]:
    """Trích xuất danh sách tên thực thể cụ thể từ câu hỏi (chỉ dùng cho intent specific_search)."""
    messages = [
        {"role": "system", "content": """\
Bạn là trợ lý trích xuất danh sách tên các thực thể cụ thể (địa điểm du lịch, khách sạn, resort, nhà hàng, quán ăn) từ câu hỏi của khách du lịch Đà Nẵng.
Hãy trích xuất tất cả tên chính xác của các thực thể được nhắc đến trong câu hỏi và trả về dưới dạng một danh sách JSON chứa các chuỗi (JSON array of strings).

Lưu ý:
- Chỉ trả về JSON array thuần túy, không thêm bất kỳ giải thích nào khác, không dùng markdown codeblock.
- Nếu không tìm thấy tên thực thể cụ thể nào, hãy trả về danh sách rỗng [].

Ví dụ:
Input: "Khách sạn Novotel Đà Nẵng có tốt không?"
Output: ["Novotel Đà Nẵng"]

Input: "So sánh khách sạn Novotel và A La Carte Da Nang"
Output: ["Novotel", "A La Carte Da Nang"]

Input: "Địa chỉ của quán Hải sản Năm Đảnh ở đâu?"
Output: ["Hải sản Năm Đảnh"]

Input: "Thời tiết hôm nay thế nào?"
Output: []
"""},
        {"role": "user", "content": query}
    ]
    raw = llm_chat(messages, max_new_tokens=150, do_sample=False, enable_thinking=False)
    result = _parse_json_from_llm(raw)
    if isinstance(result, list):
        return [str(x).strip() for x in result if x]
    
    # Fallback nếu không parse được JSON
    cleaned = raw.strip()
    cleaned = re.sub(r'^["\'\\`\u201c\u2018]|[\u201d\u2019"\'\\`]$', '', cleaned).strip()
    return [cleaned] if cleaned else []


def _safe_lower(value: Any) -> str:
    return str(value).lower().strip() if value is not None else ""


def _get_display_name(payload: Dict[str, Any]) -> str:
    return payload.get("place_name") or payload.get("entity_name") or payload.get("room_name") or ""


def _get_rating(payload: Dict[str, Any]) -> Optional[float]:
    rating = payload.get("rating")
    if rating is None:
        rating = payload.get("avg_rating")
    return rating


def _truncate_text(value: Any, max_len: int = 200) -> str:
    text = str(value) if value is not None else ""
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def rerank(
    query: str,
    docs: List[Dict[str, Any]],
    extracted: Dict[str, Any],
    top_n: int = TOP_K_RERANK,
) -> List[Dict[str, Any]]:
    """
    Rerank docs bằng bge-reranker-v2-m3 cross-encoder + heuristic.
    """
    if not docs:
        return []

    pairs  = [(query, d["text"][:512]) for d in docs]
    scores = reranker.predict(pairs, show_progress_bar=False)

    query_lower = _safe_lower(query)
    f = extracted.get("filters", {})

    mismatch_rules = {
        "hải sản": ["gà rán", "burger", "lotteria", "jollibee", "pizza", "chè", "cafe", "coffee"],
        "mì quảng": ["pizza", "cinema", "bar", "lounge", "buffet", "chè", "cafe", "coffee"],
        "đồ nướng": ["bánh sầu riêng", "quán chay", "chè", "trà sữa", "cafe", "coffee"],
        "khách sạn": ["homestay", "hostel", "dorm"],
    }

    for doc, score in zip(docs, scores):
        doc["rerank_score"] = float(score)
        payload = doc.get("payload", {})
        col = doc.get("collection", "")
        
        # Lấy payload của parent entity nếu doc thuộc collection con (reviews, rooms)
        parent_payload = {}
        if col in {COL_ROOMS, COL_PLACE_REVIEWS, COL_RESTAURANT_REVIEWS, COL_HOTEL_REVIEWS}:
            parent_doc = fetch_parent_entity(doc)
            if parent_doc:
                parent_payload = parent_doc.get("payload", {})

        name_lower = _safe_lower(_get_display_name(payload) or _get_display_name(parent_payload))
        final_score = float(score)
        
        # Setup logging for this document
        rerank_logs = []
        rerank_logs.append(f"Điểm khởi tạo (CrossEncoder): {score:.4f}")

        is_restaurant = col in {COL_RESTAURANTS, COL_RESTAURANT_REVIEWS}
        is_place = col in {COL_PLACES, COL_PLACE_REVIEWS}
        is_hotel = col in {COL_HOTELS, COL_HOTEL_REVIEWS, COL_ROOMS}

        # ── 1. So sánh quận/huyện đã chuẩn hóa ──
        req_district = f.get("district")
        doc_district = payload.get("district") or parent_payload.get("district")
        if req_district:
            if doc_district:
                if req_district.lower() == _safe_lower(doc_district):
                    final_score += 0.3
                    rerank_logs.append(f"Cộng điểm Quận/Huyện: +0.3 ({req_district} == {doc_district})")
                else:
                    rerank_logs.append(f"Không khớp Quận/Huyện: {req_district} != {doc_district}")
            else:
                rerank_logs.append(f"Yêu cầu Quận/Huyện ({req_district}) nhưng tài liệu không có thông tin quận")

        # ── 2. Rating boost ──
        rating = _get_rating(payload) or _get_rating(parent_payload)
        review_count = (
            payload.get("review_count")
            or parent_payload.get("review_count")
            or payload.get("google_review_count")
            or parent_payload.get("google_review_count")
            or 0
        )
        if rating is not None:
            if review_count > 5:
                boost = min(0.4, float(rating) / 20)
                final_score += boost
                rerank_logs.append(f"Cộng điểm Đánh giá (Review > 5): +{boost:.4f} (Đánh giá: {rating}, Số review: {review_count})")
            else:
                boost = min(0.15, float(rating) / 40)
                final_score += boost
                rerank_logs.append(f"Cộng điểm Đánh giá (Review <= 5): +{boost:.4f} (Đánh giá: {rating}, Số review: {review_count})")
        else:
            rerank_logs.append("Không có thông tin Đánh giá (Rating): Không cộng điểm")

        # ── 3. Mismatch penalty ──
        mismatch_applied = False
        for key, bad_words in mismatch_rules.items():
            if key in query_lower and any(word in name_lower for word in bad_words):
                final_score -= 0.8
                mismatch_applied = True
                matched_bad_words = [word for word in bad_words if word in name_lower]
                rerank_logs.append(f"Trừ điểm Mismatch '{key}': -0.8 (Tên '{name_lower}' chứa từ không hợp lệ: {matched_bad_words})")
        
        if any(word in query_lower for word in ["đối tác", "tiếp khách", "sang trọng"]):
            if rating is not None and float(rating) < 7.5:
                final_score -= 0.3
                rerank_logs.append(f"Trừ điểm Tiếp khách/Sang trọng (Đánh giá < 7.5): -0.3 (Đánh giá: {rating})")
            if "buffet" in name_lower:
                final_score -= 0.15
                rerank_logs.append("Trừ điểm Tiếp khách/Sang trọng (Buffet): -0.15")

        # ── 4. Match boosts trên extracted["filters"] theo loại thực thể ──
        
        # Nhóm Nhà hàng (Restaurants)
        if is_restaurant:
            cuisine_val = payload.get("cuisine") or parent_payload.get("cuisine")
            if f.get("cuisine"):
                if _match_any(cuisine_val, f["cuisine"]):
                    final_score += 0.25
                    rerank_logs.append(f"Cộng điểm Ẩm thực: +0.25 (Khớp {f['cuisine']} trong {cuisine_val})")
                else:
                    final_score -= 0.15
                    rerank_logs.append(f"Trừ điểm Ẩm thực: -0.15 (Không khớp {f['cuisine']} trong {cuisine_val})")
            
            type_val = payload.get("restaurant_type") or parent_payload.get("restaurant_type")
            if f.get("restaurant_type"):
                if _match_any(type_val, f["restaurant_type"]):
                    final_score += 0.2
                    rerank_logs.append(f"Cộng điểm Loại hình nhà hàng: +0.2 (Khớp {f['restaurant_type']} trong {type_val})")
                else:
                    final_score -= 0.1
                    rerank_logs.append(f"Trừ điểm Loại hình nhà hàng: -0.1 (Không khớp {f['restaurant_type']} trong {type_val})")
            
            cat_val = payload.get("category") or parent_payload.get("category")
            if f.get("restaurant_category"):
                if _match_any(cat_val, f["restaurant_category"]):
                    final_score += 0.15
                    rerank_logs.append(f"Cộng điểm Danh mục nhà hàng: +0.15 (Khớp {f['restaurant_category']} trong {cat_val})")

        # Nhóm Địa điểm tham quan (Places)
        elif is_place:
            suitable_val = payload.get("suitable_for") or parent_payload.get("suitable_for")
            if f.get("suitable_for"):
                if _match_any(suitable_val, f["suitable_for"]):
                    final_score += 0.2
                    rerank_logs.append(f"Cộng điểm Phù hợp đối tượng: +0.2 (Khớp {f['suitable_for']} trong {suitable_val})")
                else:
                    final_score -= 0.1
                    rerank_logs.append(f"Trừ điểm Phù hợp đối tượng: -0.1 (Không khớp {f['suitable_for']} trong {suitable_val})")
            
            time_val = payload.get("best_time_to_visit") or parent_payload.get("best_time_to_visit")
            if f.get("best_time_to_visit"):
                if _match_any(time_val, f["best_time_to_visit"]):
                    final_score += 0.15
                    rerank_logs.append(f"Cộng điểm Thời điểm đẹp: +0.15 (Khớp {f['best_time_to_visit']} trong {time_val})")
            
            duration_val = payload.get("visit_duration") or parent_payload.get("visit_duration")
            if f.get("visit_duration"):
                if _match_any(duration_val, f["visit_duration"]):
                    final_score += 0.1
                    rerank_logs.append(f"Cộng điểm Thời lượng: +0.1 (Khớp {f['visit_duration']} trong {duration_val})")
            
            tags_val = payload.get("tags") or parent_payload.get("tags")
            if f.get("tags"):
                if _match_any(tags_val, f["tags"]):
                    final_score += 0.15
                    rerank_logs.append(f"Cộng điểm Tags đặc điểm: +0.15 (Khớp {f['tags']} trong {tags_val})")

        # Nhóm Khách sạn (Hotels/Rooms)
        elif is_hotel:
            star_rating_val = payload.get("star_rating") or parent_payload.get("star_rating")
            if f.get("star_rating") is not None:
                if star_rating_val is not None:
                    if float(star_rating_val) >= float(f["star_rating"]):
                        final_score += 0.2
                        rerank_logs.append(f"Cộng điểm Số sao: +0.2 (Số sao {star_rating_val} >= {f['star_rating']})")
                    else:
                        final_score -= 0.25
                        rerank_logs.append(f"Trừ điểm Số sao: -0.25 (Số sao {star_rating_val} < {f['star_rating']})")
                else:
                    rerank_logs.append(f"Yêu cầu Số sao ({f['star_rating']}) nhưng tài liệu không có thông tin sao")

            room_view_val = payload.get("room_view") or parent_payload.get("room_view")
            if f.get("room_view"):
                if _match_any(room_view_val, f["room_view"]):
                    final_score += 0.15
                    rerank_logs.append(f"Cộng điểm View phòng: +0.15 (Khớp {f['room_view']} trong {room_view_val})")
            
            amenities_val = payload.get("amenities_room") or parent_payload.get("amenities_room")
            if f.get("amenities_room"):
                if _match_any(amenities_val, f["amenities_room"]):
                    final_score += 0.15
                    rerank_logs.append(f"Cộng điểm Tiện ích phòng: +0.15 (Khớp {f['amenities_room']} trong {amenities_val})")
            
            bed_val = payload.get("bed_type") or parent_payload.get("bed_type")
            if f.get("bed_type"):
                if _match_any(bed_val, f["bed_type"]):
                    final_score += 0.1
                    rerank_logs.append(f"Cộng điểm Loại giường: +0.1 (Khớp {f['bed_type']} trong {bed_val})")

            cancellation_val = payload.get("cancellation_policy") or parent_payload.get("cancellation_policy")
            if f.get("cancellation_policy"):
                if _match_any(cancellation_val, f["cancellation_policy"]):
                    final_score += 0.1
                    rerank_logs.append(f"Cộng điểm Chính sách hủy: +0.1 (Khớp {f['cancellation_policy']} trong {cancellation_val})")
            
            children_val = payload.get("children_policy") or parent_payload.get("children_policy")
            if f.get("children_policy"):
                if _match_any(children_val, f["children_policy"]):
                    final_score += 0.1
                    rerank_logs.append(f"Cộng điểm Chính sách trẻ em: +0.1 (Khớp {f['children_policy']} trong {children_val})")

        # Các trường dùng chung khác
        has_discount_val = payload.get("has_discount") if payload.get("has_discount") is not None else parent_payload.get("has_discount")
        if f.get("has_discount") is not None:
            if has_discount_val is not None:
                if has_discount_val == f["has_discount"]:
                    final_score += 0.1
                    rerank_logs.append(f"Cộng điểm Khuyến mãi: +0.1 (Khớp trạng thái khuyến mãi: {has_discount_val})")
            else:
                rerank_logs.append(f"Yêu cầu Khuyến mãi ({f['has_discount']}) nhưng tài liệu không có thông tin khuyến mãi")

        doc["final_score"] = final_score
        doc["rerank_logs"] = rerank_logs

    ranked = sorted(docs, key=lambda x: x.get("final_score", x.get("rerank_score", 0.0)), reverse=True)
    
    # In chi tiết cộng trừ điểm của các tài liệu hàng đầu
    print(f"\n📊 [Reranker Detail Logs] Chi tiết cộng trừ điểm của top {min(10, len(ranked))} tài liệu:")
    for idx, doc in enumerate(ranked[:10]):
        payload = doc.get("payload", {})
        col = doc.get("collection", "")
        # Lấy parent name nếu là review/room
        parent_payload = {}
        if col in {COL_ROOMS, COL_PLACE_REVIEWS, COL_RESTAURANT_REVIEWS, COL_HOTEL_REVIEWS}:
            parent_doc = fetch_parent_entity(doc)
            if parent_doc:
                parent_payload = parent_doc.get("payload", {})
        name = _get_display_name(payload) or _get_display_name(parent_payload) or "Không rõ tên"
        print(f"   #{idx+1}. {name} | Collection: {col} | Final Score: {doc.get('final_score', 0.0):.4f}")
        for log in doc.get("rerank_logs", []):
            print(f"      * {log}")
            
    return ranked[:top_n]

def build_context(
    query: str,
    docs: List[Dict[str, Any]],
    fetch_parents: bool = True,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Xây dựng context string từ danh sách docs.
    """
    enriched: List[Dict[str, Any]] = []
    seen_ids = set()

    parent_cache: Dict[str, Dict] = {}
    if fetch_parents:
        for doc in docs:
            parent_id = doc.get("payload", {}).get("parent_entity_id")
            if parent_id and parent_id not in parent_cache:
                parent = fetch_parent_entity(doc)
                if parent:
                    parent_cache[parent_id] = parent

    for doc in docs:
        parent_id = doc.get("payload", {}).get("parent_entity_id")

        if parent_id and parent_id not in seen_ids and parent_id in parent_cache:
            enriched.append(parent_cache[parent_id])
            seen_ids.add(parent_id)

        if doc["id"] not in seen_ids:
            enriched.append(doc)
            seen_ids.add(doc["id"])

    def _add_line(lines: List[str], label: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list):
            value = ", ".join([str(v) for v in value if v])
        if value is False:
            value = "Không"
        if value is True:
            value = "Có"
        if str(value).strip() == "":
            return
        lines.append(f"{label}: {value}")

    context_parts = []
    total_chars   = 0

    for doc in enriched:
        payload = doc.get("payload", {})
        name = _get_display_name(payload)
        collection = doc.get("collection", "")
        content = doc.get("text", "") or payload.get("content", "")
        content = content[:600] + "..." if len(content) > 600 else content

        lines = ["<item>", f"Tên địa điểm: {name}", f"Phân loại: {collection}"]
        _add_line(lines, "Quận", payload.get("district"))
        _add_line(lines, "Địa chỉ", payload.get("address"))

        rating_val = _get_rating(payload)
        if rating_val is not None:
            _add_line(lines, "Đánh giá", f"{rating_val}/10")

        min_price = payload.get("min_price_vnd") or payload.get("price_min_vnd")
        max_price = payload.get("max_price_vnd") or payload.get("price_max_vnd")
        if min_price is not None:
            if max_price is not None and max_price > min_price:
                _add_line(lines, "Mức giá", f"{min_price:,} - {max_price:,} VND")
            else:
                _add_line(lines, "Mức giá", f"{min_price:,} VND")

        if payload.get("time_open") and payload.get("time_close"):
            _add_line(lines, "Giờ mở", f"{payload['time_open']} - {payload['time_close']}")
        if payload.get("opening_hours"):
            _add_line(lines, "Giờ mở", payload.get("opening_hours"))

        if collection in {COL_PLACES, COL_PLACE_REVIEWS}:
            _add_line(lines, "Danh mục", payload.get("category"))
            _add_line(lines, "Phù hợp", payload.get("suitable_for"))
            _add_line(lines, "Thời điểm đẹp", payload.get("best_time_to_visit"))
            _add_line(lines, "Thời lượng", payload.get("visit_duration"))
            _add_line(lines, "Tags", payload.get("tags"))
            _add_line(lines, "Phụ thuộc thời tiết", payload.get("weather_dependent"))
            _add_line(lines, "Mức giá", payload.get("price_level"))
            _add_line(lines, "Khoảng giá", payload.get("price_range_raw"))
            _add_line(lines, "Google review", payload.get("google_review_count"))
            _add_line(lines, "TikTok likes", payload.get("tiktok_total_likes"))
            _add_line(lines, "TikTok comments", payload.get("tiktok_comment_count"))
            _add_line(lines, "TikTok videos", payload.get("tiktok_video_count"))
            _add_line(lines, "Mentions", payload.get("total_mentions"))

        if collection in {COL_RESTAURANTS, COL_RESTAURANT_REVIEWS}:
            _add_line(lines, "Ẩm thực", payload.get("cuisine"))
            _add_line(lines, "Loại hình", payload.get("restaurant_type"))
            _add_line(lines, "Category", payload.get("category"))
            if payload.get("price_avg_vnd") is not None:
                _add_line(lines, "Giá TB", f"{payload.get('price_avg_vnd'):,} VND")
            _add_line(lines, "Mức giá", payload.get("price_level"))
            _add_line(lines, "Điểm giá", payload.get("price_score"))
            _add_line(lines, "Điểm chất lượng", payload.get("quality_score"))
            _add_line(lines, "Điểm dịch vụ", payload.get("service_score"))
            _add_line(lines, "Điểm không gian", payload.get("space_score"))
            _add_line(lines, "Điểm vị trí", payload.get("location_score"))
            _add_line(lines, "Số review", payload.get("review_count"))

        if collection in {COL_HOTELS, COL_HOTEL_REVIEWS}:
            _add_line(lines, "Sao", payload.get("star_rating"))
            _add_line(lines, "Check-in", payload.get("check_in_time"))
            _add_line(lines, "Check-out", payload.get("check_out_time"))
            if payload.get("cancellation_policy"):
                _add_line(lines, "Chính sách hủy", _truncate_text(payload.get("cancellation_policy"), 180))
            if payload.get("children_policy"):
                _add_line(lines, "Chính sách trẻ em", _truncate_text(payload.get("children_policy"), 180))
            _add_line(lines, "Khuyến mãi", payload.get("has_discount"))
            _add_line(lines, "Số phòng", payload.get("room_count"))
            _add_line(lines, "Sức chứa", payload.get("max_capacity"))
            _add_line(lines, "Số ảnh", payload.get("image_count"))

        if collection == COL_ROOMS:
            _add_line(lines, "Tên phòng", payload.get("room_name"))
            _add_line(lines, "Sức chứa", payload.get("capacity"))
            _add_line(lines, "Loại giường", payload.get("bed_type"))
            _add_line(lines, "Diện tích", payload.get("area_m2"))
            _add_line(lines, "View", payload.get("room_view"))
            if payload.get("amenities_room"):
                _add_line(lines, "Tiện nghi", _truncate_text(payload.get("amenities_room"), 200))

        if collection in {COL_PLACE_REVIEWS, COL_RESTAURANT_REVIEWS, COL_HOTEL_REVIEWS}:
            _add_line(lines, "Sentiment", payload.get("sentiment"))
            _add_line(lines, "Aspects", payload.get("aspects"))
            _add_line(lines, "Recency", payload.get("recency_score"))
            _add_line(lines, "Thời gian", payload.get("timestamp_norm"))

        if content:
            _add_line(lines, "Mô tả", content)
        lines.append("</item>")

        block = "\n".join(lines)
        if total_chars + len(block) > max_chars:
            break
        context_parts.append(block)
        total_chars += len(block)

    context = "\n\n".join(context_parts)
    return context, enriched

print("✅ Reranker & Context Builder sẵn sàng (Không dùng keywords).")


# ============================================================
# Cell 11 – Planner / Synthesizer
# Nhiệm vụ: Tổng hợp câu trả lời cuối từ context + query
# Cập nhật: Prompt tự nhiên hơn, không nhắc "context", "dữ liệu"
# ============================================================

SYNTHESIZER_SYSTEM_PROMPT = """\
Bạn là trợ lý du lịch Đà Nẵng thông minh, nhiệt tình và am hiểu địa phương.
Nhiệm vụ: Trả lời câu hỏi của khách du lịch dựa trên thông tin được cung cấp.

Nguyên tắc bắt buộc:
1. TUYỆT ĐỐI KHÔNG được sử dụng các cụm từ kỹ thuật như "dựa trên context", "trong context", "theo context cung cấp", "dữ liệu đã cho", "hệ thống", "cơ sở dữ liệu", "CONTEXT", "thông tin trong CONTEXT", v.v. Hãy nói chuyện tự nhiên như một hướng dẫn viên bản địa thực thụ đang chia sẻ từ kiến thức và trải nghiệm cá nhân.
2. Chỉ dùng các thông tin có thật về địa chỉ, giá cả, đánh giá từ mô tả địa điểm. KHÔNG bịa đặt hay suy diễn thêm.
3. Nếu không đủ thông tin để trả lời, hãy thân thiện cho khách biết và gợi ý lựa chọn thay thế.
4. Trả lời bằng tiếng Việt, tự nhiên, hào hứng, hiếu khách.
5. Định dạng rõ ràng: dùng gạch đầu dòng hoặc đánh số khi liệt kê nhiều địa điểm. Với mỗi gợi ý: tên, địa chỉ (nếu có), giá tham khảo (nếu có), điểm nổi bật.
6. Với câu hỏi lịch trình (itinerary), chia theo ngày rõ ràng.
7. KHÔNG đề xuất địa điểm ngoài Đà Nẵng trừ khi được yêu cầu.
"""

CHITCHAT_SYSTEM_PROMPT = """\
Bạn là trợ lý du lịch Đà Nẵng thân thiện.
Hãy trả lời câu hỏi của người dùng một cách ngắn gọn, thân thiện bằng tiếng Việt.
Nếu câu hỏi liên quan đến du lịch hoặc Đà Nẵng, hãy khuyến khích họ hỏi thêm về địa điểm, ăn uống, khách sạn.
"""


def synthesizer(
    query: str,
    context: str,
    intent: str,
    extracted: Dict[str, Any],
) -> str:
    """
    Tổng hợp câu trả lời từ context.
    Dùng enable_thinking=True để Qwen3.5 suy luận → câu trả lời chất lượng hơn.
    Trả về string.
    """
    if intent == "chitchat" or not context.strip():
        messages = [
            {"role": "system", "content": CHITCHAT_SYSTEM_PROMPT},
            {"role": "user",   "content": query},
        ]
        return llm_chat(
            messages,
            max_new_tokens=300,
            do_sample=True,
            temperature=0.7,
            enable_thinking=False,  # Chitchat không cần thinking
        )

    # Hướng dẫn bổ sung theo intent
    intent_hints = {
        "itinerary_search": "Hãy lập lịch trình rõ ràng theo ngày. Kết hợp địa điểm, ăn uống và lưu trú phù hợp.",
        "review_search":    "Tổng hợp nhận xét, phân biệt điểm tốt và chưa tốt nếu có.",
        "specific_search":  "Nếu không tìm thấy đúng địa điểm được hỏi, hãy gợi ý tương tự.",
        "room_search":      "Tập trung vào thông tin phòng: loại phòng, tiện ích, diện tích, giá.",
    }
    hint = intent_hints.get(intent, "Gợi ý tối đa 3-5 địa điểm phù hợp nhất.")

    user_content = f"""\
THÔNG TIN ĐỊA ĐIỂM DU LỊCH ĐÀ NẴNG:
{context}

---
Câu hỏi: {query}

Hướng dẫn bổ sung: {hint}"""

    messages = [
        {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]
    return llm_chat(
        messages,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=True,
        temperature=0.3,
        # enable_thinking=True,
        enable_thinking=False,   # Thinking OFF
    )


print("✅ Planner/Synthesizer sẵn sàng.")

# ============================================================
# Cell 12 – Full RAG Pipeline
# Cập nhật: Loại bỏ ghi log keywords, format log in ra active filters
# ============================================================

def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip() if text else ""


def _doc_name(doc: Dict[str, Any]) -> str:
    payload = doc.get("payload", {})
    return payload.get("place_name") or payload.get("entity_name") or ""


def _dedupe_docs_by_name(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for doc in docs:
        name = _normalize_text(_doc_name(doc))
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(doc)
    return unique


def _find_exact_matches(query: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query_lower = _normalize_text(query)
    matches = []
    for doc in docs:
        name = _normalize_text(_doc_name(doc))
        if not name:
            continue
        base_name, branch_name = name, ""
        if " - " in name:
            base_name, branch_name = name.split(" - ", 1)
        if len(base_name) >= 4 and base_name in query_lower:
            if branch_name:
                branch_words = [w for w in branch_name.split() if len(w) > 3]
                if branch_name not in query_lower and not any(w in query_lower for w in branch_words):
                    continue
            matches.append(doc)
    return matches


def _build_specific_fallback(query: str, docs: List[Dict[str, Any]]) -> str:
    lines = []
    for doc in docs[:MAX_ALTERNATIVES]:
        payload = doc.get("payload", {})
        name = _doc_name(doc)
        if not name:
            continue
        parts = [f"- {name}"]
        if payload.get("address"):
            parts.append(f"  Địa chỉ: {payload['address']}")
        if payload.get("rating") is not None:
            parts.append(f"  Đánh giá: {payload['rating']}/10")
        lines.append("\n".join(parts))

    suggestions = "\n\n".join(lines) if lines else ""
    if suggestions:
        return (
            f"Dạ, tôi chưa tìm thấy thông tin chính xác tuyệt đối cho '{query}'. "
            "Có phải bạn đang muốn tìm một trong các địa điểm nổi bật dưới đây không:\n\n"
            f"{suggestions}\n\n"
            "Nếu đúng, bạn vui lòng cho tôi biết tên đầy đủ hoặc địa chỉ cụ thể hơn để tôi tư vấn nhé!"
        )
    else:
        return (
            "Dạ, tôi chưa tìm thấy thông tin chính xác cho địa điểm bạn vừa hỏi. "
            "Bạn có thể cung cấp thêm tên đầy đủ, địa chỉ hoặc chi nhánh để tôi hỗ trợ được không ạ?"
        )
class DanangRAGPipeline:
    """
    Pipeline RAG cho chatbot tư vấn du lịch Đà Nẵng.
    """
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def answer(
        self,
        query: str,
        top_k_retrieve: int = TOP_K_RETRIEVE,
        top_k_rerank:   int = TOP_K_RERANK,
    ) -> Dict[str, Any]:
        """Xử lý câu hỏi qua RAG Pipeline."""
        self._log(f"\n{'='*70}")
        self._log(f"📥 Câu hỏi: {query}")
        self._log("=" * 70)

        # ── Bước 1: Router ──
        self._log("\n🔀 [Router] Phân loại câu hỏi...")
        route     = router(query)
        intent    = route["intent"]
        needs_rag = route["needs_rag"]
        self._log(f"   Intent: {intent} | Needs RAG: {needs_rag}")
        self._log(f"   Lý do: {route.get('reason', '')}")

        # Chitchat: bỏ qua RAG
        if not needs_rag:
            self._log("\n💬 [Chitchat Mode] Trả lời trực tiếp...")
            ans = synthesizer(query, "", "chitchat", {})
            self._log(f"\n{'─'*70}")
            self._log(f"💬 Câu trả lời:\n{ans}")
            self._log("─" * 70)
            return {
                "answer": ans, "intent": intent, "search_query": query,
                "extracted": {}, "docs": [], "needs_rag": False,
            }

        # ── PHÂN LUỒNG ĐẶC BIỆT CHO SPECIFIC SEARCH (KHÔNG DÙNG EXTRACTOR) ──
        if intent == "specific_search":
            self._log("\n🔍 [Specific Search Flow] Trích xuất danh sách thực thể...")
            entities = extract_specific_entities(query)
            self._log(f"   Entities: {entities}")
            if not entities:
                entities = [query]

            all_exact_matches = []
            all_ranked_docs = []
            
            for entity_name in entities:
                empty_extracted = {
                    "filters": {},
                    "entity": [entity_name],
                    "intent": "specific_search",
                    "core_query": entity_name,
                    "semantic_query": entity_name
                }

                self._log(f"\n📚 [Retriever] Tìm kiếm vector với thực thể: {entity_name!r}")
                target_collections = INTENT_TO_COLLECTIONS.get("specific_search", [COL_PLACES, COL_RESTAURANTS, COL_HOTELS, COL_ROOMS])
                query_vec = embedder.encode([entity_name], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
                raw_docs = retrieve(query_vec, target_collections, empty_extracted, top_k=top_k_retrieve)

                self._log(f"🏆 [Reranker] Xếp hạng lại {len(raw_docs)} docs cho {entity_name!r}...")
                ranked_docs = rerank(entity_name, raw_docs, empty_extracted, top_n=top_k_rerank)
                top_rerank_score = ranked_docs[0].get("rerank_score", 0.0) if ranked_docs else 0.0
                deduped_docs = _dedupe_docs_by_name(ranked_docs)

                # Lọc chính xác
                exact_matches = []
                entity_name_lower = _normalize_text(entity_name)
                for doc in deduped_docs:
                    doc_name_lower = _normalize_text(_doc_name(doc))
                    if entity_name_lower in doc_name_lower or doc_name_lower in entity_name_lower:
                        exact_matches.append(doc)

                exact_match_found = len(exact_matches) > 0
                low_confidence = top_rerank_score < RERANK_SCORE_THRESHOLD

                if not exact_match_found or low_confidence:
                    self._log(f"🧭 [Specific Search] Không tìm thấy thực thể chính xác cho: {entity_name!r}")
                    all_ranked_docs.extend(ranked_docs)
                else:
                    all_exact_matches.extend(exact_matches[:3])
            
            # Khử trùng lặp giữa các thực thể
            exact_matches_deduped = _dedupe_docs_by_name(all_exact_matches)
            ranked_docs_deduped = _dedupe_docs_by_name(all_ranked_docs)

            if not exact_matches_deduped:
                self._log("\n🧭 [Specific Search] Không tìm thấy bất kỳ thực thể chính xác nào → gợi ý thay thế...")
                answer_text = _build_specific_fallback(query, ranked_docs_deduped)
                self._log(f"\n{'─'*70}")
                self._log(f"💬 Câu trả lời:\n{answer_text}")
                self._log("─" * 70)
                combined_extracted = {
                    "filters": {},
                    "entity": entities,
                    "intent": "specific_search",
                    "core_query": ", ".join(entities),
                    "semantic_query": ", ".join(entities)
                }
                return {
                    "answer": answer_text, "intent": intent, "search_query": query,
                    "extracted": combined_extracted, "docs": ranked_docs_deduped, "needs_rag": True,
                }

            self._log("\n📝 [Context Builder] Ghép context + parent lookup...")
            context, enriched_docs = build_context(query, exact_matches_deduped, fetch_parents=True)
            self._log(f"   Context: {len(context)} ký tự | {len(enriched_docs)} docs (bao gồm parent)")

            combined_extracted = {
                "filters": {},
                "entity": entities,
                "intent": "specific_search",
                "core_query": ", ".join(entities),
                "semantic_query": ", ".join(entities)
            }

            self._log("\n🤖 [Synthesizer] Tổng hợp câu trả lời...")
            answer_text = synthesizer(query, context, intent, combined_extracted)

            self._log(f"\n{'─'*70}")
            self._log(f"💬 Câu trả lời:\n{answer_text}")
            self._log("─" * 70)

            return {
                "answer": answer_text, "intent": intent, "search_query": ", ".join(entities),
                "extracted": combined_extracted, "docs": exact_matches_deduped, "needs_rag": True,
            }

        # ── LUỒNG THÔNG THƯỜNG (DÙNG EXTRACTOR) ──
        # ── Bước 2: Extractor ──
        self._log("\n🔍 [Extractor] Trích xuất thông tin có cấu trúc...")
        extracted = extractor(query, intent)
        filters = extracted.get("filters", {})
        self._log(f"   Entity:    {extracted.get('entity')}")
        self._log(f"   Semantic:  {extracted.get('semantic_query')!r}")
        
        # In các bộ lọc thực tế trích xuất được (loại bỏ null và list rỗng)
        active_filters = {k: v for k, v in filters.items() if v is not None and v != []}
        self._log(f"   Filters:   {active_filters}")

        # ── Bước 3: Xác định search_query ──
        search_query = extracted.get("semantic_query") or extracted.get("core_query") or query

        # ── Bước 4: Retrieval + Rerank ──
        if intent == "itinerary_search":
            self._log("\n📚 [Itinerary Mode] Phân luồng tìm kiếm song song...")

            # Luồng 1: Vui chơi
            q_places = f"địa điểm du lịch vui chơi tham quan {extracted.get('core_query', '')}".strip()
            self._log(f"   🎭 Query vui chơi: {q_places!r}")
            vec_places = embedder.encode([q_places], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
            docs_places = retrieve(vec_places, [COL_PLACES, COL_PLACE_REVIEWS], extracted, top_k=10)
            ranked_places = rerank(q_places, docs_places, extracted, top_n=3)

            # Luồng 2: Ăn uống
            q_rests = f"nhà hàng quán ăn đặc sản ngon {extracted.get('core_query', '')}".strip()
            self._log(f"   🍜 Query ăn uống: {q_rests!r}")
            vec_rests = embedder.encode([q_rests], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
            docs_rests = retrieve(vec_rests, [COL_RESTAURANTS, COL_RESTAURANT_REVIEWS], extracted, top_k=10)
            ranked_rests = rerank(q_rests, docs_rests, extracted, top_n=3)

            # Luồng 3: Lưu trú
            q_hotels = f"khách sạn homestay resort lưu trú {extracted.get('core_query', '')}".strip()
            self._log(f"   🏨 Query lưu trú: {q_hotels!r}")
            vec_hotels = embedder.encode([q_hotels], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
            docs_hotels = retrieve(vec_hotels, [COL_HOTELS, COL_HOTEL_REVIEWS, COL_ROOMS], extracted, top_k=10)
            ranked_hotels = rerank(q_hotels, docs_hotels, extracted, top_n=3)

            # Gộp kết quả phân tầng
            deduped_docs = (
                _dedupe_docs_by_name(ranked_places)[:2]
                + _dedupe_docs_by_name(ranked_rests)[:2]
                + _dedupe_docs_by_name(ranked_hotels)[:2]
            )
            ranked_docs = ranked_places + ranked_rests + ranked_hotels
            top_rerank_score = max([d.get("rerank_score", 0.0) for d in ranked_docs]) if ranked_docs else 0.0

        else:
            # Luồng tìm kiếm đơn
            self._log(f"\n📚 [Retriever] Tìm kiếm vector với query: {search_query!r}")
            target_collections = INTENT_TO_COLLECTIONS.get(intent, [COL_PLACES, COL_RESTAURANTS, COL_HOTELS])
            query_vec = embedder.encode([search_query], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
            raw_docs = retrieve(query_vec, target_collections, extracted, top_k=top_k_retrieve)
            self._log(f"   Tìm được {len(raw_docs)} docs từ {len(target_collections)} collections")

            if not raw_docs:
                self._log("   ⚠️  Không tìm được kết quả. Thử lại với query gốc + không filter...")
                fallback_vec = embedder.encode([query], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
                raw_docs = retrieve(fallback_vec, target_collections, {"filters": {}}, top_k=top_k_retrieve)

            # Rerank dùng query GỐC
            self._log(f"\n🏆 [Reranker] Xếp hạng lại {len(raw_docs)} docs...")
            ranked_docs = rerank(query, raw_docs, extracted, top_n=top_k_rerank)
            top_rerank_score = ranked_docs[0].get("rerank_score", 0.0) if ranked_docs else 0.0
            deduped_docs = _dedupe_docs_by_name(ranked_docs)

        low_confidence = top_rerank_score < RERANK_SCORE_THRESHOLD
        self._log(f"   Top docs sau rerank:")
        for d in ranked_docs[:3]:
            place = d.get("payload", {}).get("place_name", d["collection"])
            self._log(f"   - {place} | vector={d['score']:.3f} | rerank={d.get('rerank_score', 0):.3f}")
        if low_confidence:
            self._log(f"   ⚠️  Rerank score thấp ({top_rerank_score:.3f} < {RERANK_SCORE_THRESHOLD}).")

        # ── Bước 5: Post-processing ──
        exact_matches = _find_exact_matches(query, deduped_docs)
        exact_match_found = len(exact_matches) > 0

        if exact_match_found:
            deduped_docs = exact_matches[:3]
        else:
            deduped_docs = deduped_docs[:top_k_rerank]

        # ── Bước 6: Context Builder ──
        self._log("\n📝 [Context Builder] Ghép context + parent lookup...")
        context, enriched_docs = build_context(search_query, deduped_docs, fetch_parents=True)
        self._log(f"   Context: {len(context)} ký tự | {len(enriched_docs)} docs (bao gồm parent)")

        # ── Bước 7: Synthesizer ──
        self._log("\n🤖 [Synthesizer] Tổng hợp câu trả lời (thinking=OFF)...")
        answer_text = synthesizer(query, context, intent, extracted)

        self._log(f"\n{'─'*70}")
        self._log(f"💬 Câu trả lời:\n{answer_text}")
        self._log("─" * 70)

        return {
            "answer": answer_text, "intent": intent, "search_query": search_query,
            "extracted": extracted, "docs": ranked_docs, "needs_rag": True,
        }


# Khởi tạo pipeline
pipeline = DanangRAGPipeline(verbose=True)
print("\n✅ RAG Pipeline (Qwen3.5-4B) khởi tạo thành công!")


YOUR_QUERY = "So sánh Sandy Beach Non Nuoc Resort và Royal Charm Hotel?"  # ← Thay câu hỏi của bạn tại đây

result = pipeline.answer(YOUR_QUERY)

print("\n" + "="*70)
print("📊 METADATA KẾT QUẢ TÌM KIẾM")
print("="*70)
print(f"Intent đã phân loại:  {result['intent']}")
print(f"Query tìm kiếm thực tế: {result['search_query']}")
print(f"\nTop tài liệu tìm thấy:")
for d in result['docs'][:5]:
    place = d.get('payload', {}).get('place_name') or d.get('payload', {}).get('room_name') or 'N/A'
    col   = d.get('collection', '')
    vs    = d.get('score', 0)
    rs    = d.get('rerank_score', 0)
    print(f"  - [{col}] {place} | vector={vs:.3f}, rerank={rs:.3f}")


QUERIES_GROUP_1 = [
    "Chợ Cồn nằm ở đâu và mở cửa lúc mấy giờ?",
    "Đà Nẵng có những địa điểm check-in, sống ảo nào nổi tiếng?",
]

for q in QUERIES_GROUP_1:
    pipeline.answer(q)
    print("\n" + "-"*70 + "\n")

QUERIES_GROUP_2 = [
    "Tối nay mình muốn đi ăn hải sản ở Sơn Trà, có quán nào ngon rẻ không?",
    "Tìm quán ăn vặt vỉa hè ngon tầm trung ở quận Hải Châu"
]

for q in QUERIES_GROUP_2:
    pipeline.answer(q)
    print("\n" + "-"*70 + "\n")

QUERIES_GROUP_3 = [
    "Gợi ý cho tôi vài khách sạn ở Sơn Trà cho gia đình 4 người",
    "Tìm phòng view biển có giường đôi ở Sơn Trà dưới 4 triệu"
]

for q in QUERIES_GROUP_3:
    pipeline.answer(q)
    print("\n" + "-"*70 + "\n")

QUERIES_GROUP_4 = [
    "Khách hàng nhận xét thế nào về quán hải sản Năm Đảnh?",
    "Gợi ý lịch trình du lịch Đà Nẵng 3 ngày 2 đêm tự túc cho nhóm bạn kết hợp ăn chơi và khách sạn"
]

for q in QUERIES_GROUP_4:
    pipeline.answer(q)
    print("\n" + "-"*70 + "\n")

QUERIES_GROUP_5 = [
    "Bạn là ai và bạn có thể giúp gì cho mình?",
    "Thời tiết Đà Nẵng tháng 7 thế nào?"
]

for q in QUERIES_GROUP_5:
    pipeline.answer(q)
    print("\n" + "-"*70 + "\n")

YOUR_QUERY = "Khách sạn Novotel Đà Nẵng có phòng suite cho 2 người không?"  # ← Thay câu hỏi của bạn tại đây

result = pipeline.answer(YOUR_QUERY)

print("\n" + "="*70)
print("📊 METADATA KẾT QUẢ TÌM KIẾM")
print("="*70)
print(f"Intent đã phân loại:  {result['intent']}")
print(f"Query tìm kiếm thực tế: {result['search_query']}")
print(f"\nTop tài liệu tìm thấy:")
for d in result['docs'][:5]:
    place = d.get('payload', {}).get('place_name') or d.get('payload', {}).get('room_name') or 'N/A'
    col   = d.get('collection', '')
    vs    = d.get('score', 0)
    rs    = d.get('rerank_score', 0)
    print(f"  - [{col}] {place} | vector={vs:.3f}, rerank={rs:.3f}")