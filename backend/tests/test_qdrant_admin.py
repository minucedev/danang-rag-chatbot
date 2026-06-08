"""Tests cho helper thuần của qdrant-admin: phân trang, đọc snapshot, tổng quan.

Không gọi Qdrant — chỉ kiểm tra logic đọc file + cắt trang.
"""
from __future__ import annotations

import json

from app.api import qdrant_admin as qa


# ─── _paginate ───────────────────────────────────────────────────────────────
def test_paginate_basic():
    pts = list(range(10))
    assert qa._paginate(pts, 0, 3) == [0, 1, 2]
    assert qa._paginate(pts, 3, 3) == [3, 4, 5]


def test_paginate_overflow_returns_tail():
    pts = list(range(5))
    assert qa._paginate(pts, 3, 10) == [3, 4]
    assert qa._paginate(pts, 10, 5) == []  # offset vượt biên


def test_paginate_guards_negative_and_zero():
    pts = list(range(5))
    assert qa._paginate(pts, -2, 3) == [0, 1, 2]  # offset âm → 0
    assert qa._paginate(pts, 0, 0) == []          # limit 0 → rỗng
    assert qa._paginate(pts, 0, -1) == []         # limit âm → rỗng


# ─── _read_snapshot ──────────────────────────────────────────────────────────
def test_read_snapshot_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "_SNAPSHOT_PATH", tmp_path / "khong-ton-tai.json")
    assert qa._read_snapshot() is None


def test_read_snapshot_corrupt_returns_none(tmp_path, monkeypatch):
    p = tmp_path / "snap.json"
    p.write_text("{khong-phai-json", encoding="utf-8")
    monkeypatch.setattr(qa, "_SNAPSHOT_PATH", p)
    assert qa._read_snapshot() is None


def test_read_snapshot_valid(tmp_path, monkeypatch):
    p = tmp_path / "snap.json"
    data = {"updated_at": 123, "max_per_collection": 500, "collections": {}}
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(qa, "_SNAPSHOT_PATH", p)
    assert qa._read_snapshot() == data


# ─── _overview ───────────────────────────────────────────────────────────────
def test_overview_empty():
    ov = qa._overview(None)
    assert ov == {"updated_at": None, "max_per_collection": None, "collections": []}


def test_overview_derives_counts_and_stored_fallback():
    snap = {
        "updated_at": 999,
        "max_per_collection": 500,
        "collections": {
            "places_danang": {"total": 1200, "stored": 500, "points": [{"id": "1"}]},
            # 'stored' thiếu → suy ra từ len(points)
            "restaurants_danang": {"total": 3, "points": [{"id": "a"}, {"id": "b"}]},
        },
    }
    ov = qa._overview(snap)
    assert ov["updated_at"] == 999 and ov["max_per_collection"] == 500
    by = {c["name"]: c for c in ov["collections"]}
    assert by["places_danang"]["total"] == 1200 and by["places_danang"]["stored"] == 500
    assert by["restaurants_danang"]["stored"] == 2  # fallback len(points)


# ─── _count_by ───────────────────────────────────────────────────────────────
def _pts(*payloads):
    return [{"id": str(i), "payload": p} for i, p in enumerate(payloads)]


def test_count_by_basic_sorted_desc_skips_empty():
    pts = _pts({"district": "hai chau"}, {"district": "hai chau"}, {"district": "son tra"},
               {"district": ""}, {"other": "x"})
    out = qa._count_by(pts, "district")
    assert out == [{"key": "hai chau", "count": 2}, {"key": "son tra", "count": 1}]


def test_count_by_split_multi_value():
    pts = _pts({"cuisine": "Hải sản, Việt Nam"}, {"cuisine": "Việt Nam"}, {"cuisine": "Cà phê;Trà sữa"})
    out = qa._count_by(pts, "cuisine", split=True)
    by = {x["key"]: x["count"] for x in out}
    assert by["Việt Nam"] == 2 and by["Hải sản"] == 1 and by["Cà phê"] == 1 and by["Trà sữa"] == 1


def test_count_by_top_groups_rest_into_khac():
    pts = _pts(*[{"d": k} for k in ["a", "a", "a", "b", "b", "c", "d"]])
    out = qa._count_by(pts, "d", top=2)
    assert out[0] == {"key": "a", "count": 3}
    assert out[-1] == {"key": "Khác", "count": 2}  # c + d gộp


def test_count_by_handles_list_values():
    pts = _pts({"tags": ["biển", "gia đình"]}, {"tags": ["biển"]})
    by = {x["key"]: x["count"] for x in qa._count_by(pts, "tags")}
    assert by["biển"] == 2 and by["gia đình"] == 1


# ─── _rating_hist ────────────────────────────────────────────────────────────
def test_rating_hist_rounds_and_sorts_ascending():
    # round() dùng banker's rounding: round(8.5)=8 → bucket 8 gồm 8.4 & 8.5.
    pts = _pts({"rating": 8.4}, {"rating": 8.5}, {"rating": 9.1}, {"rating": "7.0"}, {"rating": None}, {"x": 1})
    out = qa._rating_hist(pts, "rating")
    assert out == [{"bucket": 7, "count": 1}, {"bucket": 8, "count": 2}, {"bucket": 9, "count": 1}]


def test_rating_hist_skips_non_numeric_and_bool():
    pts = _pts({"rating": "n/a"}, {"rating": True}, {"rating": 5})
    assert qa._rating_hist(pts, "rating") == [{"bucket": 5, "count": 1}]


# ─── _collection_stats ───────────────────────────────────────────────────────
def test_collection_stats_restaurants_special_type():
    col = {"total": 500, "stored": 3, "points": _pts(
        {"district": "hai chau", "rating": 8.2, "restaurant_type": "Nhà hàng, Buffet"},
        {"district": "hai chau", "rating": 7.8, "restaurant_type": "Nhà hàng"},
        {"district": "son tra", "rating": 9.0, "restaurant_type": "Café/Dessert"},
    )}
    s = qa._collection_stats(col, "restaurants_danang")
    assert s["total"] == 500 and s["stored"] == 3
    assert s["by_district"][0] == {"key": "hai chau", "count": 2}
    assert s["special"]["label"] == "Loại hình"
    typ = {x["key"]: x["count"] for x in s["special"]["items"]}
    assert typ["Nhà hàng"] == 2 and typ["Buffet"] == 1 and typ["Café/Dessert"] == 1


def test_collection_stats_hotels_special_star():
    col = {"total": 10, "stored": 2, "points": _pts(
        {"district": "hai chau", "star_rating": 5}, {"district": "hai chau", "star_rating": 4},
    )}
    s = qa._collection_stats(col, "accommodation_hotels_danang")
    assert s["special"]["label"] == "Hạng sao"
    labels = {x["key"] for x in s["special"]["items"]}
    assert "5 sao" in labels and "4 sao" in labels


def test_collection_stats_places_special_none():
    col = {"total": 5, "stored": 1, "points": _pts({"district": "son tra", "rating": 8})}
    s = qa._collection_stats(col, "places_danang")
    assert s["special"] is None
    assert s["rating_hist"] == [{"bucket": 8, "count": 1}]
