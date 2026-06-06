"""Bộ đánh giá RAG — chạy benchmark trên pipeline THẬT của app.

Khác notebook (gọi `pipeline.answer()` đồng bộ), pipeline app là async streaming
`RAGPipeline.answer_stream()`. `run_query()` là adapter gom các event stream về dạng
dict {intent, docs, answer, latency_retrieval, latency_total} để các hàm metric thuần
(port từ pbl7-metrics.ipynb) tính toán.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

from app import config

K_VALUES = (1, 3, 5)

# ── Heuristic generation (port cell 13) ──────────────────────────────────────
REFUSE_PHRASES = [
    "xin lỗi", "tôi không biết", "không có thông tin",
    "tôi không chắc", "không tìm thấy",
    "chưa cập nhật thông tin",
    "hệ thống chưa có thông tin",
    "chưa có thông tin về",
    "hiện chưa có thông tin",
    "chỉ hỗ trợ tư vấn du lịch",
    "không trả lời được",
    "nằm ngoài phạm vi",
]

POSITIVE_SIGNALS = [
    "địa chỉ", "mức giá", "đường ", "quận",
    "điểm nổi bật", "đánh giá", "rating",
    "vnd", "vnđ", "nghìn", "triệu",
    "khách sạn", "nhà hàng", "địa điểm",
    "ngày 1", "ngày 2",
    "★", "⭐", "🏨", "🍜", "🌍",
]


# ── Adapter: chạy 1 query qua pipeline thật ──────────────────────────────────
async def run_query(pipeline, query: str) -> Dict[str, Any]:
    """Chạy 1 query qua `pipeline.answer_stream` và gom kết quả.

    Trả về dict: intent (str), docs (list payload — thường có 'collection'), answer (str),
    error (str | None — message từ event 'error' nếu pipeline báo lỗi), latency_retrieval
    (s | None), latency_total (s).

    `error` khác None nghĩa là query thất bại giữa chừng (vd Gemini gián đoạn) — caller
    phải LOẠI khỏi metric thay vì coi là câu trả lời chất lượng thấp, tránh sai số liệu.

    Acquire `inference_lock` của chat để không tranh GPU đơn với request chat đang chạy.
    """
    from app.api.chat import inference_lock  # lazy import tránh circular

    stop_event = threading.Event()
    intent = ""
    docs: List[Dict[str, Any]] = []
    answer_parts: List[str] = []
    error: Optional[str] = None
    t0 = time.perf_counter()
    t_sources: Optional[float] = None

    async with inference_lock:
        async for ev in pipeline.answer_stream(
            query=query,
            history=[],
            stop_event=stop_event,
            max_new_tokens=config.DEFAULT_MAX_TOKENS,
        ):
            etype = ev.get("type")
            if etype == "intent":
                intent = ev.get("value", "")
            elif etype == "sources":
                docs = ev.get("items", []) or []
                if t_sources is None:
                    t_sources = time.perf_counter()
            elif etype == "token":
                answer_parts.append(ev.get("text", ""))
            elif etype == "done":
                break
            elif etype == "error":
                error = ev.get("message", "lỗi pipeline không rõ")
                break

    t_done = time.perf_counter()
    latency_retrieval = (t_sources - t0) if t_sources is not None else None
    return {
        "intent": intent,
        "docs": docs,
        "answer": "".join(answer_parts),
        "error": error,
        "latency_retrieval": round(latency_retrieval, 3) if latency_retrieval is not None else None,
        "latency_total": round(t_done - t0, 3),
    }


# ── Retrieval metrics (port cell 10) ─────────────────────────────────────────
def retrieval_metrics(
    item: Dict[str, Any],
    docs: List[Dict[str, Any]],
    detected_intent: str,
    latency_retrieval: Optional[float] = None,
    k_values=K_VALUES,
) -> Dict[str, Any]:
    exp_col = set(item["expected_collections"])
    retrieved_collections = [d.get("collection", "") for d in docs]

    row: Dict[str, Any] = {
        "id": item["id"],
        "category": item["category"],
        "expected_intent": item["expected_intent"],
        "detected_intent": detected_intent,
        "intent_correct": detected_intent == item["expected_intent"],
        "n_retrieved": len(docs),
        "latency_retrieval": latency_retrieval,
    }

    for k in k_values:
        top_k_cols = set(retrieved_collections[:k])
        hit = int(bool(top_k_cols & exp_col))
        precision = len(top_k_cols & exp_col) / k if k > 0 else 0
        row[f"recall@{k}"] = hit
        row[f"precision@{k}"] = round(precision, 3)

    mrr = 0.0
    for rank, col in enumerate(retrieved_collections, start=1):
        if col in exp_col:
            mrr = 1.0 / rank
            break
    row["mrr"] = round(mrr, 4)
    return row


# ── Generation metrics (port cell 13) ────────────────────────────────────────
def generation_metrics(item: Dict[str, Any], answer_text: str) -> Dict[str, Any]:
    keywords = item.get("keywords", [])
    ans_lower = answer_text.lower()

    kw_hits = sum(1 for kw in keywords if kw.lower() in ans_lower)
    kw_score = kw_hits / len(keywords) if keywords else 0.0

    has_refusal = any(p in ans_lower for p in REFUSE_PHRASES)
    has_content = any(s in ans_lower for s in POSITIVE_SIGNALS)
    has_min_length = len(answer_text.strip()) >= 80

    is_resolved = (not has_refusal) and has_content and has_min_length
    is_complete = has_min_length and has_content

    return {
        "id": item["id"],
        "category": item["category"],
        "answer": answer_text[:200],
        "kw_score": round(kw_score, 2),
        "is_resolved": is_resolved,
        "is_complete": is_complete,
        "has_refusal": has_refusal,
        "has_content": has_content,
    }


# ── Itinerary structure evaluator (port cell 24) ─────────────────────────────
class ItineraryStructureEvaluator:
    """Đánh giá cấu trúc câu trả lời lịch trình bằng heuristics + regex (không dùng LLM)."""

    DAY_PATTERNS = [
        r"ngày\s*\d+",
        r"day\s*\d+",
        r"buổi\s*(sáng|trưa|chiều|tối)",
        r"\*\*ngày\s*\d+\*\*",
        r"📅",
    ]

    HOTEL_KEYWORDS = ["khách sạn", "resort", "nhà nghỉ", "homestay", "check-in", "lưu trú", "phòng"]
    FOOD_KEYWORDS = ["ăn", "nhà hàng", "quán", "hải sản", "mì quảng", "bún", "bánh", "buffet", "đặc sản", "ẩm thực"]
    ATTRACTION_KWORDS = ["tham quan", "biển", "cầu", "chùa", "công viên", "bán đảo", "núi", "bảo tàng", "đèo", "hội an"]
    HALLUCINATION_KW = ["hà nội", "hồ chí minh", "sài gòn", "đà lạt", "nha trang", "phú quốc"]

    def evaluate(self, answer: str, criteria: dict) -> dict:
        ans = answer.lower()

        day_hits = sum(1 for p in self.DAY_PATTERNS if re.search(p, ans))
        has_daily_structure = day_hits >= 1

        day_numbers = re.findall(r"ngày\s*(\d+)", ans)
        days_mentioned = max((int(d) for d in day_numbers), default=0) if day_numbers else 0

        has_hotel = any(kw in ans for kw in self.HOTEL_KEYWORDS)
        has_food = any(kw in ans for kw in self.FOOD_KEYWORDS)
        has_attractions = any(kw in ans for kw in self.ATTRACTION_KWORDS)

        hallucination_hits = [kw for kw in self.HALLUCINATION_KW if kw in ans]
        has_hallucination = len(hallucination_hits) > 0

        min_days_req = criteria.get("min_days_mentioned", 1)
        days_ok = days_mentioned >= min_days_req or not criteria.get("has_daily_structure", True)
        hotel_ok = has_hotel if criteria.get("has_hotel", True) else True
        food_ok = has_food if criteria.get("has_food", True) else True
        attract_ok = has_attractions if criteria.get("has_attractions", True) else True
        structure_ok = has_daily_structure if criteria.get("has_daily_structure", True) else True

        component_scores = {
            "structure": 1.0 if structure_ok else 0.0,
            "days": min(1.0, days_mentioned / max(min_days_req, 1)),
            "hotel": 1.0 if hotel_ok else 0.0,
            "food": 1.0 if food_ok else 0.0,
            "attractions": 1.0 if attract_ok else 0.0,
            "no_hallucination": 0.0 if has_hallucination else 1.0,
        }

        weights = {
            "structure": 0.20,
            "days": 0.20,
            "hotel": 0.15,
            "food": 0.15,
            "attractions": 0.15,
            "no_hallucination": 0.15,
        }

        overall = sum(component_scores[k] * weights[k] for k in weights)

        # days_ok giữ lại để debug độ đầy đủ ngày, không vào điểm tổng.
        return {
            "has_daily_structure": has_daily_structure,
            "days_mentioned": days_mentioned,
            "days_ok": days_ok,
            "has_hotel": has_hotel,
            "has_food": has_food,
            "has_attractions": has_attractions,
            "hallucination_hits": hallucination_hits,
            "no_hallucination": not has_hallucination,
            "component_scores": component_scores,
            "itinerary_score": round(overall, 3),
        }


# ── Report card (port cell 22) ───────────────────────────────────────────────
def _mean(values: List[float]) -> float:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else 0.0


def build_report_card(
    ret_rows: List[Dict[str, Any]],
    gen_rows: List[Dict[str, Any]],
    perf_rows: List[Dict[str, Any]],
    judge_means: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Tạo report card [{group, metric, score, target, pass}] từ các hàng metric.

    `pass` là chuỗi "✅"/"❌" (KHÔNG phải bool) — dashboard + template so khớp đúng ký tự này.
    `perf_rows`: list dict có 'latency_retrieval', 'latency_total'.
    `judge_means`: {'faithfulness','relevance','accuracy'} (None nếu không chạy judge).
    """
    intent_acc = _mean([r["intent_correct"] for r in ret_rows])
    mrr = _mean([r["mrr"] for r in ret_rows])
    recall5 = _mean([r["recall@5"] for r in ret_rows])
    resolution = _mean([r["is_resolved"] for r in gen_rows])
    kw_cov = _mean([r["kw_score"] for r in gen_rows])
    avg_ret_lat = _mean([r.get("latency_retrieval") for r in perf_rows])
    avg_tot_lat = _mean([r.get("latency_total") for r in perf_rows])

    def entry(group, metric, score, target, ok):
        return {"group": group, "metric": metric, "score": score,
                "target": target, "pass": "✅" if ok else "❌"}

    card = [
        entry("Retrieval", "Intent Accuracy", f"{intent_acc*100:.1f}%", "≥ 80%", intent_acc >= 0.8),
        entry("Retrieval", "MRR", f"{mrr:.3f}", "≥ 0.60", mrr >= 0.6),
        entry("Retrieval", "Recall@5", f"{recall5*100:.1f}%", "≥ 70%", recall5 >= 0.7),
        entry("Generation", "Resolution Rate", f"{resolution*100:.1f}%", "≥ 85%", resolution >= 0.85),
        entry("Generation", "Keyword Coverage", f"{kw_cov:.2f}", "≥ 0.70", kw_cov >= 0.7),
    ]

    if judge_means:
        f = judge_means.get("faithfulness")
        rel = judge_means.get("relevance")
        acc = judge_means.get("accuracy")
        if f is not None:
            card.append(entry("Generation", "Faithfulness (1–5)", f"{f:.2f}", "≥ 4.0", f >= 4.0))
        if rel is not None:
            card.append(entry("Generation", "Relevance (1–5)", f"{rel:.2f}", "≥ 4.0", rel >= 4.0))
        if acc is not None:
            card.append(entry("Generation", "Accuracy (1–5)", f"{acc:.2f}", "≥ 3.8", acc >= 3.8))

    card += [
        entry("System", "Avg Retrieval Latency", f"{avg_ret_lat:.2f}s", "< 2.0s", avg_ret_lat < 2.0),
        entry("System", "Avg Total Latency", f"{avg_tot_lat:.2f}s", "< 15s", avg_tot_lat < 15),
    ]
    return card
