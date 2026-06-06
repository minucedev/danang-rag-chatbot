"""Orchestrator chạy benchmark trên pipeline thật — 1 lượt tại 1 thời điểm.

Chạy tuần tự từng query (qua `evaluator.run_query`), tính metric, phát tiến độ qua
`progress_bus`, rồi lưu kết quả + report card bằng `store`.
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional

from . import evaluator, judge, store
from .benchmark import BENCHMARK, BENCHMARK_ITINERARY
from .progress import progress_bus

# State module-level (chạy trên asyncio loop đơn luồng — không cần lock).
_state: Dict[str, Any] = {
    "running": False,
    "suite": None,
    "started_at": None,
    "current": 0,
    "total": 0,
}
_latest: Optional[Dict[str, Any]] = None


def get_state() -> Dict[str, Any]:
    return dict(_state)


def is_running() -> bool:
    return bool(_state["running"])


def get_latest() -> Optional[Dict[str, Any]]:
    return _latest


def _log(msg: str) -> None:
    progress_bus.publish(msg)


def _get_pipeline():
    from app.rag import pipeline as pl_module
    return pl_module._pipeline_instance


async def run_eval(suite: str = "both", enable_judge: bool = True) -> Optional[Dict[str, Any]]:
    """Chạy benchmark. suite ∈ {'general','itinerary','both'}."""
    global _latest

    if _state["running"]:
        _log("⚠️ Đang có một lượt eval chạy.")
        return None

    pipeline = _get_pipeline()
    if pipeline is None:
        _log("❌ Pipeline chưa sẵn sàng (model chưa load xong).")
        return None

    general_items = BENCHMARK if suite in ("general", "both") else []
    itinerary_items = BENCHMARK_ITINERARY if suite in ("itinerary", "both") else []
    total = len(general_items) + len(itinerary_items)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    _state.update(running=True, suite=suite, started_at=int(time.time()), current=0, total=total)
    judge_on = enable_judge and judge.is_available()
    _log(f"🚀 Bắt đầu eval suite='{suite}' — {total} câu hỏi. Judge: {'BẬT' if judge_on else 'TẮT'}.")

    ret_rows: List[Dict[str, Any]] = []
    gen_rows: List[Dict[str, Any]] = []
    perf_rows: List[Dict[str, Any]] = []
    itin_rows: List[Dict[str, Any]] = []
    errored: List[str] = []
    struct_eval = evaluator.ItineraryStructureEvaluator()
    idx = 0

    async def _run_one(item) -> Optional[Dict[str, Any]]:
        """Chạy 1 query, cô lập lỗi: trả None (và ghi nhận errored) nếu hỏng — để 1 câu
        lỗi không phá cả lượt và không bị tính như câu trả lời chất lượng thấp."""
        try:
            res = await evaluator.run_query(pipeline, item["query"])
        except Exception as exc:  # noqa: BLE001 — cô lập theo từng câu, vẫn báo to
            _log(f"⚠️ [{idx}/{total}] {item['id']} lỗi: {type(exc).__name__}: {exc}")
            errored.append(item["id"])
            return None
        if res.get("error"):
            _log(f"⚠️ [{idx}/{total}] {item['id']} pipeline error: {res['error']}")
            errored.append(item["id"])
            return None
        return res

    try:
        # ── General benchmark ──
        for item in general_items:
            idx += 1
            _state["current"] = idx
            res = await _run_one(item)
            if res is None:
                continue

            ret = evaluator.retrieval_metrics(
                item, res["docs"], res["intent"], res["latency_retrieval"]
            )
            gen = evaluator.generation_metrics(item, res["answer"])

            if judge_on:
                jr = await judge.judge_general(item["query"], item["gold_answer"], res["answer"])
                if jr:
                    gen["faithfulness"] = jr.get("faithfulness")
                    gen["relevance"] = jr.get("relevance")
                    gen["accuracy"] = jr.get("accuracy")

            ret_rows.append(ret)
            gen_rows.append(gen)
            perf_rows.append({
                "id": item["id"],
                "latency_retrieval": res["latency_retrieval"],
                "latency_total": res["latency_total"],
            })
            _log(f"[{idx}/{total}] {item['id']} intent={res['intent']} "
                 f"correct={ret['intent_correct']} recall@5={ret['recall@5']} "
                 f"kw={gen['kw_score']} resolved={gen['is_resolved']} "
                 f"({res['latency_total']}s)")

        # ── Itinerary benchmark ──
        for item in itinerary_items:
            idx += 1
            _state["current"] = idx
            res = await _run_one(item)
            if res is None:
                continue

            ret = evaluator.retrieval_metrics(
                item, res["docs"], res["intent"], res["latency_retrieval"]
            )
            gen = evaluator.generation_metrics(item, res["answer"])
            ret_rows.append(ret)
            gen_rows.append(gen)
            perf_rows.append({
                "id": item["id"],
                "latency_retrieval": res["latency_retrieval"],
                "latency_total": res["latency_total"],
            })

            struct = struct_eval.evaluate(res["answer"], item.get("eval_criteria", {}))
            row = {
                "id": item["id"],
                "category": item["category"],
                "intent_correct": ret["intent_correct"],
                "detected_intent": res["intent"],
                "kw_score": gen["kw_score"],
                "is_resolved": gen["is_resolved"],
                "has_daily_structure": struct["has_daily_structure"],
                "days_mentioned": struct["days_mentioned"],
                "has_hotel": struct["has_hotel"],
                "has_food": struct["has_food"],
                "has_attractions": struct["has_attractions"],
                "no_hallucination": struct["no_hallucination"],
                "itinerary_score": struct["itinerary_score"],
                "latency": res["latency_total"],
                "answer_preview": res["answer"][:400],
            }
            if judge_on:
                ij = await judge.judge_itinerary(item["query"], item["gold_answer"], res["answer"])
                if ij:
                    row.update({
                        "coherence": ij.get("coherence"),
                        "coverage": ij.get("coverage"),
                        "feasibility": ij.get("feasibility"),
                        "personalization": ij.get("personalization"),
                        "local_relevance": ij.get("local_relevance"),
                    })
            itin_rows.append(row)
            _log(f"[{idx}/{total}] {item['id']} itinerary_score={struct['itinerary_score']} "
                 f"days={struct['days_mentioned']} ({res['latency_total']}s)")

        if errored:
            _log(f"⚠️ {len(errored)} câu lỗi (loại khỏi report card): {', '.join(errored)}")

        # ── Judge means (chỉ từ general gen rows có chấm) ──
        judge_means = None
        if judge_on:
            jm = {}
            for key in ("faithfulness", "relevance", "accuracy"):
                vals = [r[key] for r in gen_rows if r.get(key) is not None]
                if vals:
                    jm[key] = sum(vals) / len(vals)
            judge_means = jm or None
            if judge_means is None:
                _log("⚠️ Judge BẬT nhưng không chấm được câu nào "
                     "(thiếu key, Gemini lỗi, hoặc trả về sai JSON).")

        report_card = evaluator.build_report_card(ret_rows, gen_rows, perf_rows, judge_means)
        n_pass = sum(1 for r in report_card if r["pass"] == "✅")

        result = {
            "id": run_id,
            "created_at": int(time.time()),
            "suite": suite,
            "enable_judge": judge_on,
            "report_card": report_card,
            "n_pass": n_pass,
            "n_total": len(report_card),
            "errored_ids": errored,
            "retrieval_rows": ret_rows,
            "generation_rows": gen_rows,
            "itinerary_rows": itin_rows,
            "perf_rows": perf_rows,
        }
        store.save_run(result)
        _latest = result
        _log(f"✅ Hoàn tất. Report card: {n_pass}/{len(report_card)} đạt. Run id: {run_id}")
        return result

    except Exception as exc:  # noqa: BLE001 — báo lỗi ra dashboard, không nuốt im lặng
        _log(f"❌ Lỗi khi eval: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None
    finally:
        _state.update(running=False, current=0, total=0)
