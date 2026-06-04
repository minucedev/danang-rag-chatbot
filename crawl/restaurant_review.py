"""
Foody.vn - Review Crawler (Optimized)
- Đọc CSV có cột URL + Total review
- Nhóm < 100       → lấy hết
- Nhóm 100–200     → lấy 80 review
- Nhóm > 200       → lấy 100 review mới nhất
- Async 4 workers song song
- Anti-bot: rotate UA/viewport, delay ngẫu nhiên, block media
- Checkpoint CSV mỗi 20 URL
- Error log → logs/error.log
"""

import asyncio
import csv
import logging
import os
import random
import re

import pandas as pd
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ══════════════════════════════════════════════════════════════════════════════
# CẤU HÌNH
# ══════════════════════════════════════════════════════════════════════════════
INPUT_CSV        = "restaurant_detail_cleaned.csv"        # cột: URL, Total review
OUTPUT_CSV       = "reviews_output.csv"
ERROR_LOG        = os.path.join("logs", "error.log")
MAX_WORKERS      = 4
CHECKPOINT_EVERY = 20
DELAY_MIN        = 0.8
DELAY_MAX        = 2.5
GOTO_TIMEOUT     = 60_000
CLICK_WAIT_MS    = 1_200    # chờ sau mỗi lần click "Xem thêm"

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
# ANTI-BOT: fingerprint pool
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


async def new_context(browser: Browser) -> BrowserContext:
    ctx = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
        extra_http_headers={
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    # Block ảnh / font / media → load nhanh hơn, ít traffic hơn
    await ctx.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_(),
    )
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# LOGIC XÁC ĐỊNH SỐ REVIEW CẦN LẤY
# ══════════════════════════════════════════════════════════════════════════════
def review_limit(total_review: int) -> int:
    if total_review < 100:
        return total_review      # lấy hết
    elif total_review <= 200:
        return 80
    else:
        return 100


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def clean_content(text: str) -> str:
    noise = {"Thích", "Thảo luận", "Báo lỗi"}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(
        ln for ln in lines
        if ln not in noise and not ln.startswith("- Đây là nhận xét")
    ).strip()


def extract_score(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d+[.,]\d+|\d+)", text)
    return m.group(1).replace(",", ".") if m else ""


def parse_btn_selector(url: str) -> str:
    """Tạo selector nút 'Xem thêm bình luận' từ URL (escape dấu /)."""
    path = "/" + url.split("foody.vn")[-1].strip("/")
    escaped = path.replace("/", "\\/")
    return (
        f"#{escaped} > div.micro-right1000 > section > div > div > div > div "
        "> div.micro-left > div > div.microsite-reviews-box.fd-clearbox.micro-review-list "
        "> div.lists.list-reviews > div > div > a"
    )


# ══════════════════════════════════════════════════════════════════════════════
# LOAD MORE — cuộn + click nút "Xem thêm bình luận"
# ══════════════════════════════════════════════════════════════════════════════
async def load_reviews(page: Page, url: str, limit: int, max_clicks: int = 60):
    """
    Cuộn xuống phần review, sau đó click 'Xem thêm bình luận' cho đến khi
    đủ limit hoặc hết nút.
    """
    btn_sel = parse_btn_selector(url)

    # Cuộn vào vùng review trước
    try:
        await page.locator(".microsite-reviews-box").scroll_into_view_if_needed()
        await page.wait_for_timeout(600)
    except Exception:
        pass

    for i in range(max_clicks):
        current = await page.locator("li.review-item").count()
        if current >= limit:
            logger.info(f"    ✔ Đủ {limit} review (hiện có {current})")
            return

        # Thử nút selector chính xác
        btn = page.locator(btn_sel)
        if await btn.count() == 0:
            # Fallback: tìm nút chứa text "Xem thêm"
            btn = page.locator(".list-reviews a:has-text('Xem thêm')")

        if await btn.count() == 0:
            logger.info(f"    ✔ Hết nút 'Xem thêm' (sau {i} lần click)")
            return

        try:
            await btn.first.scroll_into_view_if_needed()
            await btn.first.click()
            await page.wait_for_timeout(CLICK_WAIT_MS)
        except Exception as e:
            logger.warning(f"    ⚠ Click lỗi lần {i+1}: {e}")
            return


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT REVIEWS
# ══════════════════════════════════════════════════════════════════════════════
async def extract_reviews(page: Page, url: str, limit: int) -> list[dict]:
    await load_reviews(page, url, limit)

    lis = page.locator("li.review-item")
    total = min(await lis.count(), limit)
    logger.info(f"    → Trích xuất {total} review")

    reviews = []
    for i in range(total):
        li = lis.nth(i)

        async def safe(sel: str) -> str:
            try:
                el = li.locator(sel)
                return (await el.inner_text()).strip() if await el.count() > 0 else ""
            except Exception:
                return ""

        username  = await safe(".ru-username")
        time_text = await safe("div.ru-stats > span")
        score     = extract_score(await safe(".review-points"))

        content = ""
        for sel in ["div.review-des > div", "div.review-des", ".rd-des"]:
            txt = await safe(sel)
            if txt and len(txt) > 10:
                content = clean_content(txt)
                break

        reviews.append({
            "url"     : url,
            "username": username,
            "time"    : time_text,
            "score"   : score,
            "content" : content,
        })

    return reviews


# ══════════════════════════════════════════════════════════════════════════════
# WORKER — 1 context / URL, chạy song song qua semaphore
# ══════════════════════════════════════════════════════════════════════════════
async def worker(
    browser: Browser,
    sem: asyncio.Semaphore,
    idx: int,
    total_urls: int,
    url: str,
    total_review: int,
    results: list,
    lock: asyncio.Lock,
):
    limit = review_limit(total_review)

    async with sem:
        ctx  = await new_context(browser)
        page = await ctx.new_page()

        try:
            logger.info(
                f"[{idx}/{total_urls}] total_review={total_review} → lấy {limit} | {url}"
            )
            await page.goto(url, timeout=GOTO_TIMEOUT, wait_until="domcontentloaded")

            # Chờ element chính thay vì sleep cứng
            try:
                await page.wait_for_selector(".microsite-reviews-box", timeout=10_000)
            except Exception:
                pass

            reviews = await extract_reviews(page, url, limit)

            async with lock:
                results.extend(reviews)

                # Checkpoint mỗi CHECKPOINT_EVERY URL hoàn thành
                completed = sum(1 for r in results if r["url"] == url or True) // 1
                if idx % CHECKPOINT_EVERY == 0:
                    _save_csv(results, OUTPUT_CSV)
                    logger.info(f"💾 Checkpoint tại URL #{idx}: {len(results)} dòng đã lưu")

        except Exception as e:
            logger.error(f"❌ CRASH [{idx}/{total_urls}] {url} | {type(e).__name__}: {e}")

        finally:
            await ctx.close()
            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ══════════════════════════════════════════════════════════════════════════════
# CSV
# ══════════════════════════════════════════════════════════════════════════════
def _save_csv(results: list, path: str):
    if not results:
        return
    pd.DataFrame(results).to_csv(path, index=False, encoding="utf-8-sig")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    rows = []
    # NOTE: INPUT_CSV is often saved with utf-8-sig (BOM). Use utf-8-sig to avoid header like "\ufeffURL".
    with open(INPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for raw_row in csv.DictReader(f):
            # Normalize keys to avoid issues with trailing spaces in headers
            row = {((k or "").strip()): v for k, v in (raw_row or {}).items()}

            # Resolve column names robustly
            url_key = "URL" if "URL" in row else next((k for k in row.keys() if k.lower() == "url"), None)
            total_key = (
                "Total review" if "Total review" in row
                else next((k for k in row.keys() if k.lower().replace(" ", "") in {"totalreview", "total_reviews", "totalreviewcount"}), None)
            )

            url_val = (row.get(url_key) if url_key else "")
            url = str(url_val or "").strip()

            total_val = (row.get(total_key) if total_key else "")
            try:
                total_rv = int(re.sub(r"\D+", "", str(total_val)) or 0)
            except Exception:
                total_rv = 0

            if not url:
                continue

            rows.append({"url": url, "Total review": total_rv})

    total_urls = len(rows)
    logger.info(f"🚀 Bắt đầu crawl reviews | {total_urls} URL | workers={MAX_WORKERS}")

    results: list   = []
    lock            = asyncio.Lock()
    sem             = asyncio.Semaphore(MAX_WORKERS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        tasks = [
            worker(
                browser, sem,
                i + 1, total_urls,
                r["url"], r["Total review"],
                results, lock,
            )
            for i, r in enumerate(rows)
        ]
        await asyncio.gather(*tasks)

        await browser.close()

    _save_csv(results, OUTPUT_CSV)

    logger.info("══════════════════════════════════════")
    logger.info(f"✅ DONE — {len(results)} review từ {total_urls} URL")
    logger.info(f"📄 Output : {OUTPUT_CSV}")
    logger.info(f"📋 Errors : {ERROR_LOG}")
    logger.info("══════════════════════════════════════")


if __name__ == "__main__":
    asyncio.run(main())