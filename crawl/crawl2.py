"""
Foody.vn - Restaurant Detail Crawler (Optimized)
- Async + semaphore: crawl 4 URL song song
- Gom page.evaluate() 1 lần thay vì nhiều safe_text()
- Delay ngẫu nhiên chống bot detect
- Browser fingerprint (UA, locale, timezone, viewport)
- Checkpoint ghi CSV mỗi 10 URL
- Error log → logs/error.log
"""

import asyncio
import csv
import json
import logging
import os
import random
import re
import time
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright, Page, Browser

# ══════════════════════════════════════════════════════════════════════════════
# CẤU HÌNH
# ══════════════════════════════════════════════════════════════════════════════
INPUT_CSV       = "foody_urls.csv"
OUTPUT_CSV      = "restaurant_detail.csv"
ERROR_LOG       = os.path.join("logs", "error.log")
MAX_WORKERS     = 4          # Số page chạy song song
CHECKPOINT_EVERY = 10        # Ghi CSV tạm mỗi N URL
DELAY_MIN       = 0.8        # Giây delay tối thiểu giữa requests
DELAY_MAX       = 2.5        # Giây delay tối đa
GOTO_TIMEOUT    = 60_000     # ms

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ERROR_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def extract_number(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d+[\.,]?\d*)", text)
    return m.group(1).replace(",", ".") if m else ""


def parse_open_close(text: str):
    if not text:
        return "", ""
    m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
    return (m.group(1), m.group(2)) if m else ("", "")


def parse_price_range(text: str):
    if not text:
        return "", ""
    prices = re.findall(r"(\d[\d\.]*)đ", text)
    return (prices[0], prices[1]) if len(prices) >= 2 else ("", "")


def random_delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER CONTEXT — fingerprint chống bot detect
# ══════════════════════════════════════════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

def calc_avg_score(*scores):
    nums = []

    for score in scores:
        try:
            if score:
                nums.append(float(extract_number(score)))
        except ValueError:
            pass

    if not nums:
        return ""

    return round(sum(nums) / len(nums), 1)  # 1 chữ số sau dấu thập phân

async def new_context(browser: Browser):
    return await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
        extra_http_headers={
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT — gom toàn bộ vào 1 lần page.evaluate()
# ══════════════════════════════════════════════════════════════════════════════
EXTRACT_JS = """
() => {
    const q  = (sel) => { const el = document.querySelector(sel); return el ? el.innerText.trim() : ""; };
    const pg = (n)   => q(`#res-summary-point .microsite-point-group > div:nth-child(${n})`);
    return {
        name         : q(".micro-header .main-information .main-info-title > h1"),
        address      : q(".micro-header .main-information .disableSection div:nth-child(1) div"),
        price_text   : q(".res-common-price"),
        cuisines     : q(".category .category-cuisines"),
        type_food    : q(".category .category-items"),
        review_count : q(".microsite-top-points-block .microsite-review-count"),
        avg_score    : q(".microsite-top-points-block .rating_avg"),
        price_score  : pg(1) || q(".microsite-point-cost .point"),
        quality_score: pg(2) || q(".microsite-point-quality .point"),
        service_score: pg(3) || q(".microsite-point-service .point"),
        space_score  : pg(4) || q(".microsite-point-space .point"),
        location_score: pg(5) || q(".microsite-point-location .point"),
    };
}
"""


async def crawl_detail(page: Page, url: str, category: str) -> dict | None:
    # Goto với chờ đúng event, không dùng wait_for_timeout cố định
    await page.goto(url, timeout=GOTO_TIMEOUT, wait_until="domcontentloaded")

    # Chờ element chính xuất hiện thay vì sleep cứng
    try:
        await page.wait_for_selector(".micro-header", timeout=10_000)
    except Exception:
        pass

    # Scroll để trigger lazy-load rating
    try:
        await page.wait_for_selector("#res-summary-point", timeout=8_000)
        await page.locator("#res-summary-point").scroll_into_view_if_needed()
        await page.wait_for_timeout(400)   # chờ animation render (tối thiểu)
    except Exception:
        pass

    # ── 1 lần evaluate() thay cho 10+ safe_text() ────────────────────────────
    raw = await page.evaluate(EXTRACT_JS)

    price_text = raw.get("price_text", "")
    time_open, time_close = parse_open_close(price_text)
    price_min, price_max  = parse_price_range(price_text)

    price_score = extract_number(raw.get("price_score", ""))
    quality_score = extract_number(raw.get("quality_score", ""))
    service_score = extract_number(raw.get("service_score", ""))
    space_score = extract_number(raw.get("space_score", ""))
    location_score = extract_number(raw.get("location_score", ""))

    avg_score = calc_avg_score(
        price_score,
        quality_score,
        service_score,
        space_score,
        location_score,
    )

    return {
        "Name"          : raw.get("name", ""),
        "Address"       : raw.get("address", ""),
        "Avg Score"     : avg_score,
        "Price score"   : price_score,
        "Quality score" : quality_score,
        "Service score" : service_score,
        "Space score"   : space_score,
        "Location score": location_score,
        "Total review"  : extract_number(raw.get("review_count", "")),
        "Cuisine"       : raw.get("cuisines", "").replace("\n", " ").strip(),
        "Type"          : raw.get("type_food", "").replace("\n", " ").strip(),
        "Time open"     : time_open,
        "Time close"    : time_close,
        "Price min"     : price_min,
        "Price max"     : price_max,
        "Category"      : category,
        "URL"           : url,
    }


# ══════════════════════════════════════════════════════════════════════════════
# WORKER — mỗi worker giữ 1 page riêng, chạy song song qua semaphore
# ══════════════════════════════════════════════════════════════════════════════
async def worker(
    browser: Browser,
    sem: asyncio.Semaphore,
    idx: int,
    total: int,
    url: str,
    category: str,
    results: list,
    lock: asyncio.Lock,
):
    async with sem:
        context = await new_context(browser)
        page    = await context.new_page()

        # Block ảnh/font để tải nhanh hơn, ít bị nhận diện bot hơn
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "font", "media")
            else route.continue_(),
        )

        try:
            logger.info(f"[{idx}/{total}] → {url}")
            data = await crawl_detail(page, url, category)

            async with lock:
                results.append(data)

            # Checkpoint ghi CSV mỗi CHECKPOINT_EVERY URL
            async with lock:
                if len(results) % CHECKPOINT_EVERY == 0:
                    _save_csv(results, OUTPUT_CSV)
                    logger.info(f"💾 Checkpoint: đã lưu {len(results)} dòng")

        except Exception as e:
            logger.error(f"❌ CRASH [{idx}/{total}] {url} | {type(e).__name__}: {e}")

        finally:
            await context.close()
            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ══════════════════════════════════════════════════════════════════════════════
# CSV HELPER
# ══════════════════════════════════════════════════════════════════════════════
def _save_csv(results: list, path: str):
    if not results:
        return
    df = pd.DataFrame(results)
    df.to_csv(path, index=False, encoding="utf-8-sig")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    # Đọc input
    urls, categories = [], []
    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            urls.append(row["URL"])
            categories.append(row["Category"])

    total = len(urls)
    logger.info(f"🚀 Bắt đầu crawl {total} URL | workers={MAX_WORKERS}")

    results: list  = []
    lock           = asyncio.Lock()
    sem            = asyncio.Semaphore(MAX_WORKERS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        tasks = [
            worker(browser, sem, i + 1, total, url, cat, results, lock)
            for i, (url, cat) in enumerate(zip(urls, categories))
        ]
        await asyncio.gather(*tasks)

        await browser.close()

    # Lưu CSV cuối cùng
    _save_csv(results, OUTPUT_CSV)

    logger.info("══════════════════════════════════")
    logger.info(f"✅ DONE — {len(results)}/{total} URL thành công")
    logger.info(f"📄 Output : {OUTPUT_CSV}")
    logger.info(f"📋 Errors : {ERROR_LOG}")
    logger.info("══════════════════════════════════")


if __name__ == "__main__":
    asyncio.run(main())