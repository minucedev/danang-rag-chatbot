"""stable_room_id phải ổn định theo nội dung — crawl lại cùng phòng KHÔNG sinh point Qdrant trùng
(cùng lớp bug đã sửa cho review). Trước đây room_id dùng uuid4 → mỗi lần crawl ra id khác."""
from __future__ import annotations

from app.crawl_admin.engines.hotel_crawler import stable_room_id, stable_review_id


def test_room_id_deterministic():
    a = stable_room_id("hotel_x", "Deluxe King", "King", 28.0, "sea view")
    b = stable_room_id("hotel_x", "Deluxe King", "King", 28.0, "sea view")
    assert a == b
    assert a.startswith("room_")


def test_room_id_differs_by_content():
    base = stable_room_id("hotel_x", "Deluxe King", "King", 28.0, "sea view")
    assert base != stable_room_id("hotel_x", "Twin Room", "King", 28.0, "sea view")   # tên khác
    assert base != stable_room_id("hotel_y", "Deluxe King", "King", 28.0, "sea view")  # hotel khác
    assert base != stable_room_id("hotel_x", "Deluxe King", "King", 30.0, "sea view")  # diện tích khác


def test_room_and_review_ids_dont_collide():
    assert not stable_room_id("h", "r", "b", "a", "v").startswith("review_")
    assert not stable_review_id("h", "rev", "2026-01-01", "txt").startswith("room_")
