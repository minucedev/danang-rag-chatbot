"""Cấu hình cho module crawl-admin (chạy chung process với backend tại /admin/crawl)."""
from __future__ import annotations
import os
from pathlib import Path

# __file__ = backend/app/crawl_admin/config.py → parents[2] = backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "crawl_data"   # output CSV của các engine
DB_PATH = os.getenv("CRAWL_DB_PATH", str(BACKEND_DIR / "data" / "crawl.db"))

# ── Qdrant ingest: dùng chung Qdrant + model embed với app chính ──────────────
# Nạp creds Qdrant từ backend/.env (no-op nếu backend/main.py đã nạp trước).
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass
# Load bge-m3 offline từ cache local của backend (tránh gọi mạng HuggingFace)
os.environ.setdefault("HF_HUB_CACHE", str(BACKEND_DIR / "models" / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
INGEST_BATCH = int(os.getenv("CRAWL_INGEST_BATCH", "64"))
INGEST_RECREATE = os.getenv("CRAWL_INGEST_RECREATE", "false").lower() in ("1", "true", "yes")

COLLECTION_PLACES = "places_danang"
COLLECTION_RESTAURANTS = "restaurants_danang"
COLLECTION_ACCOMMODATION_HOTELS = "accommodation_hotels_danang"
COLLECTION_ACCOMMODATION_ROOMS = "accommodation_rooms_danang"
COLLECTION_ACCOMMODATION_REVIEWS = "accommodation_reviews_danang"
COLLECTION_RESTAURANT_REVIEWS = "restaurant_reviews_danang"

# Logic độ "cũ" theo crawl-update.txt
FRESHNESS_HOURS = int(os.getenv("CRAWL_FRESHNESS_HOURS", "48"))   # mới crawl < ngần này → bỏ qua
STALE_HOURS = int(os.getenv("CRAWL_STALE_HOURS", "720"))          # quá cũ (mặc định 30 ngày) → ép crawl lại

# Playwright
MAX_WORKERS = int(os.getenv("CRAWL_MAX_WORKERS", "4"))
DELAY_MIN = float(os.getenv("CRAWL_DELAY_MIN", "0.8"))
DELAY_MAX = float(os.getenv("CRAWL_DELAY_MAX", "2.5"))
GOTO_TIMEOUT = int(os.getenv("CRAWL_GOTO_TIMEOUT", "60000"))      # ms
HEADLESS = os.getenv("CRAWL_HEADLESS", "true").lower() in ("1", "true", "yes")
# Foody bật headless (nhẹ, API-based), traveloka tắt headless, booking bật headless
FOODY_HEADLESS = os.getenv("CRAWL_FOODY_HEADLESS", "true").lower() in ("1", "true", "yes")
TRAVELOKA_HEADLESS = os.getenv("CRAWL_TRAVELOKA_HEADLESS", "false").lower() in ("1", "true", "yes")
BOOKING_HEADLESS = os.getenv("CRAWL_BOOKING_HEADLESS", "true").lower() in ("1", "true", "yes")
REVIEW_CLICK_WAIT_MS = int(os.getenv("CRAWL_REVIEW_CLICK_WAIT_MS", "1200"))  # chờ sau mỗi click "Xem thêm bình luận"

# Auto-discovery (Foody listing API) — tự tìm quán Đà Nẵng, không cần nhập URL tay
DISCOVERY_ENABLED = os.getenv("CRAWL_DISCOVERY_ENABLED", "true").lower() in ("1", "true", "yes")
DISCOVERY_CITY = os.getenv("CRAWL_DISCOVERY_CITY", "da-nang")
DISCOVERY_MAX_NEW = int(os.getenv("CRAWL_DISCOVERY_MAX_NEW", "100"))   # cap số quán mỗi lần (chống bị chặn)
DISCOVERY_PAGE_COUNT = int(os.getenv("CRAWL_DISCOVERY_PAGE_COUNT", "24"))
DISCOVERY_MAX_PAGES = int(os.getenv("CRAWL_DISCOVERY_MAX_PAGES", "30"))  # trần an toàn
DISCOVERY_PAGE_DELAY = float(os.getenv("CRAWL_DISCOVERY_PAGE_DELAY", "0.6"))

# Scheduler — tự chạy crawl định kỳ. MẶC ĐỊNH TẮT: chạy chung process với chatbot trên
# máy ~4GB RAM → chỉ crawl thủ công qua nút bấm. Bật lại bằng CRAWL_SCHEDULE_ENABLED=true.
SCHEDULE_ENABLED = os.getenv("CRAWL_SCHEDULE_ENABLED", "false").lower() in ("1", "true", "yes")
SCHEDULE_HOURS = int(os.getenv("CRAWL_SCHEDULE_HOURS", "24"))
# Freshness theo engine: bỏ qua engine vừa chạy < ngần này giờ (scheduler/Chạy tất cả)
JOB_FRESHNESS_HOURS = int(os.getenv("CRAWL_JOB_FRESHNESS_HOURS", "20"))

# Giới hạn engine khách sạn (orchestrate as-is) — mặc định THẤP để tránh bị chặn
TRAVELOKA_MAX_PAGES = int(os.getenv("CRAWL_TRAVELOKA_MAX_PAGES", "3"))
TRAVELOKA_MAX_HOTELS = int(os.getenv("CRAWL_TRAVELOKA_MAX_HOTELS", "30"))
TRAVELOKA_REVIEWS = int(os.getenv("CRAWL_TRAVELOKA_REVIEWS", "10"))
BOOKING_MAX_PAGES = int(os.getenv("CRAWL_BOOKING_MAX_PAGES", "2"))
BOOKING_MAX_PROPERTIES = int(os.getenv("CRAWL_BOOKING_MAX_PROPERTIES", "30"))
BOOKING_MIN_REVIEWS = int(os.getenv("CRAWL_BOOKING_MIN_REVIEWS", "10"))
BOOKING_CITY = os.getenv("CRAWL_BOOKING_CITY", "Da Nang")

# Thư mục output CSV cho từng engine (gitignore'd)
DATA_FOODY = str(DATA_DIR / "foody")
DATA_TRAVELOKA = str(DATA_DIR / "traveloka")
DATA_BOOKING = str(DATA_DIR / "booking")

# Dashboard giờ nằm trên cổng public 8000. Bật cờ này để yêu cầu x-admin-token (= ADMIN_TOKEN
# của backend) cho các route GHI (kích hoạt crawl, thêm/xóa nguồn). Mặc định MỞ cho dev tiện.
REQUIRE_TOKEN = os.getenv("CRAWL_ADMIN_REQUIRE_TOKEN", "false").lower() in ("1", "true", "yes")
