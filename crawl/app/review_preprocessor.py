"""Tiền xử lý review nhà hàng — port từ raw_data/restaurant/tien-xu-ly-review.py.

Cung cấp hàm `preprocess_reviews(rows)` để dùng inline trong pipeline crawl,
và `preprocess_and_save(rows, output_dir)` để ghi CSV.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# ════════════════════════════════════════
# 1. TEXT CLEANING
# ════════════════════════════════════════

def normalize_text(text) -> str:
    if not text or (isinstance(text, float) and text != text):  # NaN check
        return ""
    text = str(text).lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(
        r"[^\w\sàáạảãăắằặẳẵâấầậẩẫđèéẹẻẽêếềệểễìíịỉĩòóọỏõôốồộổỗơớờợởỡùúụủũưứừựửữỳýỵỷỹ]",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_noise(text: str) -> str:
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    text = re.sub(r"\b(kkk|haha|hehe|hihi)\b", "", text)
    return text.strip()


SLANG_MAP = {
    "nv": "nhân viên",
    "ko ": "không ",
    "k ": "không ",
    "ok": "ổn",
    "ngon vl": "rất ngon",
    "vkl": "nhiều",
}


def normalize_slang(text: str) -> str:
    for k, v in SLANG_MAP.items():
        text = text.replace(k, v)
    return text


STOPWORDS = {
    "và", "là", "hoặc", "thì", "mà", "đó", "đây", "này", "tại",
    "với", "các", "những", "từ", "trong",
}


def remove_stopwords(text: str) -> str:
    return " ".join(w for w in text.split() if w not in STOPWORDS)


def preprocess_text(text) -> str:
    text = normalize_text(text)
    text = clean_noise(text)
    text = normalize_slang(text)
    return text


# ════════════════════════════════════════
# 2. TIME PROCESSING
# ════════════════════════════════════════

def parse_time(text) -> Optional[datetime]:
    if not text or (isinstance(text, float) and text != text):
        return None
    for fmt in ["%d/%m/%Y %H:%M", "%d/%m/%Y"]:
        try:
            return datetime.strptime(str(text).strip(), fmt)
        except (ValueError, TypeError):
            pass
    return None


# ════════════════════════════════════════
# 3. RECENCY SCORE
# ════════════════════════════════════════

def compute_recency_score(dt: Optional[datetime]) -> float:
    if dt is None:
        return 0.0
    days = (datetime.now() - dt).days
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.8
    if days <= 90:
        return 0.6
    if days <= 180:
        return 0.4
    return 0.2


# ════════════════════════════════════════
# 4. PIPELINE
# ════════════════════════════════════════

def preprocess_reviews(rows: list[dict]) -> list[dict]:
    """Nhận list review dict (url, username, time, score, content)
    → trả list dict đã thêm clean_content, parsed_time, recency_score.
    Bỏ review có clean_content <= 5 ký tự."""
    result: list[dict] = []
    for row in rows:
        clean = preprocess_text(row.get("content", ""))
        if len(clean) <= 5:
            continue
        parsed = parse_time(row.get("time", ""))
        result.append({
            **row,
            "clean_content": clean,
            "parsed_time": str(parsed) if parsed else "",
            "recency_score": compute_recency_score(parsed),
        })
    return result


def preprocess_and_save(rows: list[dict], output_dir: str) -> tuple[Path, Path]:
    """Ghi reviews_output.csv (raw) + reviews_cleaned.csv (preprocessed).
    Trả (path_raw, path_cleaned)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_path = out / "reviews_output.csv"
    cleaned_path = out / "reviews_cleaned.csv"

    # Raw
    raw_cols = ["url", "username", "time", "score", "content"]
    with open(raw_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=raw_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # Cleaned
    cleaned_rows = preprocess_reviews(rows)
    cleaned_cols = ["url", "username", "time", "score", "content",
                    "clean_content", "parsed_time", "recency_score"]
    with open(cleaned_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cleaned_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(cleaned_rows)

    return raw_path, cleaned_path


def append_reviews_to_files(rows: list[dict], output_dir: str) -> None:
    """Ghi append dần các review cào được ra file CSV raw và cleaned."""
    if not rows:
        return
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_path = out / "reviews_output.csv"
    cleaned_path = out / "reviews_cleaned.csv"

    # Raw
    raw_cols = ["url", "username", "time", "score", "content"]
    raw_exists = raw_path.exists() and raw_path.stat().st_size > 0
    raw_enc = "utf-8" if raw_exists else "utf-8-sig"
    with open(raw_path, "a", encoding=raw_enc, newline="") as f:
        w = csv.DictWriter(f, fieldnames=raw_cols, extrasaction="ignore")
        if not raw_exists:
            w.writeheader()
        w.writerows(rows)

    # Cleaned
    cleaned_rows = preprocess_reviews(rows)
    if cleaned_rows:
        cleaned_cols = ["url", "username", "time", "score", "content",
                        "clean_content", "parsed_time", "recency_score"]
        cleaned_exists = cleaned_path.exists() and cleaned_path.stat().st_size > 0
        cleaned_enc = "utf-8" if cleaned_exists else "utf-8-sig"
        with open(cleaned_path, "a", encoding=cleaned_enc, newline="") as f:
            w = csv.DictWriter(f, fieldnames=cleaned_cols, extrasaction="ignore")
            if not cleaned_exists:
                w.writeheader()
            w.writerows(cleaned_rows)
