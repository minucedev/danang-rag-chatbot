"""Test logic limit max_hotels của Traveloka (commit db1ada0).
Lõi: limit đếm theo số KS cào THÀNH CÔNG (crawled_urls); KS bị skip do freshness KHÔNG tính.
Không cần Playwright/network — chỉ gọi thẳng method, crawl_detail được monkeypatch."""
from __future__ import annotations

from app.engines.hotel_crawler import TravelokaCrawlerEngine


def _make_engine(tmp_path, max_hotels):
    eng = TravelokaCrawlerEngine(max_hotels=max_hotels, data_dir=tmp_path)
    eng.crawled_urls = set()
    eng.resume_crawl = False  # tránh ghi checkpoint ra đĩa trong test
    return eng


def test_max_hotels_reached_counts_crawled_urls(tmp_path):
    eng = _make_engine(tmp_path, max_hotels=3)
    assert eng._max_hotels_reached() is False          # 0/3
    eng.crawled_urls = {"x", "y"}
    assert eng._max_hotels_reached() is False           # 2/3
    eng.crawled_urls = {"x", "y", "z"}
    assert eng._max_hotels_reached() is True             # 3/3


def test_freshness_skip_not_counted_toward_limit(tmp_path):
    eng = _make_engine(tmp_path, max_hotels=2)
    eng.crawl_detail = lambda ctx, hotel: True           # luôn cào thành công
    eng.check_freshness_callback = lambda url: url != "fresh"  # "fresh" → bị skip

    hotels = [
        {"link": "a", "hotel_id": "1"},
        {"link": "fresh", "hotel_id": "2"},  # skip vì freshness → KHÔNG tính vào limit
        {"link": "b", "hotel_id": "3"},
        {"link": "c", "hotel_id": "4"},      # không bao giờ tới (đã đạt limit ở "b")
    ]
    eng._stream_detail_for_page(None, hotels, 1, set(), {"count": 0})

    # a(thành công→1), fresh(skip, vẫn 1), b(thành công→2 = đạt limit, break trước c)
    assert eng.crawled_urls == {"a", "b"}
