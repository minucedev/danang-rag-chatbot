"""Foody.vn detail crawler — refactor từ crawl/crawl1 (1).py thành hàm tái dùng.

`crawl_detail(page, url)` trả về dict thông tin nhà hàng (hoặc raise nếu lỗi).
Context/fingerprint tách riêng để pipeline mở nhiều page song song.
"""
from __future__ import annotations
import logging
import random
import re
from typing import Optional

from playwright.async_api import Browser, Page

from app.crawl_admin import config

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

# Gom toàn bộ field vào 1 lần page.evaluate() (selector lấy nguyên từ crawl1 (1).py đã chạy được)
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


def _extract_number(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d+[\.,]?\d*)", text)
    return m.group(1).replace(",", ".") if m else ""


def _parse_open_close(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
    return (m.group(1), m.group(2)) if m else ("", "")


def _parse_price_range(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    prices = re.findall(r"(\d[\d\.]*)đ", text)
    return (prices[0], prices[1]) if len(prices) >= 2 else ("", "")


def _calc_avg_score(*scores) -> str | float:
    nums = []
    for s in scores:
        try:
            if s:
                nums.append(float(_extract_number(s)))
        except ValueError:
            pass
    return round(sum(nums) / len(nums), 1) if nums else ""


async def new_context(browser: Browser):
    """Context mới với fingerprint ngẫu nhiên + chặn ảnh/font cho nhẹ."""
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
    await ctx.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_(),
    )
    return ctx


async def _goto_and_wait(page: Page, url: str) -> None:
    """Goto + chờ header/score — dùng chung cho crawl_detail và crawl_detail_with_reviews."""
    await page.goto(url, timeout=config.GOTO_TIMEOUT, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector(".micro-header", timeout=10_000)
    except Exception:
        pass
    try:
        await page.wait_for_selector("#res-summary-point", timeout=8_000)
        await page.locator("#res-summary-point").scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
    except Exception:
        pass


def _build_detail(raw: dict, url: str) -> dict:
    """Chuyển raw JS object thành dict chi tiết nhà hàng."""
    if not raw.get("name"):
        raise RuntimeError("Trích xuất rỗng (tên trống — DOM Foody đổi hoặc bị chặn?)")

    time_open, time_close = _parse_open_close(raw.get("price_text", ""))
    price_min, price_max = _parse_price_range(raw.get("price_text", ""))
    price_score = _extract_number(raw.get("price_score", ""))
    quality_score = _extract_number(raw.get("quality_score", ""))
    service_score = _extract_number(raw.get("service_score", ""))
    space_score = _extract_number(raw.get("space_score", ""))
    location_score = _extract_number(raw.get("location_score", ""))

    return {
        "Name": raw.get("name", ""),
        "Address": raw.get("address", ""),
        "Avg Score": _calc_avg_score(
            price_score, quality_score, service_score, space_score, location_score
        ),
        "Price score": price_score,
        "Quality score": quality_score,
        "Service score": service_score,
        "Space score": space_score,
        "Location score": location_score,
        "Total review": _extract_number(raw.get("review_count", "")),
        "Cuisine": raw.get("cuisines", "").replace("\n", " ").strip(),
        "Type": raw.get("type_food", "").replace("\n", " ").strip(),
        "Time open": time_open,
        "Time close": time_close,
        "Price min": price_min,
        "Price max": price_max,
        "URL": url,
    }


async def crawl_detail(page: Page, url: str) -> dict:
    """Crawl 1 trang chi tiết Foody → dict field. Raise nếu goto/evaluate lỗi."""
    await _goto_and_wait(page, url)
    raw = await page.evaluate(EXTRACT_JS)
    return _build_detail(raw, url)


async def crawl_detail_with_reviews(page: Page, url: str, review_limit: int, last_crawl_at: Optional[int] = None) -> tuple[dict, list[dict]]:
    """Crawl chi tiết + review trên CÙNG 1 lần goto (không cần truy cập trang 2 lần).

    Trả (detail_dict, reviews_list). reviews_list có thể rỗng nếu review_limit<=0
    hoặc không load được review.
    """
    from app.crawl_admin import foody_review_crawler
    from datetime import datetime

    last_crawl_dt = None
    if last_crawl_at:
        try:
            last_crawl_dt = datetime.fromtimestamp(last_crawl_at)
        except Exception:
            pass

    await _goto_and_wait(page, url)
    raw = await page.evaluate(EXTRACT_JS)
    detail = _build_detail(raw, url)

    # ── Crawl review trên cùng page (đã ở trang chi tiết) ──
    reviews: list[dict] = []
    if review_limit > 0:
        try:
            await foody_review_crawler.load_reviews(page, url, review_limit)

            lis = page.locator("li.review-item")
            total = min(await lis.count(), review_limit)

            for i in range(total):
                li = lis.nth(i)

                async def safe(sel: str, _li=li) -> str:
                    try:
                        el = _li.locator(sel)
                        return (await el.inner_text()).strip() if await el.count() > 0 else ""
                    except Exception:
                        return ""

                username = await safe(".ru-username")
                time_text = await safe("div.ru-stats > span")

                if last_crawl_dt:
                    from app.crawl_admin.review_preprocessor import parse_time
                    parsed_time = parse_time(time_text)
                    if parsed_time and parsed_time < last_crawl_dt:
                        continue
                score = foody_review_crawler.extract_score(await safe(".review-points"))

                content = ""
                for sel in ["div.review-des > div", "div.review-des", ".rd-des"]:
                    txt = await safe(sel)
                    if txt and len(txt) > 10:
                        content = foody_review_crawler.clean_content(txt)
                        break

                reviews.append({
                    "url": url,
                    "username": username,
                    "time": time_text,
                    "score": score,
                    "content": content,
                })
        except Exception as exc:
            # review lỗi không ảnh hưởng detail, nhưng phải log để phát hiện selector hỏng
            # (nếu không, mọi quán trả 0 review sẽ trông giống quán thật sự không có review).
            logging.warning("Foody review crawl lỗi cho %s: %s", url, type(exc).__name__)

    return detail, reviews
