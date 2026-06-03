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

# Server
PORT = int(os.getenv("CRAWL_PORT", "8100"))
