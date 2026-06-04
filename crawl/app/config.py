"""Cấu hình cho tool crawl-admin standalone (độc lập với backend chính)."""
from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # = crawl/
DATA_DIR = BASE_DIR / "data"
DB_PATH = os.getenv("CRAWL_DB_PATH", str(DATA_DIR / "crawl.db"))

# Logic độ "cũ" theo crawl-update.txt
FRESHNESS_HOURS = int(os.getenv("CRAWL_FRESHNESS_HOURS", "24"))   # mới crawl < ngần này → bỏ qua
STALE_HOURS = int(os.getenv("CRAWL_STALE_HOURS", "720"))          # quá cũ (mặc định 30 ngày) → ép crawl lại

# Playwright
MAX_WORKERS = int(os.getenv("CRAWL_MAX_WORKERS", "4"))
DELAY_MIN = float(os.getenv("CRAWL_DELAY_MIN", "0.8"))
DELAY_MAX = float(os.getenv("CRAWL_DELAY_MAX", "2.5"))
GOTO_TIMEOUT = int(os.getenv("CRAWL_GOTO_TIMEOUT", "60000"))      # ms
HEADLESS = os.getenv("CRAWL_HEADLESS", "true").lower() in ("1", "true", "yes")

# Auto-discovery (Foody listing API) — tự tìm quán Đà Nẵng, không cần nhập URL tay
DISCOVERY_ENABLED = os.getenv("CRAWL_DISCOVERY_ENABLED", "true").lower() in ("1", "true", "yes")
DISCOVERY_CITY = os.getenv("CRAWL_DISCOVERY_CITY", "da-nang")
DISCOVERY_MAX_NEW = int(os.getenv("CRAWL_DISCOVERY_MAX_NEW", "100"))   # cap số quán mỗi lần (chống bị chặn)
DISCOVERY_PAGE_COUNT = int(os.getenv("CRAWL_DISCOVERY_PAGE_COUNT", "24"))
DISCOVERY_MAX_PAGES = int(os.getenv("CRAWL_DISCOVERY_MAX_PAGES", "30"))  # trần an toàn
DISCOVERY_PAGE_DELAY = float(os.getenv("CRAWL_DISCOVERY_PAGE_DELAY", "0.6"))

# Scheduler — tự chạy crawl định kỳ
SCHEDULE_ENABLED = os.getenv("CRAWL_SCHEDULE_ENABLED", "true").lower() in ("1", "true", "yes")
SCHEDULE_HOURS = int(os.getenv("CRAWL_SCHEDULE_HOURS", "24"))
# Freshness theo engine: bỏ qua engine vừa chạy < ngần này giờ (scheduler/Chạy tất cả)
JOB_FRESHNESS_HOURS = int(os.getenv("CRAWL_JOB_FRESHNESS_HOURS", "20"))

# Giới hạn engine khách sạn (orchestrate as-is) — mặc định THẤP để tránh bị chặn
AGODA_MAX_PAGES = int(os.getenv("CRAWL_AGODA_MAX_PAGES", "3"))
AGODA_MAX_HOTELS = int(os.getenv("CRAWL_AGODA_MAX_HOTELS", "30"))
AGODA_REVIEWS = int(os.getenv("CRAWL_AGODA_REVIEWS", "10"))
BOOKING_MAX_PAGES = int(os.getenv("CRAWL_BOOKING_MAX_PAGES", "2"))
BOOKING_MAX_PROPERTIES = int(os.getenv("CRAWL_BOOKING_MAX_PROPERTIES", "30"))
BOOKING_MIN_REVIEWS = int(os.getenv("CRAWL_BOOKING_MIN_REVIEWS", "10"))
BOOKING_CITY = os.getenv("CRAWL_BOOKING_CITY", "Da Nang")

# Thư mục output CSV cho từng engine (gitignore'd)
DATA_FOODY = str(DATA_DIR / "foody")
DATA_AGODA = str(DATA_DIR / "agoda")
DATA_BOOKING = str(DATA_DIR / "booking")

# Server
PORT = int(os.getenv("CRAWL_PORT", "8100"))
