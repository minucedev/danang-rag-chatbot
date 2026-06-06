"""Test các hàm metric thuần (không cần Qdrant/GPU/Gemini)."""
from __future__ import annotations

from app.metrics.evaluator import (
    ItineraryStructureEvaluator,
    build_report_card,
    generation_metrics,
    retrieval_metrics,
)


def _docs(*collections):
    return [{"collection": c} for c in collections]


# ── retrieval_metrics ────────────────────────────────────────────────────────
def test_retrieval_perfect_top1():
    item = {
        "id": "X1", "category": "Khách sạn",
        "expected_intent": "hotel_search",
        "expected_collections": ["accommodation_hotels_danang"],
    }
    docs = _docs("accommodation_hotels_danang", "restaurants_danang", "places_danang")
    row = retrieval_metrics(item, docs, "hotel_search", latency_retrieval=0.5)

    assert row["intent_correct"] is True
    assert row["recall@1"] == 1 and row["recall@3"] == 1 and row["recall@5"] == 1
    assert row["mrr"] == 1.0
    assert row["latency_retrieval"] == 0.5


def test_retrieval_hit_at_rank3_and_intent_wrong():
    item = {
        "id": "X2", "category": "Địa điểm",
        "expected_intent": "place_search",
        "expected_collections": ["places_danang"],
    }
    docs = _docs("restaurants_danang", "restaurants_danang", "places_danang")
    row = retrieval_metrics(item, docs, "restaurant_search")

    assert row["intent_correct"] is False
    assert row["recall@1"] == 0
    assert row["recall@3"] == 1
    assert row["mrr"] == round(1 / 3, 4)


def test_retrieval_no_hit():
    item = {
        "id": "X3", "category": "Giá",
        "expected_intent": "price_search",
        "expected_collections": ["accommodation_hotels_danang"],
    }
    row = retrieval_metrics(item, _docs("places_danang"), "price_search")
    assert row["recall@5"] == 0
    assert row["mrr"] == 0.0


# ── generation_metrics ───────────────────────────────────────────────────────
def test_generation_refusal_not_resolved():
    item = {"id": "G1", "category": "Khách sạn", "keywords": ["khách sạn", "giá"]}
    ans = "Xin lỗi, hiện chưa có thông tin về khách sạn bạn cần. " * 3
    row = generation_metrics(item, ans)
    assert row["has_refusal"] is True
    assert row["is_resolved"] is False


def test_generation_rich_answer_resolved():
    item = {"id": "G2", "category": "Khách sạn", "keywords": ["khách sạn", "giá"]}
    ans = ("Khách sạn Mỹ Khê có địa chỉ ở quận Sơn Trà, mức giá khoảng 900 nghìn VND mỗi đêm, "
           "đánh giá tốt và gần biển rất tiện lợi cho du khách.")
    row = generation_metrics(item, ans)
    assert row["has_refusal"] is False
    assert row["has_content"] is True
    assert row["is_resolved"] is True
    assert row["kw_score"] == 1.0  # cả 2 keyword xuất hiện


def test_generation_too_short_not_resolved():
    item = {"id": "G3", "category": "Khách sạn", "keywords": ["khách sạn"]}
    row = generation_metrics(item, "Có khách sạn.")
    assert row["is_resolved"] is False  # < 80 ký tự


# ── ItineraryStructureEvaluator ──────────────────────────────────────────────
def test_itinerary_full_structure():
    ev = ItineraryStructureEvaluator()
    ans = ("Ngày 1: nhận phòng khách sạn ven biển, ăn hải sản. "
           "Ngày 2: tham quan bán đảo Sơn Trà và chùa Linh Ứng. "
           "Ngày 3: ăn mì quảng rồi ra biển Mỹ Khê.")
    crit = {"has_daily_structure": True, "has_hotel": True, "has_food": True,
            "has_attractions": True, "min_days_mentioned": 3}
    out = ev.evaluate(ans, crit)
    assert out["has_daily_structure"] is True
    assert out["days_mentioned"] == 3
    assert out["has_hotel"] and out["has_food"] and out["has_attractions"]
    assert out["no_hallucination"] is True
    assert out["itinerary_score"] == 1.0


def test_itinerary_hallucination_penalized():
    ev = ItineraryStructureEvaluator()
    ans = "Ngày 1: bay ra Hà Nội chơi hồ Gươm. Ngày 2: vào Sài Gòn ăn uống."
    crit = {"has_daily_structure": True, "has_hotel": True, "has_food": True,
            "has_attractions": True, "min_days_mentioned": 2}
    out = ev.evaluate(ans, crit)
    assert out["no_hallucination"] is False
    assert "hà nội" in out["hallucination_hits"]
    assert out["itinerary_score"] < 1.0


# ── build_report_card ────────────────────────────────────────────────────────
def test_report_card_pass_fail():
    ret_rows = [
        {"intent_correct": True, "mrr": 1.0, "recall@5": 1},
        {"intent_correct": True, "mrr": 1.0, "recall@5": 1},
    ]
    gen_rows = [
        {"is_resolved": True, "kw_score": 0.9},
        {"is_resolved": True, "kw_score": 0.8},
    ]
    perf_rows = [
        {"latency_retrieval": 0.5, "latency_total": 5.0},
        {"latency_retrieval": 0.7, "latency_total": 6.0},
    ]
    card = build_report_card(ret_rows, gen_rows, perf_rows)
    by_metric = {r["metric"]: r["pass"] for r in card}
    assert by_metric["Intent Accuracy"] == "✅"
    assert by_metric["Recall@5"] == "✅"
    assert by_metric["Resolution Rate"] == "✅"
    assert by_metric["Avg Total Latency"] == "✅"


def test_report_card_with_judge():
    ret_rows = [{"intent_correct": False, "mrr": 0.0, "recall@5": 0}]
    gen_rows = [{"is_resolved": False, "kw_score": 0.1}]
    perf_rows = [{"latency_retrieval": 3.0, "latency_total": 20.0}]
    card = build_report_card(ret_rows, gen_rows, perf_rows,
                             judge_means={"faithfulness": 4.5, "relevance": 3.0, "accuracy": 4.0})
    by_metric = {r["metric"]: r["pass"] for r in card}
    assert by_metric["Intent Accuracy"] == "❌"
    assert by_metric["Avg Total Latency"] == "❌"
    assert by_metric["Faithfulness (1–5)"] == "✅"
    assert by_metric["Relevance (1–5)"] == "❌"
