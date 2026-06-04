"""Foody.vn detail crawler — refactor từ crawl/crawl1 (1).py thành hàm tái dùng.

`crawl_detail(page, url)` trả về dict thông tin nhà hàng (hoặc raise nếu lỗi).
Context/fingerprint tách riêng để pipeline mở nhiều page song song.
"""
from __future__ import annotations
import random
import re

from playwright.async_api import Browser, Page

from app import config

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


async def crawl_detail(page: Page, url: str) -> dict:
    """Crawl 1 trang chi tiết Foody → dict field. Raise nếu goto/evaluate lỗi."""
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

    raw = await page.evaluate(EXTRACT_JS)
    # Trích xuất rỗng toàn bộ (DOM Foody đổi / bị chặn) → coi là LỖI thay vì lưu bản ghi trống.
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
