"""Lưu/đọc kết quả các lượt eval — JSON (đầy đủ) + CSV (như notebook cell 23/29).

Thư mục: backend/metrics_data/runs/<run_id>/
  result.json, eval_retrieval.csv, eval_generation.csv, eval_itinerary.csv, eval_report_card.csv
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("app.metrics.store")

# store.py -> metrics -> app -> backend
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = _BACKEND_ROOT / "metrics_data" / "runs"

# run_id luôn là strftime("%Y%m%d-%H%M%S") → chỉ chữ số + dấu '-'. Siết regex để chặn
# path traversal: run_id tới từ URL (route public), không được phép chứa '/', '..', v.v.
_RUN_ID_RE = re.compile(r"^[0-9-]+$")

# Tên các CSV xuất ra ↔ khóa trong result.json
_CSV_MAP = {
    "eval_retrieval": "retrieval_rows",
    "eval_generation": "generation_rows",
    "eval_itinerary": "itinerary_rows",
    "eval_report_card": "report_card",
}


def _run_dir(run_id: str) -> Optional[Path]:
    """Thư mục của 1 run; None nếu run_id không hợp lệ (chống path traversal)."""
    if not _RUN_ID_RE.match(run_id or ""):
        return None
    return RUNS_DIR / run_id


def save_run(result: Dict[str, Any]) -> None:
    """Ghi result.json + các CSV cho 1 lượt chạy (ghi atomic qua file .tmp)."""
    import pandas as pd

    run_id = result["id"]
    d = _run_dir(run_id)
    if d is None:
        raise ValueError(f"run_id không hợp lệ: {run_id!r}")
    d.mkdir(parents=True, exist_ok=True)

    # Ghi tmp rồi replace: tránh để lại result.json cụt nếu process bị giết giữa chừng
    # (file cụt sẽ bị list_runs/get_run lặng lẽ bỏ qua → mất run).
    tmp = d / "result.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / "result.json")

    for csv_name, key in _CSV_MAP.items():
        rows = result.get(key) or []
        if rows:
            pd.DataFrame(rows).to_csv(d / f"{csv_name}.csv", index=False, encoding="utf-8-sig")


def list_runs() -> List[Dict[str, Any]]:
    """Tóm tắt các lượt chạy, mới nhất trước."""
    if not RUNS_DIR.exists():
        return []
    out = []
    for d in RUNS_DIR.iterdir():
        f = d / "result.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Bỏ qua run hỏng nhưng để lại dấu vết — tránh "mất run" lặng lẽ.
            logger.warning("[metrics.store] bỏ qua run hỏng %s: %s: %s", f, type(exc).__name__, exc)
            continue
        out.append({
            "id": data.get("id"),
            "created_at": data.get("created_at"),
            "suite": data.get("suite"),
            "enable_judge": data.get("enable_judge"),
            "n_pass": data.get("n_pass"),
            "n_total": data.get("n_total"),
        })
    out.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
    return out


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    d = _run_dir(run_id)
    if d is None:
        return None
    f = d / "result.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[metrics.store] run hỏng %s: %s: %s", f, type(exc).__name__, exc)
        return None


def get_csv_path(run_id: str, name: str) -> Optional[Path]:
    """Đường dẫn CSV nếu run_id + name hợp lệ và file tồn tại (chống path traversal)."""
    if name not in _CSV_MAP:
        return None
    d = _run_dir(run_id)
    if d is None:
        return None
    p = d / f"{name}.csv"
    return p if p.exists() else None
