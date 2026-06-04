"""Test các transform thuần của ingest (CSV → docs) — crown jewels: đúng dữ liệu vào Qdrant.
Không cần Playwright/network/Qdrant/embedder."""
from __future__ import annotations
import pandas as pd

from app import ingest


# ─── Helpers ──────────────────────────────────────────────────────────────────
def test_resolve_col_flexible_headers():
    df = pd.DataFrame(columns=["Avg Score", "hotel_id"])
    assert ingest.resolve_col(df, ["avg_score"]) == "Avg Score"
    assert ingest.resolve_col(df, ["AVGSCORE"]) == "Avg Score"
    assert ingest.resolve_col(df, ["missing"]) is None


def test_resolve_col_required_raises():
    df = pd.DataFrame(columns=["a"])
    try:
        ingest.resolve_col(df, ["b"], required=True)
        assert False, "phải raise KeyError"
    except KeyError:
        pass


def test_parse_price_number():
    assert ingest.parse_price_number("1.200.000đ") == 1200000
    assert ingest.parse_price_number("1,200,000 VND") == 1200000
    assert ingest.parse_price_number(None) is None
    assert ingest.parse_price_number("") is None


def test_price_level_boundaries():
    assert ingest.price_level_place(None) == "unknown"
    assert ingest.price_level_place(49_999) == "budget"
    assert ingest.price_level_place(50_000) == "mid"
    assert ingest.price_level_place(200_000) == "high"
    assert ingest.price_level_hotel(399_999) == "budget"
    assert ingest.price_level_hotel(1_200_000) == "high"


def test_extract_district():
    assert ingest.extract_district("123 Trần Phú, Quận Hải Châu, Đà Nẵng") == "hai chau"
    assert ingest.extract_district("Khu vực không rõ") == ""
    assert ingest.extract_district("bất kỳ", fallback_district="Sơn Trà") == "son tra"


def test_stable_uuid_idempotent():
    a = ingest.stable_uuid(["restaurant_entity", "https://x/q"])
    b = ingest.stable_uuid(["restaurant_entity", "https://x/q"])
    assert a == b
    # whitespace/NFKC chuẩn hoá → cùng id
    assert ingest.stable_uuid(["  X  "]) == ingest.stable_uuid(["X"])
    assert a != ingest.stable_uuid(["restaurant_entity", "https://x/other"])


# ─── Restaurants ──────────────────────────────────────────────────────────────
def _resto_df(rows):
    cols = ["Name", "Address", "Avg Score", "Total review", "Cuisine", "Type",
            "Price min", "Price max", "URL"]
    return pd.DataFrame(rows, columns=cols)


def test_build_restaurant_blank_name_dropped_and_dedupe():
    df = _resto_df([
        ["Quán A", "1 Trần Phú, Hải Châu, Đà Nẵng", 7.5, 100, "Hải sản", "Nhà hàng", "100000", "300000", "https://x/a"],
        ["", "addr", 5, 1, "", "", "", "", "https://x/blank"],          # blank name → drop
        ["Quán A 2", "addr", 6, 2, "", "", "", "", "https://x/a"],       # same URL → dedupe
    ])
    docs = ingest.build_restaurant_entities(df)
    assert len(docs) == 1
    p = docs[0]["payload"]
    assert p["entity_name"] == "Quán A"
    assert p["district"] == "hai chau"
    assert p["min_price_vnd"] == 100000
    assert p["price_level"] == "mid"  # 100k place → mid (<200k)
    assert p["review_count"] == 100


def test_build_restaurant_id_url_vs_fallback():
    df_url = _resto_df([["Q", "addr dài hơn 20 ký tự nhé", 7, 1, "", "", "", "", "https://x/q"]])
    df_nourl = _resto_df([["Q", "addr dài hơn 20 ký tự nhé", 7, 1, "", "", "", "", ""]])
    id_url = ingest.build_restaurant_entities(df_url)[0]["id"]
    id_nourl = ingest.build_restaurant_entities(df_nourl)[0]["id"]
    assert id_url and id_nourl and id_url != id_nourl
    # idempotent
    assert id_url == ingest.build_restaurant_entities(df_url)[0]["id"]


# ─── Accommodation ────────────────────────────────────────────────────────────
def test_build_hotels_rooms_reviews_join():
    df_hotels = pd.DataFrame([
        {"hotel_id": "h1", "name": "KS Một", "rating": 9.0, "review_count": 50,
         "full_address": "10 Võ Nguyên Giáp, Sơn Trà, Đà Nẵng", "star_rating": 4, "link": "http://h1"},
    ])
    df_rooms = pd.DataFrame([
        {"hotel_id": "h1", "room_id": "r1", "room_name": "Deluxe", "capacity": 2,
         "bed_type": "double", "area": 25, "view": "sea", "amenities": "wifi"},
        {"hotel_id": "hX", "room_id": "rX", "room_name": "Orphan", "capacity": 2,
         "bed_type": "", "area": 0, "view": "", "amenities": ""},  # orphan hotel → drop
    ])
    df_prices = pd.DataFrame([
        {"hotel_id": "h1", "room_id": "r1", "price": "500000", "currency": "VND", "date": "2024-01-01", "is_discount": "true"},
        {"hotel_id": "h1", "room_id": "r1", "price": "800000", "currency": "VND", "date": "2024-02-01", "is_discount": "false"},
    ])
    df_reviews = pd.DataFrame([
        {"hotel_id": "h1", "review_id": "rv1", "reviewer_name": "An", "review_text": "Phòng sạch sẽ thoáng mát", "review_rating": 9, "review_date": "2024-01-05"},
        {"hotel_id": "hX", "review_id": "rvX", "reviewer_name": "B", "review_text": "Đánh giá mồ côi không parent", "review_rating": 5, "review_date": "2024-01-05"},
    ])

    img = ingest.build_image_summary(pd.DataFrame())
    pol = ingest.build_policy_summary(pd.DataFrame())
    hp, rp = ingest.build_price_summaries(df_prices)
    rs = ingest.build_room_stats(df_rooms)
    hotel_docs, h2e = ingest.build_hotels(df_hotels, img, pol, hp, rs)
    room_docs = ingest.build_rooms(df_rooms, h2e, rp)
    rev_docs = ingest.build_acc_reviews(df_reviews, h2e)

    assert len(hotel_docs) == 1
    hp_payload = hotel_docs[0]["payload"]
    assert hp_payload["district"] == "son tra"
    assert hp_payload["min_price_vnd"] == 500000 and hp_payload["max_price_vnd"] == 800000
    assert hp_payload["has_discount"] is True          # OR across rows
    assert hp_payload["price_snapshot_date"].startswith("2024-02-01")  # latest snapshot

    # orphan room/review bị loại; parent_entity_id liên kết đúng
    assert len(room_docs) == 1 and len(rev_docs) == 1
    parent = ingest.stable_uuid(["accommodation_hotel", "h1"])
    assert room_docs[0]["payload"]["parent_entity_id"] == parent
    assert rev_docs[0]["payload"]["parent_entity_id"] == parent
    assert h2e["h1"] == parent


def test_acc_review_short_text_dropped():
    df_h = pd.DataFrame([{"hotel_id": "h1", "name": "K", "full_address": "Hải Châu, Đà Nẵng"}])
    _, h2e = ingest.build_hotels(df_h, {}, {}, {}, {})
    df_rev = pd.DataFrame([{"hotel_id": "h1", "review_id": "x", "review_text": "ngắn", "review_rating": 5, "review_date": ""}])
    assert ingest.build_acc_reviews(df_rev, h2e) == []  # len<10 → drop
