----------------------------------------
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
----------------------------------------
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
----------------------------------------
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

