import csv
import hashlib
import html
import json
import logging
import os
import random
import re
import time
import uuid
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import Page, TimeoutError, sync_playwright

# ==========================================
# COMMON CONFIG & LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==========================================
# COMMON UTILITIES
# ==========================================
def random_sleep(min_s: float = 0.5, max_s: float = 1.5):
    time.sleep(random.uniform(min_s, max_s))

def normalize_text(text: Optional[str], default: str = "N/A") -> str:
    if text is None:
        return default
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned if cleaned else default

def stable_hotel_id(link: str) -> str:
    digest = hashlib.md5(link.encode("utf-8")).hexdigest()[:16]
    return f"hotel_{digest}"


# ==========================================
# AGODA CRAWLER ENGINE
# ==========================================
class AgodaCrawlerEngine:
    def __init__(self, headless: bool = True, max_pages: int = 200, max_hotels: int = 5000, 
                 reviews_per_hotel: int = 15, data_dir: Optional[Path] = None):
        self.headless = headless
        self.max_pages = max_pages
        self.max_hotels = max_hotels
        self.reviews_per_hotel = reviews_per_hotel
        
        self.data_dir = data_dir or (Path.cwd() / "data" / "agoda_da_nang")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.hotels_csv = self.data_dir / "hotels.csv"
        self.prices_csv = self.data_dir / "prices.csv"
        self.rooms_csv = self.data_dir / "rooms.csv"
        self.reviews_csv = self.data_dir / "reviews.csv"
        self.policies_csv = self.data_dir / "policies.csv"
        self.images_csv = self.data_dir / "images.csv"
        
        self.hotels_header = [
            "hotel_id", "name", "price_min", "rating", "review_count", "location_short",
            "property_type", "link", "full_address", "description", "star_rating"
        ]
        
        self.da_nang_keywords = ("da nang", "danang", "đà nẵng", "da-nang")
        self.request_retries = 5
        self.list_scroll_passes = 6
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        ]

    def stable_room_id(self, hotel_id: str, room_name: str) -> str:
        key = f"{hotel_id}|{normalize_text(room_name).lower()}"
        return f"room_{hashlib.md5(key.encode('utf-8')).hexdigest()[:16]}"

    def _is_valid_room_name(self, name: str) -> bool:
        if not name or name == "N/A" or len(name) < 3:
            return False
        lower = name.lower()
        blocked = {"room", "rooms", "select room", "book now", "đặt ngay", "price", "night"}
        return not any(b in lower for b in blocked) and re.search(r"[A-Za-zÀ-ỹ0-9]", name)

    def _contains_da_nang(self, text: str) -> bool:
        return any(kw in normalize_text(text).lower() for kw in self.da_nang_keywords)

    def _start_api_capture(self, page: Page):
        captured = []
        def _on_response(response):
            try:
                if response.status != 200 or len(captured) > 400:
                    return
                if "json" not in response.headers.get("content-type", "").lower():
                    return
                url = response.url.lower()
                if "agoda" not in url:
                    return
                data = response.json()
                if isinstance(data, (dict, list)):
                    captured.append({"url": response.url, "data": data})
            except:
                pass
        page.on("response", _on_response)
        return lambda: captured

    def _iter_dict_nodes(self, value: Any):
        if isinstance(value, dict):
            yield value
            for v in value.values():
                yield from self._iter_dict_nodes(v)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_dict_nodes(item)

    def _extract_price_from_api_node(self, node: Dict) -> Optional[int]:
        keys = ["finalprice", "price", "amount", "displayprice", "totalprice", "sellprice"]
        for k in keys:
            v = node.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
            if isinstance(v, dict):
                for sub in ["value", "amount", "price"]:
                    if sub in v and isinstance(v[sub], (int, float)) and v[sub] > 0:
                        return int(v[sub])
        return None

    def _extract_agoda_api_room_prices(self, payloads: List[Dict], hotel_id: str):
        rooms = []
        prices = []
        seen = set()

        for payload in payloads:
            for node in self._iter_dict_nodes(payload.get("data")):
                norm_node = {str(k).lower().replace("_", ""): v for k, v in node.items()}

                room_name = None
                for key in ["roomtypename", "masterroomtypename", "roomname", "displayroomname", "name"]:
                    if key in norm_node:
                        candidate = normalize_text(norm_node[key])
                        if self._is_valid_room_name(candidate):
                            room_name = candidate
                            break
                if not room_name:
                    continue

                room_id = self.stable_room_id(hotel_id, room_name)
                price = self._extract_price_from_api_node(norm_node)
                if price is None:
                    continue

                if room_id not in seen:
                    rooms.append({
                        "room_id": room_id,
                        "hotel_id": hotel_id,
                        "room_name": room_name,
                        "capacity": str(norm_node.get("maxadults") or norm_node.get("maxoccupancy") or "N/A"),
                        "bed_type": normalize_text(norm_node.get("bedtype")),
                        "area": normalize_text(norm_node.get("areasize") or norm_node.get("size")),
                        "view": normalize_text(norm_node.get("viewtype")),
                        "amenities_room": "N/A",
                    })
                    seen.add(room_id)

                prices.append({
                    "price_id": str(uuid.uuid4()),
                    "hotel_id": hotel_id,
                    "room_name": room_name,
                    "price": price,
                    "currency": norm_node.get("currencycode") or norm_node.get("currency") or "VND",
                    "date": "N/A",
                    "is_discount": False,
                    "room_id": room_id,
                    "matched_room_name": room_name,
                    "match_method": "api",
                })
        return rooms, prices

    def init_outputs(self):
        files = {
            self.hotels_csv: self.hotels_header,
            self.prices_csv: ["price_id","hotel_id","room_name","price","currency","date","is_discount","room_id","matched_room_name","match_method"],
            self.rooms_csv: ["room_id","hotel_id","room_name","capacity","bed_type","area","view","amenities_room"],
            self.reviews_csv: ["review_id","hotel_id","reviewer_name","review_text","review_rating","review_date","language","helpful_count"],
            self.policies_csv: ["policy_id","hotel_id","policy_type","policy_value"],
            self.images_csv: ["image_id","hotel_id","image_url"],
        }
        for path, header in files.items():
            if not path.exists():
                with open(path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(header)

        self._ensure_hotels_schema(self.hotels_csv, self.hotels_header)

    def append_csv(self, path: Path, row: list):
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def _ensure_hotels_schema(self, path: Path, expected_header: List[str]):
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(expected_header)
            return

        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_header = reader.fieldnames or []
            if old_header == expected_header:
                return
            rows = list(reader)

        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=expected_header)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in expected_header})

        os.replace(temp_path, path)

    def save_hotels(self, data: Dict):
        self.append_csv(self.hotels_csv, [data.get(k) for k in self.hotels_header])

    def save_prices(self, data: Dict):
        self.append_csv(self.prices_csv, [data.get(k) for k in ["price_id","hotel_id","room_name","price","currency","date","is_discount","room_id","matched_room_name","match_method"]])

    def save_rooms(self, data: Dict):
        self.append_csv(self.rooms_csv, [data.get(k) for k in ["room_id","hotel_id","room_name","capacity","bed_type","area","view","amenities_room"]])

    def save_reviews(self, data: Dict):
        self.append_csv(self.reviews_csv, [data.get(k) for k in ["review_id","hotel_id","reviewer_name","review_text","review_rating","review_date","language","helpful_count"]])

    def save_policies(self, data: Dict):
        self.append_csv(self.policies_csv, [data.get(k) for k in ["policy_id","hotel_id","policy_type","policy_value"]])

    def save_images(self, data: Dict):
        self.append_csv(self.images_csv, [data.get(k) for k in ["image_id","hotel_id","image_url"]])

    def crawl_list(self, page: Page):
        site_base = "https://www.agoda.com/city/da-nang-vn.html"
        hotels = []
        seen = set()
        for p in range(1, self.max_pages + 1):
            if len(hotels) >= self.max_hotels:
                break
            url = f"{site_base}{'&' if '?' in site_base else '?'}page={p}"
            logging.info(f"[Agoda] List page {p}: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            for _ in range(self.list_scroll_passes):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1000)

            links = page.locator('a[href*="/hotel/"], a[href*="/accommodation/"]')
            for i in range(links.count()):
                try:
                    a = links.nth(i)
                    href = a.get_attribute("href") or ""
                    if "/hotel/" not in href and "/accommodation/" not in href:
                        continue
                    full_link = "https://www.agoda.com" + href if href.startswith("/") else href
                    if full_link in seen:
                        continue
                    seen.add(full_link)

                    name = normalize_text(a.inner_text())
                    hotel_id = stable_hotel_id(full_link)

                    hotels.append({
                        "hotel_id": hotel_id,
                        "name": name,
                        "link": full_link,
                        "price_min": None,
                        "rating": None,
                        "review_count": None,
                        "location_short": "Da Nang",
                        "property_type": "Accommodation",
                    })
                    if len(hotels) >= self.max_hotels:
                        break
                except:
                    continue
            if len(hotels) >= self.max_hotels:
                break
        logging.info(f"[Agoda] Found {len(hotels)} hotels from list")
        return hotels

    def goto_with_retry(self, page: Page, url: str) -> bool:
        for _ in range(self.request_retries):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=70000)
                page.wait_for_timeout(4000)
                return True
            except:
                time.sleep(2)
        return False

    def _open_rooms_tab(self, page: Page):
        try:
            page.locator('button, a').filter(has_text=re.compile("Phòng nghỉ|Rooms|Room", re.I)).first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except:
            pass

    def _open_overview_tab(self, page: Page):
        patterns = [r"^Tổng quan$", r"^Overview$", r"Thông tin cơ sở lưu trú"]
        for pattern in patterns:
            try:
                tab = page.locator("button, a, [role='tab']").filter(has_text=re.compile(pattern, re.I)).first
                tab.scroll_into_view_if_needed(timeout=2500)
                tab.click(timeout=2500, force=True)
                page.wait_for_timeout(1200)
                return
            except:
                continue

    def _open_review_tab(self, page: Page):
        patterns = [r"^Đánh giá$", r"^Reviews$", r"Nhận xét"]
        for pattern in patterns:
            try:
                tab = page.locator("button, a, [role='tab']").filter(has_text=re.compile(pattern, re.I)).first
                tab.scroll_into_view_if_needed(timeout=2500)
                tab.click(timeout=2500, force=True)
                page.wait_for_timeout(1200)
                return
            except:
                continue

    def _iter_nodes(self, value: Any):
        if isinstance(value, dict):
            yield value
            for v in value.values():
                yield from self._iter_nodes(v)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_nodes(item)

    def _extract_json_ld_hotel_fields(self, page: Page) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        scripts = page.locator('script[type="application/ld+json"]')

        def _parse_star(v: Any) -> Optional[float]:
            if isinstance(v, (int, float)):
                num = float(v)
                return num if 0 < num <= 5 else None
            if isinstance(v, str):
                m = re.search(r"(\d(?:[\.,]\d)?)", v)
                if m:
                    num = float(m.group(1).replace(",", "."))
                    return num if 0 < num <= 5 else None
            if isinstance(v, dict):
                for key in ["ratingValue", "value"]:
                    if key in v:
                        parsed = _parse_star(v.get(key))
                        if parsed is not None:
                            return parsed
            return None

        for i in range(scripts.count()):
            try:
                raw = scripts.nth(i).inner_text()
                data = json.loads(raw)
            except:
                continue

            for node in self._iter_nodes(data):
                node_type = str(node.get("@type", "")).lower()
                if "hotel" not in node_type and "lodgingbusiness" not in node_type:
                    continue

                if not result.get("name") and node.get("name"):
                    result["name"] = normalize_text(str(node.get("name")))

                if not result.get("description") and node.get("description"):
                    result["description"] = normalize_text(str(node.get("description")))

                if not result.get("full_address"):
                    addr = node.get("address")
                    if isinstance(addr, dict):
                        parts = [
                            addr.get("streetAddress"),
                            addr.get("addressLocality"),
                            addr.get("addressRegion"),
                            addr.get("postalCode"),
                            addr.get("addressCountry"),
                        ]
                        joined = ", ".join([str(p).strip() for p in parts if p and str(p).strip()])
                        if joined:
                            result["full_address"] = normalize_text(joined)
                    elif isinstance(addr, str):
                        result["full_address"] = normalize_text(addr)

                if result.get("star_rating") is None:
                    for key in ["starRating", "stars", "rating"]:
                        if key in node:
                            parsed = _parse_star(node.get(key))
                            if parsed is not None:
                                result["star_rating"] = parsed
                                break

        return result

    def _extract_overview_highlights(self, page: Page) -> str:
        full_text = ""
        for sel in [
            '#property-main-content',
            '[id*="property-main-content"]',
            'main',
        ]:
            try:
                full_text = normalize_text(page.locator(sel).first.inner_text(), default="")
                if full_text:
                    break
            except:
                continue

        chunks: List[str] = []
        if full_text:
            lines = [normalize_text(line, default="") for line in full_text.splitlines()]
            highlight_lines: List[str] = []
            seen = set()
            capture = False
            for line in lines:
                if not line:
                    continue
                low = line.lower()
                if low in {"tooltip", "điểm nổi bật nhất", "điểm nổi bật", "highlights"}:
                    capture = True
                    continue
                if capture and (low.startswith("thông tin hữu ích") or low.startswith("xem những nơi gần đây") or low.startswith("các địa danh") or low.startswith("địa danh") or low.startswith("bản đồ")):
                    break
                if len(line) > 120:
                    continue
                if not capture:
                    if low.startswith("cách ") or "wi-fi" in low or "wifi" in low or "bàn tiếp tân" in low or "dọn phòng" in low or "nhân viên" in low:
                        capture = True
                    else:
                        continue
                if not (
                    low.startswith("cách ")
                    or "wi-fi" in low
                    or "wifi" in low
                    or "bàn tiếp tân" in low
                    or "dọn phòng" in low
                    or "nhân viên" in low
                    or "miễn phí" in low
                    or "đỗ xe" in low
                    or "parking" in low
                    or "lễ tân" in low
                    or "sân bay" in low
                ):
                    continue
                if line in seen:
                    continue
                seen.add(line)
                highlight_lines.append(line)
                if len(highlight_lines) >= 6:
                    break

            if highlight_lines:
                return " | ".join(highlight_lines)

        selectors = [
            'section:has-text("Điểm nổi bật")',
            'div:has-text("Điểm nổi bật")',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 4)):
                    raw = normalize_text(loc.nth(i).inner_text(), default="")
                    if raw:
                        chunks.append(raw)
            except:
                continue

        lines: List[str] = []
        seen = set()
        for chunk in chunks:
            for part in re.split(r"[•\|\n]+", chunk):
                line = normalize_text(part, default="")
                if not line:
                    continue
                low = line.lower()
                if "điểm nổi bật" in low or "highlight" in low:
                    continue
                if len(line) < 12:
                    continue
                if line in seen:
                    continue
                seen.add(line)
                lines.append(line)

        return " | ".join(lines[:6]) if lines else "N/A"

    def _extract_rating_and_review_count(self, page: Page, ld_data: Dict[str, Any]) -> tuple[Optional[float], Optional[int]]:
        rating = None
        review_count = None

        if ld_data.get("rating") is not None:
            try:
                rating = float(ld_data.get("rating"))
            except:
                rating = None

        try:
            text = normalize_text(page.locator("main").inner_text(), default="")
        except:
            text = ""

        if not text:
            try:
                text = normalize_text(page.text_content("body"), default="")
            except:
                text = ""

        if text:
            rating_patterns = [
                r"(?:Dựa trên\s*\d[\d\.,]*\s*bài đánh giá\s*)?(\d(?:[\.,]\d)?)\s*(?:Rất tốt|Tuyệt vời|Trên cả tuyệt vời|Tốt|Xuất sắc)",
                r"\b(\d(?:[\.,]\d)?)\s*(?:Rất tốt|Tuyệt vời|Trên cả tuyệt vời|Tốt|Xuất sắc)\b",
                r"\b(\d(?:[\.,]\d)?)\s*(?:/\s*10|/\s*5)\b",
                r"\b(\d(?:[\.,]\d)?)\s*Đánh giá\b",
            ]
            for pattern in rating_patterns:
                m = re.search(pattern, text, flags=re.IGNORECASE)
                if not m:
                    continue
                try:
                    parsed = float(m.group(1).replace(",", "."))
                    if parsed > 0:
                        rating = parsed
                        break
                except:
                    continue

            review_patterns = [
                r"Nhận xét trên Agoda\s*\((\d[\d\.,]*)\)",
                r"Đánh giá\s*\((\d[\d\.,]*)\)",
                r"Dựa trên\s*(\d[\d\.,]*)\s*bài đánh giá",
                r"(?:Dựa trên\s*)?(\d[\d\.,]*)\s*bài đánh giá",
                r"(\d[\d\.,]*)\s*bài đánh giá",
                r"(\d[\d\.,]*)\s*nhận xét",
            ]
            for pattern in review_patterns:
                m = re.search(pattern, text, flags=re.IGNORECASE)
                if not m:
                    continue
                digits = re.sub(r"[^\d]", "", m.group(1))
                if digits:
                    try:
                        review_count = int(digits)
                        break
                    except:
                        continue

        return rating, review_count

    def _extract_property_type(self, page: Page, ld_data: Dict[str, Any], item_name: str) -> str:
        candidates = []
        for source in [item_name, ld_data.get("name"), ld_data.get("description")]:
            if source:
                candidates.append(normalize_text(str(source), default=""))

        text = " ".join([c for c in candidates if c])
        lowered = text.lower()

        mapping = [
            ("serviced apartment", ["serviced apartment", "căn hộ dịch vụ"]),
            ("resort", ["resort"]),
            ("hostel", ["hostel", "nhà nghỉ"]),
            ("guest house", ["guest house", "nhà khách"]),
            ("villa", ["villa"]),
            ("motel", ["motel"]),
            ("homestay", ["homestay"]),
            ("hotel", ["hotel", "khách sạn", "khach san"]),
            ("apartment", ["apartment", "căn hộ"]),
        ]

        for label, keywords in mapping:
            if any(keyword in lowered for keyword in keywords):
                return label

        return "Accommodation"

    def _extract_address(self, page: Page, ld_data: Dict[str, Any]) -> str:
        addr = ld_data.get("full_address")
        if addr and addr != "N/A":
            return addr

        selectors = [
            '[data-testid="address"]',
            '[class*="Address"]',
            '[class*="location"]',
            'span[class*="address"]',
            '.Address__Text',
            'span.HeaderBox__Address',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = normalize_text(loc.first.inner_text())
                    if text and text != "N/A":
                        return text
            except:
                continue
        return "Da Nang"

    def _extract_star_rating(self, page: Page, ld_data: Dict[str, Any]) -> Optional[float]:
        star = ld_data.get("star_rating")
        if star is not None:
            return star

        try:
            star_locator = page.locator('span[class*="star"], i[class*="star"], svg[class*="star"]')
            for i in range(star_locator.count()):
                aria = star_locator.nth(i).get_attribute("aria-label")
                if aria:
                    m = re.search(r"(\d+(?:\.\d+)?)", aria)
                    if m:
                        return float(m.group(1))
        except:
            pass
        return None

    def _extract_description(self, page: Page, ld_data: Dict[str, Any]) -> str:
        desc = ld_data.get("description")
        if desc and desc != "N/A":
            return desc

        selectors = [
            '#property-main-content-description',
            '[class*="description"]',
            '[data-testid="property-description"]',
            'p.description',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = normalize_text(loc.first.inner_text())
                    if text and text != "N/A":
                        return text
            except:
                continue
        return "N/A"

    def _extract_primary_hotel_info(self, page: Page, item: Dict) -> Dict:
        self._open_overview_tab(page)
        ld_data = self._extract_json_ld_hotel_fields(page)

        name = normalize_text(
            page.locator("h1").first.inner_text() if page.locator("h1").count() > 0 else ld_data.get("name") or item["name"]
        )

        rating, review_count = self._extract_rating_and_review_count(page, ld_data)
        self._open_overview_tab(page)
        address = self._extract_address(page, ld_data)
        star = self._extract_star_rating(page, ld_data)
        description = self._extract_description(page, ld_data)
        property_type = self._extract_property_type(page, ld_data, name)

        return {
            "hotel_id": item["hotel_id"],
            "name": name,
            "price_min": item.get("price_min"),
            "rating": rating if rating is not None else item.get("rating"),
            "review_count": review_count if review_count is not None else item.get("review_count"),
            "location_short": "Da Nang",
            "property_type": property_type,
            "link": item["link"],
            "full_address": address,
            "description": description,
            "star_rating": star,
        }

    def crawl_rooms(self, page: Page, hotel_id: str):
        self._open_rooms_tab(page)
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(2000)

        records = []
        seen = set()
        selectors = ['[class*="RoomName"]', '[data-testid*="room-name"]', 'h3, h4', '[class*="room-type"]']

        for sel in selectors:
            blocks = page.locator(sel)
            for i in range(min(blocks.count(), 100)):
                try:
                    text = normalize_text(blocks.nth(i).inner_text())
                    if not self._is_valid_room_name(text):
                        continue
                    room_id = self.stable_room_id(hotel_id, text)
                    if room_id in seen:
                        continue
                    seen.add(room_id)
                    record = {
                        "room_id": room_id,
                        "hotel_id": hotel_id,
                        "room_name": text,
                        "capacity": "N/A",
                        "bed_type": "N/A",
                        "area": "N/A",
                        "view": "N/A",
                        "amenities_room": "N/A",
                    }
                    records.append(record)
                    self.save_rooms(record)
                except:
                    continue
        return records

    def crawl_prices(self, page: Page, hotel_id: str):
        records = []
        for sel in ['[class*="Price"]', '[data-testid*="price"]', 'span[class*="currency"]']:
            blocks = page.locator(sel)
            for i in range(min(blocks.count(), 150)):
                try:
                    text = normalize_text(blocks.nth(i).inner_text())
                    match = re.search(r"(\d{1,3}(?:[.,]\d{3})*)", text)
                    if match:
                        price = int(match.group(1).replace(",", "").replace(".", ""))
                        record = {
                            "price_id": str(uuid.uuid4()),
                            "hotel_id": hotel_id,
                            "room_name": "Default Room",
                            "price": price,
                            "currency": "VND",
                            "date": "N/A",
                            "is_discount": False,
                            "room_id": "",
                            "matched_room_name": "Default Room",
                            "match_method": "dom",
                        }
                        records.append(record)
                        self.save_prices(record)
                except:
                    continue
        return records

    def run(self):
        logging.info("[Agoda] Starting Agoda crawler...")
        self.init_outputs()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent=random.choice(self.user_agents),
                viewport={"width": 1440, "height": 900},
                locale="vi-VN"
            )

            page = context.new_page()
            hotels = self.crawl_list(page)

            saved_count = 0
            for hotel in hotels[:self.max_hotels]:
                detail_page = context.new_page()
                try:
                    logging.info(f"[Agoda] Crawling detail: {hotel['name']}")
                    if self.goto_with_retry(detail_page, hotel["link"]):
                        hotel_info = self._extract_primary_hotel_info(detail_page, hotel)
                        self.save_hotels(hotel_info)

                        api_stop = self._start_api_capture(detail_page)
                        self.crawl_rooms(detail_page, hotel["hotel_id"])
                        self.crawl_prices(detail_page, hotel["hotel_id"])
                        api_data = api_stop()
                        api_rooms, api_prices = self._extract_agoda_api_room_prices(api_data, hotel["hotel_id"])

                        for r in api_rooms: 
                            self.save_rooms(r)
                        for pr in api_prices: 
                            self.save_prices(pr)

                        logging.info(f"✅ [Agoda] Done: {hotel['hotel_id']}")
                        saved_count += 1
                except Exception as e:
                    logging.error(f"[Agoda] Error on detail: {e}")
                finally:
                    detail_page.close()

            browser.close()
        logging.info(f"[Agoda] Crawler finished. Total saved: {saved_count}")


# ==========================================
# BOOKING CRAWLER ENGINE
# ==========================================
class BookingCrawlerEngine:
    def __init__(self, headless: bool = True, max_pages: int = 2, max_properties: int = 50, 
                 min_reviews: int = 10, search_city: str = "Da Nang", search_queries: Optional[List[str]] = None,
                 data_dir: Optional[Path] = None):
        self.headless = headless
        self.max_pages = max_pages
        self.max_properties = max_properties
        self.min_reviews = min_reviews
        self.search_city = search_city
        self.search_queries = search_queries
        
        self.data_dir = data_dir or (Path.cwd() / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.hotels_csv = self.data_dir / "hotels.csv"
        self.rooms_csv = self.data_dir / "rooms.csv"
        self.prices_csv = self.data_dir / "prices.csv"
        self.policies_csv = self.data_dir / "policies.csv"
        self.reviews_csv = self.data_dir / "reviews.csv"
        self.images_csv = self.data_dir / "images.csv"
        
        self.hotels_jsonl = self.data_dir / "hotels.jsonl"
        self.rooms_jsonl = self.data_dir / "rooms.jsonl"
        self.prices_jsonl = self.data_dir / "prices.jsonl"
        self.policies_jsonl = self.data_dir / "policies.jsonl"
        self.reviews_jsonl = self.data_dir / "reviews.jsonl"
        self.images_jsonl = self.data_dir / "images.jsonl"
        
        self.currency_pattern = r"(VND|USD|EUR|GBP|JPY|AUD|CAD|SGD|THB|IDR|MYR|PHP|KRW|TWD|HKD|\$|€|£|₫)"
        self.request_retries = 3
        
        self.non_hotel_types = {
            "resort": "Resort",
            "apartment": "Apartment",
            "apartments": "Apartment",
            "villa": "Villa",
            "homestay": "Homestay",
            "hostel": "Hostel",
            "guest house": "Guesthouse",
            "guesthouse": "Guesthouse",
            "bed and breakfast": "B&B",
            "b&b": "B&B",
            "inn": "Inn",
            "motel": "Motel",
            "capsule": "Capsule Hotel",
            "camp": "Campsite",
            "camping": "Campsite",
            "glamping": "Glamping",
            "lodging": "Lodging",
            "nha tro": "Hostel",
            "nha khach": "Guesthouse",
            "nha nghi": "Guesthouse",
            "cho nghi nha dan": "Homestay",
            "biet thu": "Villa",
            "can ho": "Apartment",
        }
        
        self.default_search_queries = [
            f"{self.search_city} apartment",
            f"{self.search_city} villa",
            f"{self.search_city} resort",
            f"{self.search_city} homestay",
            f"{self.search_city} guest house",
            f"{self.search_city} hostel",
            f"{self.search_city} bed and breakfast",
            f"{self.search_city} capsule hotel",
            f"{self.search_city} love hotel",
            f"{self.search_city} holiday home",
            f"{self.search_city} campground",
        ]
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ]

    def _normalize_ascii(self, text: str) -> str:
        lowered = text.lower()
        replacements = {
            "đ": "d", "á": "a", "à": "a", "ả": "a", "ã": "a", "ạ": "a", "ă": "a", "ắ": "a", "ằ": "a", "ẳ": "a", "ẵ": "a", "ặ": "a",
            "â": "a", "ấ": "a", "ầ": "a", "ẩ": "a", "ẫ": "a", "ậ": "a", "é": "e", "è": "e", "ẻ": "e", "ẽ": "e", "ẹ": "e", "ê": "e",
            "ế": "e", "ề": "e", "ể": "e", "ễ": "e", "ệ": "e", "í": "i", "ì": "i", "ỉ": "i", "ĩ": "i", "ị": "i", "ó": "o", "ò": "o",
            "ỏ": "o", "õ": "o", "ọ": "o", "ô": "o", "ố": "o", "ồ": "o", "ổ": "o", "ỗ": "o", "ộ": "o", "ơ": "o", "ớ": "o", "ờ": "o",
            "ở": "o", "ỡ": "o", "ợ": "o", "ú": "u", "ù": "u", "ủ": "u", "ũ": "u", "ụ": "u", "ư": "u", "ứ": "u", "ừ": "u", "ử": "u",
            "ữ": "u", "ự": "u", "ý": "y", "ỳ": "y", "ỷ": "y", "ỹ": "y", "ỵ": "y",
        }
        for src, dst in replacements.items():
            lowered = lowered.replace(src, dst)
        return lowered

    def clean_float(self, text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        match = re.search(r"\d+[\.,]?\d*", text)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None

    def clean_int(self, text: Optional[str]) -> Optional[int]:
        value = self.clean_float(text)
        if value is None:
            return None
        return int(value)

    def parse_price_and_currency(self, text: Optional[str]) -> tuple[Optional[int], str]:
        if not text:
            return None, "N/A"
        raw = normalize_text(text)
        currency_match = re.search(self.currency_pattern, raw, flags=re.IGNORECASE)
        currency = currency_match.group(1).upper() if currency_match else "N/A"

        patterns = [
            rf"{self.currency_pattern}\s*([\d.,]{{3,}})",
            rf"([\d.,]{{3,}})\s*{self.currency_pattern}",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, raw, flags=re.IGNORECASE)
            if not matches:
                continue
            for candidate in matches:
                number_text = candidate[1] if isinstance(candidate, tuple) else candidate
                cleaned = str(number_text).replace(",", "").replace(".", "")
                if len(cleaned) < 4:
                    continue
                try:
                    return int(cleaned), currency
                except ValueError:
                    continue

        for candidate in re.findall(r"\d+[\d.,]{2,}", raw):
            cleaned = candidate.replace(",", "").replace(".", "")
            if len(cleaned) < 4:
                continue
            try:
                return int(cleaned), currency
            except ValueError:
                continue
        return None, currency

    def get_search_queries(self) -> List[str]:
        if self.search_queries:
            return self.search_queries
        return list(self.default_search_queries)

    def detect_property_type(self, *texts: str) -> str:
        blob = self._normalize_ascii(" ".join([normalize_text(x, default="") for x in texts]))
        for token, label in self.non_hotel_types.items():
            if token in blob:
                return label
        if "love hotel" in blob:
            return "Love Hotel"
        if "capsule" in blob:
            return "Capsule Hotel"
        if "hotel" in blob:
            return "Hotel"
        return "Lodging"

    def is_non_hotel_type(self, property_type: str) -> bool:
        return normalize_text(property_type, default="").lower() != "hotel"

    def is_target_location(self, hotel_row: Dict[str, Any], target_city: str = "Da Nang") -> bool:
        address = self._normalize_ascii(normalize_text(hotel_row.get("full_address"), default=""))
        city = self._normalize_ascii(normalize_text(target_city, default=""))
        if city and city in address:
            return True
        link = self._normalize_ascii(normalize_text(hotel_row.get("link"), default=""))
        return "da-nang" in link or "danang" in link

    def goto_with_retry(self, page: Page, url: str, retries: int = 3) -> bool:
        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=70000)
                page.wait_for_timeout(2500)
                return True
            except Exception as exc:
                logging.warning(f"[Booking] goto failed ({attempt}/{retries}): {exc}")
                random_sleep(1.0, 2.0)
        return False

    def _append_jsonl(self, path: Path, data: Dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _append_csv(self, path: Path, row: List[Any]) -> None:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def _csv_cell(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, str):
            cleaned = normalize_text(value, default="")
            return "" if cleaned == "N/A" else cleaned
        return value

    def init_outputs(self) -> None:
        for path in [self.hotels_jsonl, self.rooms_jsonl, self.prices_jsonl, self.policies_jsonl, self.reviews_jsonl, self.images_jsonl]:
            path.write_text("", encoding="utf-8")

        specs = {
            self.hotels_csv: [
                "hotel_id", "name", "rating", "review_count", "location_short", "property_type",
                "link", "full_address", "latitude", "longitude", "description", "star_rating",
            ],
            self.rooms_csv: [
                "room_id", "hotel_id", "room_name", "capacity", "bed_type", "area", "view", "amenities_room",
            ],
            self.prices_csv: [
                "price_id", "hotel_id", "room_name", "price", "currency", "date", "occupancy",
                "is_discount", "room_id", "matched_room_name", "match_method", "match_score",
            ],
            self.policies_csv: ["policy_id", "hotel_id", "policy_type", "policy_value"],
            self.reviews_csv: [
                "review_id", "hotel_id", "reviewer_name", "review_text", "review_rating",
                "review_date", "language", "helpful_count",
            ],
            self.images_csv: ["image_id", "hotel_id", "image_url"],
        }

        for csv_file, header in specs.items():
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(header)

    def save_hotel(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.hotels_jsonl, data)
        self._append_csv(
            self.hotels_csv,
            [
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("name")),
                self._csv_cell(data.get("rating")),
                self._csv_cell(data.get("review_count")),
                self._csv_cell(data.get("location_short")),
                self._csv_cell(data.get("property_type")),
                self._csv_cell(data.get("link")),
                self._csv_cell(data.get("full_address")),
                self._csv_cell(data.get("latitude")),
                self._csv_cell(data.get("longitude")),
                self._csv_cell(data.get("description")),
                self._csv_cell(data.get("star_rating")),
            ],
        )

    def save_room(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.rooms_jsonl, data)
        self._append_csv(
            self.rooms_csv,
            [
                self._csv_cell(data.get("room_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("room_name")),
                self._csv_cell(data.get("capacity")),
                self._csv_cell(data.get("bed_type")),
                self._csv_cell(data.get("area")),
                self._csv_cell(data.get("view")),
                self._csv_cell(data.get("amenities_room")),
            ],
        )

    def save_price(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.prices_jsonl, data)
        self._append_csv(
            self.prices_csv,
            [
                self._csv_cell(data.get("price_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("room_name")),
                self._csv_cell(data.get("price")),
                self._csv_cell(data.get("currency")),
                self._csv_cell(data.get("date")),
                self._csv_cell(data.get("occupancy")),
                data.get("is_discount", False),
                self._csv_cell(data.get("room_id")),
                self._csv_cell(data.get("matched_room_name")),
                self._csv_cell(data.get("match_method")),
                self._csv_cell(data.get("match_score")),
            ],
        )

    def save_policy(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.policies_jsonl, data)
        self._append_csv(
            self.policies_csv,
            [
                self._csv_cell(data.get("policy_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("policy_type")),
                self._csv_cell(data.get("policy_value")),
            ],
        )

    def save_review(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.reviews_jsonl, data)
        self._append_csv(
            self.reviews_csv,
            [
                self._csv_cell(data.get("review_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("reviewer_name")),
                self._csv_cell(data.get("review_text")),
                self._csv_cell(data.get("review_rating")),
                self._csv_cell(data.get("review_date")),
                self._csv_cell(data.get("language")),
                self._csv_cell(data.get("helpful_count")),
            ],
        )

    def save_image(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.images_jsonl, data)
        self._append_csv(
            self.images_csv,
            [
                self._csv_cell(data.get("image_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("image_url")),
            ],
        )

    def _extract_jsonld(self, page: Page) -> List[Dict[str, Any]]:
        payloads = []
        try:
            scripts = page.locator('script[type="application/ld+json"]').all_inner_texts()
            for raw in scripts:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        payloads.extend([x for x in parsed if isinstance(x, dict)])
                    elif isinstance(parsed, dict):
                        payloads.append(parsed)
                except Exception:
                    continue
        except Exception:
            pass
        return payloads

    def _extract_apollo_state(self, page: Page) -> Dict[str, Any]:
        selectors = [
            'script[data-capla-store-data="apollo"]',
            'script[type="application/json"][data-capla-store-data="apollo"]',
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() == 0:
                    continue
                raw = loc.first.inner_text().strip()
                if not raw:
                    continue
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return {}

    def _extract_featured_reviews_from_apollo(self, page: Page, hotel_id: str, limit: int) -> List[Dict[str, Any]]:
        state = self._extract_apollo_state(page)
        if not state:
            return []

        records = []
        seen = set()

        for key, node in state.items():
            if not isinstance(key, str) or not key.startswith("FeaturedReview:"):
                continue
            if not isinstance(node, dict):
                continue

            reviewer_name = normalize_text(node.get("guestName"), default="N/A")
            score = self.clean_float(str(node.get("averageScore")))
            completed = node.get("completed")
            review_date = "N/A"
            if completed is not None:
                try:
                    ts = int(float(str(completed)))
                    review_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                except Exception:
                    review_date = "N/A"

            positive = normalize_text(node.get("positiveText"), default="")
            negative = normalize_text(node.get("negativeText"), default="")
            title = normalize_text(node.get("title"), default="")

            parts = []
            if title and title != "N/A":
                parts.append(title)
            if positive and positive != "N/A":
                parts.append(f"Pros: {positive}")
            if negative and negative != "N/A":
                parts.append(f"Cons: {negative}")
            review_text = normalize_text(" | ".join(parts), default="N/A")

            if review_text == "N/A":
                continue
            signature = (reviewer_name, review_date, review_text)
            if signature in seen:
                continue
            seen.add(signature)

            item = {
                "review_id": str(uuid.uuid4()),
                "hotel_id": hotel_id,
                "reviewer_name": reviewer_name,
                "review_text": review_text,
                "review_rating": score,
                "review_date": review_date,
                "language": normalize_text(node.get("language"), default="en"),
                "helpful_count": None,
            }
            records.append(item)
            if len(records) >= limit:
                break

        return records

    def _page_html(self, page: Page) -> str:
        try:
            return page.content()
        except Exception:
            return ""

    def _extract_booking_env_coords(self, html_content: str) -> tuple[Optional[float], Optional[float]]:
        lat_match = re.search(r"booking\.env\.b_map_center_latitude\s*=\s*([\-\d.]+)", html_content, flags=re.IGNORECASE)
        lon_match = re.search(r"booking\.env\.b_map_center_longitude\s*=\s*([\-\d.]+)", html_content, flags=re.IGNORECASE)
        lat = self.clean_float(lat_match.group(1)) if lat_match else None
        lon = self.clean_float(lon_match.group(1)) if lon_match else None
        if lat is not None and not (-90 <= lat <= 90):
            lat = None
        if lon is not None and not (-180 <= lon <= 180):
            lon = None
        return lat, lon

    def _extract_booking_score(self, page: Page) -> tuple[Optional[float], Optional[int]]:
        body_text = ""
        try:
            body_text = normalize_text(page.locator("body").inner_text(), default="")
        except Exception:
            pass

        score_patterns = [
            r"\b(Exceptional|Wonderful|Superb|Fabulous|Very good|Good|Pleasant)\s+([0-9](?:[\.,]\d)?)\b",
            r"\b([0-9](?:[\.,]\d)?)\s*/\s*10\b",
            r"\bReview score\b[^\d]{0,20}([0-9](?:[\.,]\d)?)\b",
        ]
        for pattern in score_patterns:
            match = re.search(pattern, body_text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
            score = self.clean_float(value)
            if score is not None:
                return score, None

        html_content = self._page_html(page)
        score_match = re.search(r'"reviewScore"\s*:\s*"?([0-9](?:[\.,]\d)?)"?', html_content, flags=re.IGNORECASE)
        count_match = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', html_content, flags=re.IGNORECASE)
        score = self.clean_float(score_match.group(1)) if score_match else None
        review_count = self.clean_int(count_match.group(1)) if count_match else None
        return score, review_count

    def _open_reviews_section(self, page: Page) -> bool:
        selectors = [
            'a[href*="#tab-reviews"]',
            'button:has-text("Reviews")',
            'a:has-text("Reviews")',
            'button:has-text("No reviews yet")',
            'a:has-text("No reviews yet")',
            '[data-testid*="reviews"]',
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() == 0:
                    continue
                loc.first.click(timeout=5000)
                page.wait_for_timeout(3500)
                return True
            except Exception:
                continue
        return False

    def _parse_booking_review_text(self, text: str) -> Optional[Dict[str, Any]]:
        raw = html.unescape(text or "")
        raw = raw.strip()
        if not raw:
            return None

        raw = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"</(p|div|li|tr|section|article|h\d)>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)

        lines = [normalize_text(line, default="") for line in raw.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return None

        reviewer_name = lines[0]
        review_rating = None
        review_date = "N/A"

        date_patterns = [
            r"Ngày đánh giá:?(?:\s*ngày)?\s*\d{1,2}\s*tháng\s*\d{1,2}\s*năm\s*\d{4}",
            r"Reviewed:?(?:\s*on)?\s+[A-Z][a-z]{2,9}\s+\d{1,2},?\s+\d{4}",
            r"Reviewed:?(?:\s*on)?\s+[A-Z][a-z]{2,9}\s+\d{4}",
            r"Reviewed:?(?:\s*on)?\s+\d{1,2}\s+[A-Z][a-z]{2,9}\s+\d{4}",
            r"\b\d{1,2}\s+[A-Z][a-z]{2,9}\s+\d{4}\b",
            r"\b\d+\s+(?:day|week|month|year)s?\s+ago\b",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE | re.UNICODE)
            if match:
                review_date = normalize_text(match.group(0))
                break

        score_patterns = [
            r"\b(10|[1-9](?:[\.,]\d)?)\b",
            r"\b([1-9](?:[\.,]\d)?)\s*/\s*10\b",
        ]
        for line in lines:
            if re.fullmatch(r"10|[1-9](?:[\.,]\d)?", line):
                review_rating = self.clean_float(line)
                break
        if review_rating is None:
            for pattern in score_patterns:
                match = re.search(pattern, raw)
                if match:
                    candidate = self.clean_float(match.group(1))
                    if candidate is not None and 0 < candidate <= 10:
                        review_rating = candidate
                        break

        body_lines = []
        for line in lines[1:]:
            lowered = line.lower()
            if lowered in {"việt nam", "my", "us", "uk", "germany", "france", "australia", "vietnam"}:
                continue
            if review_date != "N/A" and review_date.lower() in lowered:
                continue
            if re.fullmatch(r"10|[1-9](?:[\.,]\d)?", line):
                continue
            if lowered.startswith("ngày đánh giá") or lowered.startswith("reviewed"):
                continue
            body_lines.append(line)

        review_text = " ".join(body_lines).strip()
        if not review_text:
            review_text = raw

        helpful_count = None
        helpful_match = re.search(r"\b(\d+)\s+people?\s+find(?:s)?\s+it\s+helpful\b", raw, flags=re.IGNORECASE)
        if helpful_match:
            try:
                helpful_count = int(helpful_match.group(1))
            except ValueError:
                helpful_count = None

        return {
            "reviewer_name": reviewer_name,
            "review_rating": review_rating,
            "review_date": review_date,
            "review_text": review_text,
            "helpful_count": helpful_count,
        }

    def _extract_occupancy(self, text: str) -> str:
        match = re.search(r"(?:×\s*)?(\d+)\s*(?:guest|guests|adult|adults|person|people)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"×\s*(\d+)", text)
        if match:
            return match.group(1)
        return "2"

    def build_search_url(self, page_number: int, query: str) -> str:
        offset = (page_number - 1) * 25
        city_query = query.replace(" ", "+")
        return (
            "https://www.booking.com/searchresults.en-gb.html"
            f"?ss={city_query}&group_adults=2&no_rooms=1&group_children=0&offset={offset}"
        )

    def crawl_list(self, page: Page) -> List[Dict[str, Any]]:
        items = []
        seen = set()
        queries = self.get_search_queries()

        for query in queries:
            for page_num in range(1, self.max_pages + 1):
                url = self.build_search_url(page_num, query)
                logging.info(f"[Booking] List page {page_num} | query={query} | {url}")
                if not self.goto_with_retry(page, url):
                    continue

                try:
                    page.wait_for_selector('a[data-testid="title-link"]', timeout=25000)
                except TimeoutError:
                    logging.warning(f"[Booking] No list cards found on page {page_num} for query={query}")
                    continue

                links = page.locator('a[data-testid="title-link"]')
                count = links.count()
                logging.info(f"[Booking] Found {count} list links on page {page_num} for query={query}")

                for i in range(count):
                    try:
                        anchor = links.nth(i)
                        href = normalize_text(anchor.get_attribute("href"), default="")
                        if not href:
                            continue
                        href = href.split("?", 1)[0]
                        if "/hotel/vn/" not in href.lower():
                            continue
                        if href in seen:
                            continue
                        seen.add(href)

                        name = normalize_text(anchor.inner_text(), default="N/A")
                        card_text = normalize_text(anchor.locator("xpath=../..").inner_text(), default="")
                        property_type = self.detect_property_type(name, card_text, href, query)

                        rating = None
                        review_count = None
                        rating_match = re.search(r"\b([1-9](?:[\.,]\d)?)\b", card_text)
                        if rating_match:
                            rating = self.clean_float(rating_match.group(1))
                        review_match = re.search(r"([\d,.]+)\s+reviews?", card_text, flags=re.IGNORECASE)
                        if review_match:
                            review_count = self.clean_int(review_match.group(1))

                        item = {
                            "hotel_id": stable_hotel_id(href),
                            "name": name,
                            "rating": rating,
                            "review_count": review_count,
                            "location_short": self.search_city,
                            "property_type": property_type,
                            "link": href,
                        }
                        items.append(item)
                    except Exception:
                        continue

        logging.info(f"[Booking] Collected list candidates: {len(items)}")
        return items

    def _extract_text(self, page: Page, selectors: Iterable[str], default: str = "N/A") -> str:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    return normalize_text(loc.first.inner_text(), default=default)
            except Exception:
                continue
        return default

    def _extract_hotel_from_detail(self, page: Page, list_item: Dict[str, Any]) -> Dict[str, Any]:
        jsonlds = self._extract_jsonld(page)
        html_content = self._page_html(page)

        title = self._extract_text(page, ['h2[data-testid="title"]', 'h1'])
        if title == "N/A":
            title = list_item.get("name", "N/A")

        description = self._extract_text(
            page,
            [
                '[data-testid="property-description"]',
                '#property_description_content',
                'meta[name="description"]',
            ],
        )

        full_address = self._extract_text(
            page,
            [
                '[data-testid="address"]',
                '.hp_address_subtitle',
                '.bui-f-font-body_2',
            ],
        )

        rating = list_item.get("rating")
        review_count = list_item.get("review_count")
        latitude = None
        longitude = None
        star_rating = None

        for item in jsonlds:
            item_type = str(item.get("@type", "")).lower()
            if item_type in {"hotel", "lodgingbusiness", "hostel", "apartment", "resort"}:
                title = normalize_text(item.get("name"), default=title)
                address = item.get("address")
                if isinstance(address, dict):
                    full_address = normalize_text(
                        ", ".join(
                            [
                                normalize_text(address.get("streetAddress"), default=""),
                                normalize_text(address.get("addressLocality"), default=""),
                                normalize_text(address.get("addressRegion"), default=""),
                                normalize_text(address.get("addressCountry"), default=""),
                            ]
                        ).strip(" ,"),
                        default=full_address,
                    )
                geo = item.get("geo")
                if isinstance(geo, dict):
                    latitude = self.clean_float(str(geo.get("latitude")))
                    longitude = self.clean_float(str(geo.get("longitude")))
                aggregate = item.get("aggregateRating")
                if isinstance(aggregate, dict):
                    rating = self.clean_float(str(aggregate.get("ratingValue"))) or rating
                    review_count = self.clean_int(str(aggregate.get("reviewCount"))) or review_count
                star_raw = item.get("starRating")
                if isinstance(star_raw, dict):
                    star_rating = self.clean_float(str(star_raw.get("ratingValue") or star_raw.get("value")))
                elif star_raw is not None:
                    star_rating = self.clean_float(str(star_raw))

        env_lat, env_lon = self._extract_booking_env_coords(html_content)
        if latitude is None:
            latitude = env_lat
        if longitude is None:
            longitude = env_lon

        if latitude is not None and not (-90 <= latitude <= 90):
            latitude = None
        if longitude is not None and not (-180 <= longitude <= 180):
            longitude = None

        property_type = self.detect_property_type(
            title,
            list_item.get("property_type", ""),
            description,
            full_address,
            list_item.get("link", ""),
        )

        if rating is None or review_count is None:
            score, review_total = self._extract_booking_score(page)
            if rating is None:
                rating = score
            if review_count is None:
                review_count = review_total

        return {
            "hotel_id": list_item["hotel_id"],
            "name": title,
            "rating": rating,
            "review_count": review_count,
            "location_short": self.search_city,
            "property_type": property_type,
            "link": list_item.get("link", "N/A"),
            "full_address": full_address,
            "latitude": latitude,
            "longitude": longitude,
            "description": description,
            "star_rating": star_rating,
        }

    def crawl_rooms_and_prices(self, page: Page, hotel_id: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        room_records = []
        price_records = []
        seen_chunks = set()

        selectors = [
            '[data-testid="rooms-table"] tr',
            '[data-testid="room-card"]',
            'table tr',
        ]

        blocks = None
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    blocks = loc
                    break
            except Exception:
                continue

        if blocks is None:
            return room_records, price_records

        count = min(blocks.count(), 200)
        for i in range(count):
            try:
                text = normalize_text(blocks.nth(i).inner_text(), default="")
            except Exception:
                continue
            if not text or len(text) < 20 or text in seen_chunks:
                continue
            seen_chunks.add(text)

            lower = text.lower()
            if any(token in lower for token in ["accommodation type", "number of guests", "select rooms", "your choices"]):
                continue

            room_name = "N/A"
            room_name_candidates = text.split("\n")
            room_name_candidates = [normalize_text(x, default="") for x in room_name_candidates]
            room_name_candidates = [x for x in room_name_candidates if x and len(x) >= 3]
            for candidate in room_name_candidates:
                candidate_lower = candidate.lower()
                if any(token in candidate_lower for token in ["vnd", "usd", "eur", "book", "select", "total", "tax", "free cancellation"]):
                    continue
                if len(candidate.split()) > 16:
                    continue
                room_name = candidate
                break
            room_name = re.sub(r"\+?\s*show prices.*$", "", room_name, flags=re.IGNORECASE).strip()
            room_name = re.sub(r"\bshow prices\b.*$", "", room_name, flags=re.IGNORECASE).strip()
            room_name = re.sub(r"\s{2,}", " ", room_name).strip()
            if not room_name or room_name == "N/A":
                room_name = "Standard Room"

            area_match = re.search(r"(\d+(?:[\.,]\d+)?)\s*m²", text, flags=re.IGNORECASE)
            capacity_match = re.search(r"(\d+)\s*(?:guest|guests|adult|adults|person|people)", text, flags=re.IGNORECASE)
            occupancy = self._extract_occupancy(text)

            bed_type = "N/A"
            for token in ["double bed", "single bed", "queen bed", "king bed", "twin bed", "bunk bed", "sofa bed"]:
                if token in text.lower():
                    bed_type = token
                    break

            view = "N/A"
            for token in ["sea view", "city view", "garden view", "river view", "mountain view", "pool view"]:
                if token in text.lower():
                    view = token
                    break

            room_id = str(uuid.uuid4())
            room_item = {
                "room_id": room_id,
                "hotel_id": hotel_id,
                "room_name": room_name,
                "capacity": capacity_match.group(1) if capacity_match else occupancy,
                "bed_type": bed_type,
                "area": self.clean_float(area_match.group(1)) if area_match else "N/A",
                "view": view,
                "amenities_room": text,
            }
            room_records.append(room_item)
            self.save_room(room_item)

            price, currency = self.parse_price_and_currency(text)
            if price is not None:
                price_item = {
                    "price_id": str(uuid.uuid4()),
                    "hotel_id": hotel_id,
                    "room_name": room_name,
                    "price": price,
                    "currency": currency,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "occupancy": occupancy,
                    "is_discount": any(x in text.lower() for x in ["discount", "deal", "save", "promo"]),
                    "room_id": room_id,
                    "matched_room_name": room_name,
                    "match_method": "direct",
                    "match_score": 0,
                }
                price_records.append(price_item)
                self.save_price(price_item)

        return room_records, price_records

    def _fallback_price_from_page(self, page: Page) -> tuple[Optional[int], str]:
        body = ""
        try:
            body = normalize_text(page.locator("body").inner_text(), default="")
        except Exception:
            pass
        if not body:
            return None, "N/A"
        return self.parse_price_and_currency(body)

    def crawl_policies(self, page: Page, hotel_id: str) -> List[Dict[str, Any]]:
        records = []
        body = ""
        try:
            body = normalize_text(page.locator("body").inner_text(), default="")
        except Exception:
            pass

        if not body:
            return records

        checks = [
            ("check_in_time", r"Check-in[^\d]{0,20}(\d{1,2}:\d{2}|\d{1,2}\s*[AP]M)"),
            ("check_out_time", r"Check-out[^\d]{0,20}(\d{1,2}:\d{2}|\d{1,2}\s*[AP]M)"),
        ]
        for policy_type, pattern in checks:
            match = re.search(pattern, body, flags=re.IGNORECASE)
            if match:
                item = {
                    "policy_id": str(uuid.uuid4()),
                    "hotel_id": hotel_id,
                    "policy_type": policy_type,
                    "policy_value": normalize_text(match.group(1)),
                }
                records.append(item)
                self.save_policy(item)

        for label, policy_type in [("Cancellation", "cancellation_policy"), ("Children", "children_policy"), ("Pets", "pet_policy")]:
            idx = body.lower().find(label.lower())
            if idx != -1:
                snippet = normalize_text(body[max(0, idx - 80): idx + 260], default="")
                if snippet:
                    item = {
                        "policy_id": str(uuid.uuid4()),
                        "hotel_id": hotel_id,
                        "policy_type": policy_type,
                        "policy_value": snippet,
                    }
                    records.append(item)
                    self.save_policy(item)

        unique = []
        seen = set()
        for row in records:
            key = (row["policy_type"], row["policy_value"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def crawl_images(self, page: Page, hotel_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        records = []
        seen = set()
        try:
            imgs = page.locator("img")
            for i in range(min(imgs.count(), 350)):
                src = normalize_text(imgs.nth(i).get_attribute("src"), default="")
                if not src:
                    src = normalize_text(imgs.nth(i).get_attribute("data-src"), default="")
                if not src or not src.startswith("http") or src in seen:
                    continue
                lower_src = src.lower()
                if any(token in lower_src for token in ["criteo", "pixel", "widget", "event?", ".gif"]):
                    continue
                if "xdata/images/hotel" not in lower_src and "xdata/images/xphoto" not in lower_src:
                    continue
                seen.add(src)
                item = {
                    "image_id": str(uuid.uuid4()),
                    "hotel_id": hotel_id,
                    "image_url": src,
                }
                records.append(item)
                self.save_image(item)
                if len(records) >= limit:
                    break
        except Exception:
            pass
        return records

    def crawl_reviews(self, page: Page, hotel_id: str, min_reviews: int = 10) -> List[Dict[str, Any]]:
        records = []
        seen = set()

        apollo_reviews = self._extract_featured_reviews_from_apollo(page, hotel_id, min_reviews)
        if apollo_reviews:
            for row in apollo_reviews:
                self.save_review(row)
            return apollo_reviews

        self._open_reviews_section(page)

        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass

        selectors = [
            '[data-testid="review-card"]',
            '[data-testid="review-score"]',
            '.c-review-block',
            '[data-testid*="review-card"]',
            '[data-testid*="review-item"]',
            'article:has-text("Ngày đánh giá")',
            'article:has-text("Reviewed")',
            'li:has-text("Ngày đánh giá")',
            'li:has-text("Reviewed")',
        ]

        blocks = None
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    blocks = loc
                    break
            except Exception:
                continue

        if blocks is None:
            body = ""
            try:
                body = normalize_text(page.locator("body").inner_text(), default="")
            except Exception:
                pass
            if "no reviews yet" in body.lower():
                return records
            if not re.search(r"(?:Ngày đánh giá|Reviewed|review score|\b10\b)", body, flags=re.IGNORECASE):
                return records
            if body:
                review_chunks = re.split(r"(?:\n|\r\n){2,}", body)
                for chunk in review_chunks:
                    parsed = self._parse_booking_review_text(chunk)
                    if parsed is None:
                        continue
                    key = (parsed["reviewer_name"], parsed["review_date"], parsed["review_text"])
                    if key in seen:
                        continue
                    seen.add(key)
                    item = {
                        "review_id": str(uuid.uuid4()),
                        "hotel_id": hotel_id,
                        "reviewer_name": parsed["reviewer_name"],
                        "review_text": parsed["review_text"],
                        "review_rating": parsed["review_rating"],
                        "review_date": parsed["review_date"],
                        "language": "en",
                        "helpful_count": parsed.get("helpful_count"),
                    }
                    records.append(item)
                    self.save_review(item)
                    if len(records) >= min_reviews:
                        return records
            return records

        count = min(blocks.count(), 200)
        for i in range(count):
            try:
                text = normalize_text(blocks.nth(i).inner_text(), default="")
            except Exception:
                continue
            if not text or len(text) < 20 or text in seen:
                continue
            seen.add(text)

            parsed = self._parse_booking_review_text(text)
            if parsed is None:
                continue

            review_item = {
                "review_id": str(uuid.uuid4()),
                "hotel_id": hotel_id,
                "reviewer_name": parsed["reviewer_name"],
                "review_text": parsed["review_text"],
                "review_rating": parsed["review_rating"],
                "review_date": parsed["review_date"],
                "language": "en",
                "helpful_count": parsed.get("helpful_count"),
            }
            records.append(review_item)
            self.save_review(review_item)
            if len(records) >= min_reviews:
                break

        return records

    def crawl_detail(self, context, list_item: Dict[str, Any]) -> bool:
        detail_page = context.new_page()
        link = list_item["link"]

        try:
            if not self.goto_with_retry(detail_page, link):
                return False

            hotel = self._extract_hotel_from_detail(detail_page, list_item)
            if not self.is_non_hotel_type(hotel["property_type"]):
                logging.info(f"[Booking] Skip hotel-like property: {hotel['property_type']} | {hotel['name']}")
                return False
            if not self.is_target_location(hotel, target_city=self.search_city):
                logging.info(f"[Booking] Skip non-target city property: {self.search_city} | {hotel.get('name')}")
                return False

            self.save_hotel(hotel)
            room_records, price_records = self.crawl_rooms_and_prices(detail_page, hotel["hotel_id"])
            if not room_records:
                fallback_room = {
                    "room_id": str(uuid.uuid4()),
                    "hotel_id": hotel["hotel_id"],
                    "room_name": "Standard Room",
                    "capacity": "N/A",
                    "bed_type": "N/A",
                    "area": "N/A",
                    "view": "N/A",
                    "amenities_room": "N/A",
                }
                room_records.append(fallback_room)
                self.save_room(fallback_room)

            if not price_records:
                fallback_price, fallback_currency = self._fallback_price_from_page(detail_page)
                if fallback_price is not None:
                    first_room = room_records[0]
                    fallback_price_item = {
                        "price_id": str(uuid.uuid4()),
                        "hotel_id": hotel["hotel_id"],
                        "room_name": first_room.get("room_name", "Standard Room"),
                        "price": fallback_price,
                        "currency": fallback_currency,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "occupancy": first_room.get("capacity", "2"),
                        "is_discount": False,
                        "room_id": first_room.get("room_id"),
                        "matched_room_name": first_room.get("room_name", "Standard Room"),
                        "match_method": "fallback_page",
                        "match_score": 0,
                    }
                    self.save_price(fallback_price_item)

            self.crawl_policies(detail_page, hotel["hotel_id"])
            self.crawl_images(detail_page, hotel["hotel_id"])
            self.crawl_reviews(detail_page, hotel["hotel_id"], min_reviews=self.min_reviews)

            logging.info(f"✅ [Booking] Saved property: {hotel['hotel_id']} | {hotel['name']}")
            random_sleep(0.8, 1.6)
            return True
        except Exception as exc:
            logging.error(f"[Booking] Detail crawl failed for {link}: {exc}")
            return False
        finally:
            detail_page.close()

    def run(self) -> None:
        logging.info("[Booking] Starting Booking.com crawler...")
        self.init_outputs()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
            context = browser.new_context(
                user_agent=random.choice(self.user_agents),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                java_script_enabled=True,
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            page = context.new_page()
            saved = 0
            try:
                items = self.crawl_list(page)
                logging.info(f"[Booking] List records collected: {len(items)}")
                for idx, item in enumerate(items, 1):
                    logging.info(f"[Booking] [{idx}/{len(items)}] Crawl detail: {item.get('link')}")
                    ok = self.crawl_detail(context, item)
                    if ok:
                        saved += 1
                    if saved >= self.max_properties:
                        break
            finally:
                browser.close()

        logging.info(f"[Booking] Crawler finished. Total properties saved: {saved}")


# ==========================================
# MAIN EXECUTION ENTRY POINT
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="Unified Crawler Orchestrator for Agoda & Booking.com")
    parser.add_argument("--source", choices=["all", "agoda", "booking"], default="all",
                        help="Choose which crawl source to execute (default: all)")
    parser.add_argument("--city", default="Da Nang", help="City keyword to search for Booking.com (default: Da Nang)")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run browser with visual interface")
    parser.set_defaults(headless=True)
    
    # Platform specific limits
    parser.add_argument("--max-pages", type=int, default=None, 
                        help="Override maximum list pages to crawl (Default: Agoda=200, Booking=2)")
    parser.add_argument("--max-results", type=int, default=None,
                        help="Override maximum properties/hotels to crawl (Default: Agoda=5000, Booking=50)")
    parser.add_argument("--reviews-limit", type=int, default=None,
                        help="Override reviews cào per property (Default: Agoda=15, Booking=10)")

    args = parser.parse_args()

    logging.info(f"Starting unified crawler pipeline with config: {vars(args)}")

    sources_to_run = []
    if args.source == "all":
        sources_to_run = ["agoda", "booking"]
    else:
        sources_to_run = [args.source]

    for source in sources_to_run:
        if source == "agoda":
            max_pages = args.max_pages if args.max_pages is not None else 200
            max_hotels = args.max_results if args.max_results is not None else 5000
            reviews_per_hotel = args.reviews_limit if args.reviews_limit is not None else 15
            
            engine = AgodaCrawlerEngine(
                headless=args.headless,
                max_pages=max_pages,
                max_hotels=max_hotels,
                reviews_per_hotel=reviews_per_hotel
            )
            try:
                engine.run()
            except Exception as e:
                logging.error(f"Agoda crawler pipeline failed: {e}", exc_info=True)

        elif source == "booking":
            max_pages = args.max_pages if args.max_pages is not None else 2
            max_properties = args.max_results if args.max_results is not None else 50
            min_reviews = args.reviews_limit if args.reviews_limit is not None else 10
            
            engine = BookingCrawlerEngine(
                headless=args.headless,
                max_pages=max_pages,
                max_properties=max_properties,
                min_reviews=min_reviews,
                search_city=args.city
            )
            try:
                engine.run()
            except Exception as e:
                logging.error(f"Booking crawler pipeline failed: {e}", exc_info=True)

    logging.info("Unified Crawler process completed.")


if __name__ == "__main__":
    main()
