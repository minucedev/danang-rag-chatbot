"""Test các transform thuần của ingest (CSV → docs) — crown jewels: đúng dữ liệu vào Qdrant.
Không cần Playwright/network/Qdrant/embedder."""
from __future__ import annotations
import pandas as pd

from app.crawl_admin import ingest
from app.crawl_admin import foody_review_crawler


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


def test_review_limit_tiers():
    assert foody_review_crawler.review_limit(50) == 50    # <100 → lấy hết
    assert foody_review_crawler.review_limit(100) == 80   # 100–200 → 80
    assert foody_review_crawler.review_limit(200) == 80
    assert foody_review_crawler.review_limit(250) == 100  # >200 → 100


def test_extract_score():
    assert foody_review_crawler.extract_score("8,5/10") == "8.5"   # comma → dot
    assert foody_review_crawler.extract_score("Điểm: 9") == "9"    # integer
    assert foody_review_crawler.extract_score("7.0 trên 10") == "7.0"  # ưu tiên thập phân, lấy match đầu
    assert foody_review_crawler.extract_score("") == ""
    assert foody_review_crawler.extract_score("ngon lắm") == ""    # không số → rỗng


def test_clean_content():
    raw = "Quán ngon\nThích\nThảo luận\n- Đây là nhận xét của khách\nPhục vụ tốt"
    assert foody_review_crawler.clean_content(raw) == "Quán ngon\nPhục vụ tốt"
    assert foody_review_crawler.clean_content("   \n  ") == ""


def test_parse_btn_selector():
    sel = foody_review_crawler.parse_btn_selector("https://www.foody.vn/da-nang/quan-a/")
    assert sel.startswith("#\\/da-nang\\/quan-a >")  # bỏ slash cuối + escape /


def test_build_restaurant_reviews_join_and_drop():
    parent = ingest.stable_uuid(["restaurant_entity", "https://foody.vn/da-nang/quan-a"])
    url_to_entity = {"https://foody.vn/da-nang/quan-a": parent}
    df = pd.DataFrame([
        {"url": "https://foody.vn/da-nang/quan-a", "username": "An", "time": "01/02/2024",
         "score": "8.5", "content": "Đồ ăn ngon, phục vụ tốt"},          # giữ
        {"url": "https://foody.vn/da-nang/quan-la", "username": "B", "time": "",
         "score": "5", "content": "Quán lạ không có parent"},            # orphan → loại
        {"url": "https://foody.vn/da-nang/quan-a", "username": "C", "time": "",
         "score": "", "content": "ngắn"},                                # <8 ký tự → loại
    ])
    docs = ingest.build_restaurant_reviews(df, url_to_entity)
    assert len(docs) == 1
    assert docs[0]["text"] == "Đồ ăn ngon, phục vụ tốt"  # đúng dòng còn lại
    p = docs[0]["payload"]
    assert p["parent_entity_id"] == parent
    assert p["source_type"] == "restaurant_review"
    assert p["rating"] == 8.5
    assert p["source_place_id"] == "https://foody.vn/da-nang/quan-a"
    # dayfirst=True → 01/02/2024 là 1 tháng 2 (không phải 2 tháng 1)
    assert p["timestamp_norm"].startswith("2024-02-01")


def test_build_restaurant_reviews_dedupe_and_distinct():
    parent = ingest.stable_uuid(["restaurant_entity", "https://x/q"])
    u2e = {"https://x/q": parent}
    same = {"url": "https://x/q", "username": "An", "time": "", "score": "7", "content": "Đồ ăn rất ngon"}
    # 2 dòng trùng hệt → dedupe còn 1; 1 dòng khác nội dung → giữ riêng
    df = pd.DataFrame([same, dict(same), {**same, "content": "Phục vụ chu đáo nhiệt tình"}])
    docs = ingest.build_restaurant_reviews(df, u2e)
    assert len(docs) == 2
    assert len({d["id"] for d in docs}) == 2  # id phân biệt theo nội dung


def test_build_restaurant_reviews_missing_content_col():
    # CSV méo (không có cột content/review_text) → trả [] êm, không raise
    df = pd.DataFrame([{"url": "https://x/q", "score": "8"}])
    assert ingest.build_restaurant_reviews(df, {"https://x/q": "pid"}) == []


def test_acc_review_short_text_dropped():
    df_h = pd.DataFrame([{"hotel_id": "h1", "name": "K", "full_address": "Hải Châu, Đà Nẵng"}])
    _, h2e = ingest.build_hotels(df_h, {}, {}, {}, {})
    df_rev = pd.DataFrame([{"hotel_id": "h1", "review_id": "x", "review_text": "ngắn", "review_rating": 5, "review_date": ""}])
    assert ingest.build_acc_reviews(df_rev, h2e) == []  # len<10 → drop
