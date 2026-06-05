"""Foody.vn review crawler — refactor từ crawl/restaurant_review.py thành hàm tái dùng.

`crawl_reviews(page, url, limit)` trả list review dict {url, username, time, score, content}.
Tái dùng `foody_crawler.new_context` (fingerprint + chặn ảnh/font) cho context.
"""
from __future__ import annotations
import re
from typing import TYPE_CHECKING, Optional

from app import config

if TYPE_CHECKING:  # chỉ dùng cho type hint — tránh buộc test thuần phải cài Playwright
    from playwright.async_api import Page


def review_limit(total_review: int) -> int:
    """Số review cần lấy theo bậc: <100 lấy hết, 100–200 lấy 80, >200 lấy 100
    (lấy theo thứ tự Foody trả về, KHÔNG sắp xếp theo ngày)."""
    if total_review < 100:
        return total_review
    if total_review <= 200:
        return 80
    return 100


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


async def load_reviews(page: Page, url: str, limit: int, max_clicks: int = 60) -> None:
    """Cuộn xuống vùng review rồi click 'Xem thêm bình luận' đến khi đủ limit hoặc hết nút."""
    btn_sel = parse_btn_selector(url)
    try:
        await page.locator(".microsite-reviews-box").scroll_into_view_if_needed()
        await page.wait_for_timeout(600)
    except Exception:
        pass

    for _ in range(max_clicks):
        if await page.locator("li.review-item").count() >= limit:
            return
        btn = page.locator(btn_sel)
        if await btn.count() == 0:
            btn = page.locator(".list-reviews a:has-text('Xem thêm')")
        if await btn.count() == 0:
            return
        try:
            await btn.first.scroll_into_view_if_needed()
            await btn.first.click()
            await page.wait_for_timeout(config.REVIEW_CLICK_WAIT_MS)
        except Exception:
            return


async def crawl_reviews(page: Page, url: str, limit: int, last_crawl_at: Optional[int] = None) -> list[dict]:
    """Goto trang quán → load + trích xuất tối đa `limit` review. Trả list dict."""
    from datetime import datetime
    
    last_crawl_dt = None
    if last_crawl_at:
        try:
            last_crawl_dt = datetime.fromtimestamp(last_crawl_at)
        except Exception:
            pass

    await page.goto(url, timeout=config.GOTO_TIMEOUT, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector(".microsite-reviews-box", timeout=10_000)
    except Exception:
        pass

    await load_reviews(page, url, limit)

    lis = page.locator("li.review-item")
    total = min(await lis.count(), limit)

    reviews: list[dict] = []
    for i in range(total):
        li = lis.nth(i)

        async def safe(sel: str) -> str:
            try:
                el = li.locator(sel)
                return (await el.inner_text()).strip() if await el.count() > 0 else ""
            except Exception:
                return ""

        username = await safe(".ru-username")
        time_text = await safe("div.ru-stats > span")

        if last_crawl_dt:
            from app.review_preprocessor import parse_time
            parsed_time = parse_time(time_text)
            if parsed_time and parsed_time < last_crawl_dt:
                continue

        score = extract_score(await safe(".review-points"))

        content = ""
        for sel in ["div.review-des > div", "div.review-des", ".rd-des"]:
            txt = await safe(sel)
            if txt and len(txt) > 10:
                content = clean_content(txt)
                break

        reviews.append({
            "url": url,
            "username": username,
            "time": time_text,
            "score": score,
            "content": content,
        })

    return reviews
