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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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

def clean_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"\d+[\.,]?\d*", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None

def clean_int(text: Optional[str]) -> Optional[int]:
    value = clean_float(text)
    if value is None:
        return None
    return int(value)

def parse_price_and_currency(text: Optional[str]) -> tuple[Optional[int], str]:
    if not text:
        return None, "N/A"
    raw = normalize_text(text)
    currency_pattern = r"(VND|USD|EUR|GBP|JPY|AUD|CAD|SGD|THB|IDR|MYR|PHP|KRW|TWD|HKD|\$|€|£|₫)"
    currency_match = re.search(currency_pattern, raw, flags=re.IGNORECASE)
    currency = currency_match.group(1).upper() if currency_match else "N/A"

    patterns = [
        rf"{currency_pattern}\s*([\d.,]{{3,}})",
        rf"([\d.,]{{3,}})\s*{currency_pattern}",
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

def stable_hotel_id(link: str) -> str:
    digest = hashlib.md5(link.encode("utf-8")).hexdigest()[:16]
    return f"hotel_{digest}"

def strip_html_tags(text: Optional[str], default: str = "") -> str:
    if text is None:
        return default
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</(p|div|li|tr|section|article|h\d)>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else default



# ==========================================
# TRAVELOKA CRAWLER ENGINE (face.py)
# ==========================================
class TravelokaCrawlerEngine:
    def __init__(self, headless: bool = True, max_pages: int = 114, max_hotels: int = 5000,
                 min_reviews: int = 20, data_dir: Optional[Path] = None):
        self.headless = headless
        self.max_pages = max_pages
        self.max_hotels = max_hotels
        self.min_reviews = min_reviews
        
        self.data_dir = data_dir or (Path.cwd() / "dataset")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.hotels_jsonl = self.data_dir / "hotels.jsonl"
        self.prices_jsonl = self.data_dir / "prices.jsonl"
        self.rooms_jsonl = self.data_dir / "rooms.jsonl"
        self.reviews_jsonl = self.data_dir / "reviews.jsonl"
        self.policies_jsonl = self.data_dir / "policies.jsonl"
        self.images_jsonl = self.data_dir / "images.jsonl"
        
        self.hotels_csv = self.data_dir / "hotels.csv"
        self.prices_csv = self.data_dir / "prices.csv"
        self.rooms_csv = self.data_dir / "rooms.csv"
        self.reviews_csv = self.data_dir / "reviews.csv"
        self.policies_csv = self.data_dir / "policies.csv"
        self.images_csv = self.data_dir / "images.csv"
        self.checkpoint_jsonl = self.data_dir / "crawl_checkpoint.jsonl"
        
        self.site_base = "https://www.traveloka.com/en-vn/hotel/vietnam/region/da-nang-10010083"
        self.max_review_pages = 6
        self.request_retries = 4
        self.list_scroll_passes = 3
        self.list_max_scroll_rounds = 500
        self.list_max_stable_rounds = 10
        self.list_min_rounds_before_stop = 6
        self.list_scroll_wait_ms = 1800
        self.list_scroll_pixels = 2200
        self.search_date_offset_days = 21
        self.search_stay_nights = 1
        self.detail_load_wait_ms = 2500
        self.section_settle_wait_ms = 1800
        self.review_round_wait_ms = 2500
        self.manual_verification_delay_seconds = 8
        self.resume_crawl = True
        self.reset_outputs = False
        self.stream_detail_during_list = True
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ]

    def stable_room_id(self, hotel_id: str, room_name: str) -> str:
        raw = f"{hotel_id}|{normalize_text(room_name, default='unknown-room').lower()}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        return f"room_{digest}"

    def normalize_room_name_key(self, room_name: str) -> str:
        normalized = normalize_text(room_name, default="unknown-room").lower()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def detect_property_type(self, text: str) -> str:
        raw = normalize_text(text, default="").lower()
        mapping = {
            "resort": "Resort", "homestay": "Homestay", "apartment": "Apartment", "villa": "Villa",
            "hotel": "Hotel", "hostel": "Hostel", "ryokan": "Ryokan", "guesthouse": "Guesthouse",
            "guest house": "Guesthouse", "inn": "Inn", "motel": "Motel", "bnb": "B&B",
            "bed and breakfast": "B&B", "private": "Private Vacation Home", "khách sạn": "Hotel",
            "căn hộ": "Apartment", "nhà nghỉ": "Guesthouse", "resot": "Resort",
            "nhà để nghỉ dưỡng riêng tư": "Private Vacation Home",
        }
        for token, label in mapping.items():
            if token in raw:
                return label
        return "Accommodation"

    def current_crawl_date(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def current_search_dates(self) -> tuple[str, str]:
        check_in = datetime.now().date() + timedelta(days=self.search_date_offset_days)
        check_out = check_in + timedelta(days=self.search_stay_nights)
        return check_in.strftime("%Y-%m-%d"), check_out.strftime("%Y-%m-%d")

    def _date_from_relative_review_text(self, text: str) -> Optional[str]:
        raw = normalize_text(text, default="").lower()
        amount: Optional[int] = None
        unit: Optional[str] = None

        match = re.search(r"(?:đánh giá\s+)?cách đây\s+(\d+)\s+(ngày|tuần|tháng|năm)", raw, flags=re.IGNORECASE)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
        else:
            match = re.search(r"(\d+)\s+(day|week|month|year)s?\s+ago", raw, flags=re.IGNORECASE)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)

        if amount is None or unit is None:
            match = re.search(r"(\d+)\s+(ngày|tuần|tháng|năm)\s+trước", raw, flags=re.IGNORECASE)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)

        if amount is None or unit is None:
            placeholder = re.search(r"\b(day|week|month|year)\(s\)\s+ago\b", raw, flags=re.IGNORECASE)
            if placeholder:
                amount = 1
                unit = placeholder.group(1)

        if amount is None or unit is None:
            return None

        today = datetime.now().date()
        if unit in {"day", "ngày"}:
            target = today - timedelta(days=amount)
        elif unit in {"week", "tuần"}:
            target = today - timedelta(weeks=amount)
        elif unit in {"month", "tháng"}:
            target = today - timedelta(days=amount * 30)
        else:
            target = today - timedelta(days=amount * 365)
        return target.strftime("%Y-%m-%d")

    def safe_locator_text(self, locator, selectors: Iterable[str], default: str = "N/A") -> str:
        for selector in selectors:
            try:
                loc = locator.locator(selector)
                if loc.count() > 0:
                    return normalize_text(loc.first.inner_text(), default=default)
            except Exception:
                continue
        return default

    def goto_with_retry(self, page: Page, url: str, retries: int = 4) -> bool:
        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=70000)
                page.wait_for_timeout(5000)
                if self.manual_verification_delay_seconds > 0:
                    logging.info(
                        "Manual verification window: waiting %ss on %s",
                        self.manual_verification_delay_seconds,
                        page.url,
                    )
                    page.wait_for_timeout(self.manual_verification_delay_seconds * 1000)
                return True
            except Exception as exc:
                logging.warning(f"[Traveloka] goto failed ({attempt}/{retries}): {exc}")
                random_sleep(1.2, 2.5)
        return False

    def build_list_url(self, page_number: int) -> str:
        check_in, check_out = self.current_search_dates()
        if page_number <= 1:
            return f"{self.site_base}?viewType=list&checkIn={check_in}&checkOut={check_out}"
        return f"{self.site_base}/{page_number}?viewType=list&checkIn={check_in}&checkOut={check_out}"

    def click_if_present(self, page: Page, selectors: Iterable[str], timeout_ms: int = 2500) -> bool:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    loc.first.click(timeout=timeout_ms)
                    page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
        return False

    def _scroll_page_by(self, page: Page, pixels: int) -> None:
        try:
            page.evaluate("window.scrollBy(0, arguments[0]);", pixels)
        except Exception:
            page.mouse.wheel(0, pixels)

    def _scroll_page_to_top(self, page: Page) -> None:
        try:
            page.evaluate("window.scrollTo(0, 0);")
        except Exception:
            pass

    def _list_footer_visible(self, page: Page) -> bool:
        selectors = ['text=Explore promos', 'text=Explore Promos']
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    return True
            except Exception:
                continue
        return False

    def _split_text_chunks(self, text: str, start_pattern: Any) -> List[str]:
        matches = list(start_pattern.finditer(text))
        if not matches:
            cleaned = normalize_text(text, default="")
            return [cleaned] if cleaned else []

        chunks = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunk = normalize_text(text[start:end], default="")
            if chunk:
                chunks.append(chunk)
        return chunks

    def _split_review_chunks(self, text: str) -> List[str]:
        start_pattern = re.compile(
            r"(?:^|\s)(?P<name>[A-ZÀ-ỹ0-9*][^\n]{0,70}?)\s+(?P<rating>\d{1,2}(?:[\.,]\d)?)\s*/\s*10",
            flags=re.IGNORECASE | re.UNICODE,
        )
        return self._split_text_chunks(text, start_pattern)

    def _split_room_chunks(self, text: str) -> List[str]:
        start_pattern = re.compile(r"(?<!\d)(?P<size>\d+(?:[\.,]\d+)?)\s*m[²]", flags=re.IGNORECASE)
        return self._split_text_chunks(text, start_pattern)

    def _is_property_detail_link(self, href: str) -> bool:
        if not href:
            return False
        lower = href.lower()
        if any(token in lower for token in ["/area/", "/landmark/", "/city/", "/region/", "/curation", "/search?"]):
            return False
        patterns = [
            r"/en-vn/hotel/vietnam/[^/?#]+-\d+(?:[/?#].*)?$",
            r"/en-vn/accommodation/[^/?#]+-\d+(?:[/?#].*)?$",
            r"/hotel/vietnam/[^/?#]+-\d+(?:[/?#].*)?$",
            r"/accommodation/[^/?#]+-\d+(?:[/?#].*)?$",
        ]
        return any(re.search(pattern, lower) is not None for pattern in patterns)

    def _extract_review_date(self, text: str) -> str:
        relative_date = self._date_from_relative_review_text(text)
        if relative_date:
            return relative_date

        patterns = [
            r"Reviewed\s+(?:on\s+)?[A-Z][a-z]{2,9}\s+\d{1,2},?\s+\d{4}",
            r"Reviewed\s+[A-Z][a-z]{2,9}\s+\d{4}",
            r"Reviewed\s+\d{1,2}\s+[A-Z][a-z]{2,9}\s+\d{4}",
            r"Reviewed\s+\d+\s+(?:day|week|month|year)s?\s+ago",
            r"Reviewed\s+\d+\s+(?:day|week|month|year)s? ago",
            r"\b\d+\s+(?:day|week|month|year)s?\s+ago\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            if match:
                result = normalize_text(match.group(0))
                if result and result != "N/A":
                    return result
        return "N/A"

    def _clean_review_body(self, text: str) -> str:
        cleaned = normalize_text(text, default="")
        if not cleaned:
            return "N/A"
        cleaned = re.sub(r"^\w+\(s\)\s+ago\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(See original|Read More)\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\b(See original|Read More)\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\b\d+\s+people? find(s)? it helpful\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^Find this review helpful\?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^Summarized by AI\b.*?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^Reviewed\s+.+?$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
        cleaned = re.sub(r"\b\d+\s+(?:day|week|month|year)s?\s+ago\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned or "N/A"

    def _extract_helpful_count(self, text: str) -> Optional[int]:
        match = re.search(r"\b(\d+)\s+people?\s+find(?:s)?\s+it\s+helpful\b", text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        match = re.search(r"\b(\d+)\s+people?\s+found\s+this\s+helpful\b", text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def _extract_review_from_chunk(self, chunk: str) -> Dict[str, Any]:
        date_prefix_match = re.match(r"^\s*(\w+\(s\)\s+ago)\s+", chunk, flags=re.IGNORECASE)
        working_chunk = chunk
        date_from_prefix = None
        
        if date_prefix_match:
            date_prefix = date_prefix_match.group(1)
            working_chunk = chunk[date_prefix_match.end():]
            normalized_prefix = date_prefix.replace("(s)", "")
            if not re.search(r"\d+", normalized_prefix):
                match_unit = re.search(r"(day|week|month|year)", normalized_prefix, re.IGNORECASE)
                if match_unit:
                    unit = match_unit.group(1)
                    normalized_prefix = f"1 {unit} ago"
            date_from_prefix = self._date_from_relative_review_text(normalized_prefix)
        
        match = re.search(
            r"(?P<name>[A-ZÀ-ỹ0-9*][^\n]{0,70}?)\s+(?P<rating>\d{1,2}(?:[\.,]\d)?)\s*/\s*10(?:\s+(?P<date>Reviewed\s+[^\n]+?))?(?:\s+(?P<body>.*))?$",
            working_chunk,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return {
                "reviewer_name": "N/A",
                "review_rating": None,
                "review_date": date_from_prefix or "N/A",
                "review_text": self._clean_review_body(working_chunk),
            }

        remainder = match.group("body") or ""
        review_text = self._clean_review_body(remainder)
        if review_text == "N/A":
            review_text = self._clean_review_body(working_chunk[match.end():])

        review_date = self._extract_review_date(working_chunk)
        if review_date == "N/A" and date_from_prefix:
            review_date = date_from_prefix
        if review_date == "N/A":
            date_match = re.search(r"\b\d{1,2}\s+[A-Z][a-z]{2,9}\s+\d{4}\b", working_chunk)
            if date_match:
                review_date = normalize_text(date_match.group(0))

        return {
            "reviewer_name": normalize_text(match.group("name"), default="N/A"),
            "review_rating": clean_float(match.group("rating")),
            "review_date": review_date,
            "review_text": review_text,
            "helpful_count": self._extract_helpful_count(working_chunk),
        }

    def _extract_room_name_from_text(self, text: str) -> str:
        raw = normalize_text(text, default="")
        if not raw:
            return "N/A"

        generic_names = {
            "room option(s)", "see room details", "guest(s)", "price/room/night",
            "price/room2/night", "non refundable", "free cancellation", "pay at hotel", "holiday fiesta"
        }

        def _clean_candidate(value: str) -> str:
            candidate = normalize_text(value, default="")
            candidate = re.sub(r"\s{2,}", " ", candidate).strip(" -|/")
            candidate = re.sub(r"^Room\s+", "", candidate, flags=re.IGNORECASE).strip()
            candidate = re.sub(r"\b(?:Without Breakfast|With Breakfast|Breakfast Included|Room Only|Best Available Rate)\b.*$", "", candidate, flags=re.IGNORECASE).strip()
            candidate = re.sub(r"\b(?:Non Refundable|Free Cancellation|Pay at Hotel|Holiday Fiesta)\b.*$", "", candidate, flags=re.IGNORECASE).strip()
            candidate = candidate.strip(" -|/")
            return candidate

        patterns = [
            r"Price/room(?:2)?/night\s+(?P<name>.+?)(?=\s+(?:Without Breakfast|With Breakfast|Breakfast Included|Room Only|Non Refundable|Free Cancellation|Pay at Hotel|Holiday Fiesta|x\d|$))",
            r"See Room Details\s+(?P<name>.+?)(?=\s+Room Option\(s\)|\s+Guest\(s\)|\s+Price/room/night|\s+Non Refundable|\s+Free Cancellation|\s+Pay at Hotel|\s+Holiday Fiesta|$)",
            r"(?:Room\s+)(?P<name>[A-Z].+?)(?=\s+Room Option\(s\)|\s+Guest\(s\)|\s+Price/room(?:2)?/night|\s+Non Refundable|\s+Free Cancellation|\s+Pay at Hotel|\s+Holiday Fiesta|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                candidate = _clean_candidate(match.group("name"))
                if candidate and candidate.lower() not in generic_names:
                    return candidate

        fallback = raw.split("Price/room/night", 1)[-1]
        fallback = fallback.split("Price/room2/night", 1)[-1]
        fallback = fallback.split("Room Option(s)", 1)[0].strip()
        fallback = _clean_candidate(fallback)
        fallback = re.sub(r"^\d+(?:[\.,]\d+)?\s*m[²]\s*", "", fallback, flags=re.IGNORECASE)
        fallback = re.sub(r"^(Shower|Bathtub|Refrigerator|Seating area|Hot water|Air conditioning|Free WiFi)\s+", "", fallback, flags=re.IGNORECASE)
        fallback = normalize_text(fallback, default="")
        if fallback and fallback.lower() not in generic_names and len(fallback) <= 120:
            return fallback
        return "N/A"

    def _policy_rows_from_text(self, text: str) -> List[Dict[str, str]]:
        normalized = strip_html_tags(text)
        if not normalized:
            return []

        policies = []
        for policy_type, pattern in [
            ("check_in_time", r"check[- ]?in[^\d]*(\d{1,2}:\d{2})"),
            ("check_out_time", r"check[- ]?out[^\d]*(\d{1,2}:\d{2})"),
        ]:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                policies.append({"policy_type": policy_type, "policy_value": match.group(1)})

        for policy_type in ["cancellation_policy", "children_policy", "pet_policy"]:
            label = policy_type.split("_")[0]
            pos = normalized.lower().find(label)
            if pos != -1:
                snippet = normalize_text(normalized[max(0, pos - 120): pos + 300])
                if snippet:
                    policies.append({"policy_type": policy_type, "policy_value": snippet})

        deduped = []
        seen = set()
        for policy in policies:
            key = (policy["policy_type"], policy["policy_value"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(policy)
        return deduped

    def init_outputs(self, reset: bool = False) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        jsonl_files = [
            self.hotels_jsonl, self.prices_jsonl, self.rooms_jsonl,
            self.reviews_jsonl, self.policies_jsonl, self.images_jsonl,
        ]
        for file_path in jsonl_files:
            if reset or not file_path.exists():
                file_path.write_text("", encoding="utf-8")

        csv_specs = {
            self.hotels_csv: [
                "hotel_id", "name", "price_min", "rating", "review_count", "location_short",
                "property_type", "link", "full_address", "description", "star_rating",
            ],
            self.prices_csv: [
                "price_id", "hotel_id", "room_id", "room_name", "price", "currency", "date", "is_discount",
            ],
            self.rooms_csv: [
                "room_id", "hotel_id", "room_name", "capacity", "bed_type", "area", "view", "amenities_room",
            ],
            self.reviews_csv: [
                "review_id", "hotel_id", "reviewer_name", "review_text", "review_rating", "review_date", "helpful_count",
            ],
            self.policies_csv: [
                "policy_id", "hotel_id", "policy_type", "policy_value",
            ],
            self.images_csv: [
                "image_id", "hotel_id", "image_url",
            ],
        }

        for csv_file, header in csv_specs.items():
            should_write_header = reset or not csv_file.exists() or csv_file.stat().st_size == 0
            if not should_write_header:
                continue
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(header)

        if reset or not self.checkpoint_jsonl.exists():
            self.checkpoint_jsonl.write_text("", encoding="utf-8")

    def load_done_hotel_ids_from_checkpoint(self) -> set[str]:
        done_ids = set()
        if not self.checkpoint_jsonl.exists():
            return done_ids
        try:
            with open(self.checkpoint_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    hotel_id = normalize_text(payload.get("hotel_id"), default="")
                    status = normalize_text(payload.get("status"), default="")
                    if hotel_id and status == "done":
                        done_ids.add(hotel_id)
        except Exception:
            return done_ids
        return done_ids

    def save_checkpoint_done(self, item: Dict[str, Any], reason: Optional[str] = None) -> None:
        payload = {
            "hotel_id": item.get("hotel_id"),
            "link": item.get("link"),
            "status": "done",
            "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if reason:
            payload["reason"] = reason
        self._append_jsonl(self.checkpoint_jsonl, payload)

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

    def save_hotels(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.hotels_jsonl, data)
        self._append_csv(
            self.hotels_csv,
            [
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("name")),
                self._csv_cell(data.get("price_min")),
                self._csv_cell(data.get("rating")),
                self._csv_cell(data.get("review_count")),
                self._csv_cell(data.get("location_short")),
                self._csv_cell(data.get("property_type")),
                self._csv_cell(data.get("link")),
                self._csv_cell(data.get("full_address")),
                self._csv_cell(data.get("description")),
                self._csv_cell(data.get("star_rating")),
            ],
        )

    def save_prices(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.prices_jsonl, data)
        self._append_csv(
            self.prices_csv,
            [
                self._csv_cell(data.get("price_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("room_id")),
                self._csv_cell(data.get("room_name")),
                self._csv_cell(data.get("price")),
                self._csv_cell(data.get("currency")),
                self._csv_cell(data.get("date")),
                data.get("is_discount", False),
            ],
        )

    def save_rooms(self, data: Dict[str, Any]) -> None:
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

    def save_reviews(self, data: Dict[str, Any]) -> None:
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
                self._csv_cell(data.get("helpful_count")),
            ],
        )

    def save_policies(self, data: Dict[str, Any]) -> None:
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

    def save_images(self, data: Dict[str, Any]) -> None:
        self._append_jsonl(self.images_jsonl, data)
        self._append_csv(
            self.images_csv,
            [
                self._csv_cell(data.get("image_id")),
                self._csv_cell(data.get("hotel_id")),
                self._csv_cell(data.get("image_url")),
            ],
        )

    def _extract_card_text(self, anchor, max_depth: int = 4) -> str:
        best_text = normalize_text(anchor.inner_text(), default="")
        for depth in range(1, max_depth + 1):
            try:
                ancestor = anchor.locator("xpath=" + "/".join([".."] * depth))
                text = normalize_text(ancestor.first.inner_text(), default="")
                if len(text) > len(best_text):
                    best_text = text
            except Exception:
                continue
        return best_text

    def _parse_list_card(self, card_text: str) -> Dict[str, Any]:
        price_min = None
        currency = "N/A"
        price_match = re.search(r"(?:VND|₫|USD|EUR|GBP|JPY|AUD|CAD)\s*([\d.,]+)|([\d.,]+)\s*(?:VND|₫)", card_text, flags=re.IGNORECASE)
        if price_match:
            raw_number = price_match.group(1) or price_match.group(2)
            if raw_number:
                try:
                    price_min = int(raw_number.replace(".", "").replace(",", ""))
                except ValueError:
                    price_min = None
            currency_match = re.search(r"(VND|USD|EUR|GBP|JPY|AUD|CAD|₫|\$|€|£)", price_match.group(0), flags=re.IGNORECASE)
            currency = currency_match.group(1).upper() if currency_match else "N/A"

        rating = None
        rating_match = re.search(r"(?:Rating|Rated|Guest rating|Review score)[^\d]*([\d]+(?:[\.,]\d+)?)", card_text, flags=re.IGNORECASE)
        if rating_match:
            rating = clean_float(rating_match.group(1))
        if rating is None:
            float_candidates = [clean_float(x) for x in re.findall(r"\b\d+[\.,]\d+\b", card_text)]
            float_candidates = [x for x in float_candidates if x is not None and 0 <= x <= 10]
            if float_candidates:
                rating = float_candidates[0]

        review_count = None
        review_match = re.search(r"([\d,.]+)\s+reviews?", card_text, flags=re.IGNORECASE)
        if review_match:
            try:
                review_count = int(review_match.group(1).replace(",", "").replace(".", ""))
            except ValueError:
                review_count = None

        return {
            "price_min": price_min,
            "currency": currency,
            "rating": rating,
            "review_count": review_count,
            "location_short": "Da Nang",
        }

    def _extract_expected_total(self, page: Page) -> Optional[int]:
        candidate_text = self.safe_locator_text(
            page,
            ["h1", '[data-testid*="search-result"]', '[data-testid*="result"]', '[class*="result"]', '[class*="search"]'],
            default=""
        )
        if not candidate_text:
            try:
                candidate_text = normalize_text(page.locator("body").inner_text(), default="")
            except Exception:
                candidate_text = ""

        patterns = [
            r"(\d[\d\.,]{1,10})\s+(?:accommodations?|properties|places\s+to\s+stay)\s+found",
            r"(\d[\d\.,]{1,10})\s+nơi\s+lưu\s+trú\s+được\s+tìm\s+thấy",
        ]
        for pattern in patterns:
            match = re.search(pattern, candidate_text, flags=re.IGNORECASE | re.UNICODE)
            if not match:
                continue
            try:
                return int(match.group(1).replace(",", "").replace(".", ""))
            except ValueError:
                continue
        return None

    def _normalize_detail_link(self, href: str) -> str:
        link = href.strip()
        if not link:
            return ""
        if not link.startswith("http"):
            link = f"https://www.traveloka.com{link}"
        link = link.split("#", 1)[0]
        link = link.split("?", 1)[0]
        return link

    def crawl_list(self, page: Page, skip_hotel_ids: Optional[set[str]] = None,
                   on_page_hotels: Optional[Callable[[List[Dict[str, Any]], int], None]] = None) -> List[Dict[str, Any]]:
        hotels = []
        seen_links = set()
        skip_hotel_ids = skip_hotel_ids or set()
        expected_total = None
        consecutive_empty_pages = 0
        max_consecutive_empty_pages = 5
        search_check_in, search_check_out = self.current_search_dates()
        logging.info("[Traveloka] Search date window: %s -> %s", search_check_in, search_check_out)

        for page_number in range(1, self.max_pages + 1):
            list_url = self.build_list_url(page_number)
            logging.info("[Traveloka] Open list page %s/%s: %s", page_number, self.max_pages, list_url)
            if not self.goto_with_retry(page, list_url):
                logging.error("[Traveloka] Unable to open list page %s.", page_number)
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= max_consecutive_empty_pages:
                    logging.warning("[Traveloka] Stop list crawl after %s consecutive failed pages.", consecutive_empty_pages)
                    break
                continue

            page_has_links = True
            try:
                page.wait_for_selector('a[href*="/hotel/"], a[href*="/accommodation/"]', timeout=30000)
            except TimeoutError:
                logging.warning("[Traveloka] No accommodation links found on list page %s.", page_number)
                page_has_links = False

            if not page_has_links:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= max_consecutive_empty_pages:
                    logging.warning("[Traveloka] Stop list crawl after %s consecutive empty pages.", consecutive_empty_pages)
                    break
                continue

            consecutive_empty_pages = 0
            self._scroll_page_to_top(page)
            page_new_hotels = []
            page.wait_for_timeout(self.list_scroll_wait_ms)

            for _ in range(self.list_scroll_passes):
                self._scroll_page_by(page, max(600, self.list_scroll_pixels // 2))
                page.wait_for_timeout(self.list_scroll_wait_ms)

            if expected_total is None:
                expected_total = self._extract_expected_total(page)
                if expected_total:
                    logging.info("[Traveloka] Expected accommodations from UI: %s", expected_total)

            stable_rounds = 0
            last_seen_count = len(seen_links)
            footer_logged = False

            for round_index in range(1, self.list_max_scroll_rounds + 1):
                links = page.locator(
                    'a[href*="/en-vn/hotel/vietnam/"], '
                    'a[href*="traveloka.com/en-vn/hotel/vietnam/"], '
                    'a[href*="/en-vn/accommodation/"], '
                    'a[href*="traveloka.com/en-vn/accommodation/"]'
                )
                count = links.count()

                for index in range(count):
                    anchor = links.nth(index)
                    try:
                        href = anchor.get_attribute("href") or ""
                        if not href or not self._is_property_detail_link(href):
                            continue

                        link = self._normalize_detail_link(href)
                        if not link or link in seen_links:
                            continue
                        seen_links.add(link)

                        name = normalize_text(anchor.inner_text(), default="N/A")
                        card_text = self._extract_card_text(anchor)
                        parsed = self._parse_list_card(card_text)
                        if name == "N/A":
                            name = normalize_text(card_text.split("\n", 1)[0], default="N/A")

                        hotel = {
                            "hotel_id": stable_hotel_id(link),
                            "name": name,
                            "price_min": parsed["price_min"],
                            "rating": parsed["rating"],
                            "review_count": parsed["review_count"],
                            "location_short": parsed["location_short"],
                            "property_type": self.detect_property_type(f"{name} {card_text}"),
                            "link": link,
                        }
                        if hotel["hotel_id"] in skip_hotel_ids:
                            continue
                        hotels.append(hotel)
                        page_new_hotels.append(hotel)
                    except Exception as exc:
                        logging.debug(f"[Traveloka] List parse error: {exc}")

                current_seen = len(seen_links)
                footer_visible = self._list_footer_visible(page)
                if footer_visible and not footer_logged:
                    logging.info("[Traveloka] Page %s reached Explore promos zone; stop deep scrolling.", page_number)
                    footer_logged = True

                if round_index == 1 or round_index % 10 == 0:
                    logging.info(
                        "[Traveloka] Page %s/%s scroll round %s | collected unique accommodations: %s",
                        page_number, self.max_pages, round_index, current_seen
                    )

                if expected_total and current_seen >= expected_total:
                    logging.info("[Traveloka] Reached expected total from UI (%s).", expected_total)
                    break

                if current_seen <= last_seen_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_seen_count = current_seen

                if round_index >= self.list_min_rounds_before_stop and stable_rounds >= self.list_max_stable_rounds:
                    logging.info("[Traveloka] Stop page %s crawl: no new links after %s rounds.", page_number, stable_rounds)
                    break

                self.click_if_present(
                    page,
                    ['button:has-text("Show more")', 'button:has-text("Load more")', 'button:has-text("See more")',
                     'button:has-text("Xem thêm")', 'button:has-text("Tải thêm")'],
                    timeout_ms=1000,
                )

                if not footer_visible:
                    self._scroll_page_by(page, self.list_scroll_pixels)
                    page.wait_for_timeout(self.list_scroll_wait_ms)
                else:
                    self._scroll_page_by(page, max(400, self.list_scroll_pixels // 5))
                    page.wait_for_timeout(max(1200, self.list_scroll_wait_ms // 2))

                random_sleep(1.0, 2.0)

            if on_page_hotels and page_new_hotels:
                try:
                    on_page_hotels(page_new_hotels, page_number)
                except Exception as exc:
                    logging.error(f"[Traveloka] Page {page_number} callback failed: {exc}")

            if expected_total and len(seen_links) >= expected_total:
                break
            if len(hotels) >= self.max_hotels:
                break

        logging.info("[Traveloka] Total unique properties from list: %s", len(hotels))
        return hotels

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

    def _page_has_verification(self, page: Page) -> bool:
        try:
            title = page.title().lower()
        except Exception:
            title = ""
        body = ""
        try:
            body = page.content().lower()
        except Exception:
            pass
        return "human verification" in title or "human verification" in body or "verify that you're not a robot" in body

    def _first_non_empty(self, values: Iterable[str], default: str = "N/A") -> str:
        for value in values:
            cleaned = normalize_text(value, default="")
            if cleaned and cleaned != "N/A":
                return cleaned
        return default

    def _collect_visible_text(self, page: Page, selectors: Iterable[str], default: str = "") -> str:
        texts = []
        for selector in selectors:
            try:
                loc = page.locator(selector)
                count = min(loc.count(), 25)
                for i in range(count):
                    try:
                        text = normalize_text(loc.nth(i).inner_text(), default="")
                        if text:
                            texts.append(text)
                    except Exception:
                        continue
            except Exception:
                continue
        combined = normalize_text("\n".join(texts), default="")
        return combined if combined else default

    def _extract_locator_texts(self, locator, max_items: int = 50) -> List[str]:
        values = []
        try:
            count = min(locator.count(), max_items)
            for i in range(count):
                try:
                    text = normalize_text(locator.nth(i).inner_text(), default="")
                    if text and text != "N/A":
                        values.append(text)
                except Exception:
                    continue
        except Exception:
            pass
        return values

    def _parse_room_block(self, text: str) -> Dict[str, Any]:
        room_name = self._extract_room_name_from_text(text)
        capacity = "N/A"
        bed_type = "N/A"
        area = "N/A"
        view = "N/A"

        area_match = re.search(r"(\d+(?:[\.,]\d+)?)\s*m²", text, flags=re.IGNORECASE)
        if area_match:
            area = clean_float(area_match.group(1)) or area

        capacity_match = re.search(r"(\d+)\s*(guest|guests|adult|adults|person|people|room\(s\))", text, flags=re.IGNORECASE)
        if capacity_match:
            capacity = capacity_match.group(1)

        for token in ["double bed", "single bed", "queen", "king", "sofa bed", "twin bed", "bunk bed"]:
            if token in text.lower():
                bed_type = token
                break

        for token in ["sea view", "city view", "garden view", "river view", "mountain view", "pool view"]:
            if token in text.lower():
                view = token
                break

        return {
            "room_name": room_name,
            "capacity": capacity,
            "bed_type": bed_type,
            "area": area,
            "view": view,
        }

    def _extract_address(self, page: Page) -> str:
        jsonlds = self._extract_jsonld(page)
        for item in jsonlds:
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    self._extract_room_name_from_text(address.get("streetAddress", "")), # fallback utility
                    address.get("addressLocality", ""),
                    address.get("addressRegion", ""),
                    address.get("addressCountry", ""),
                    address.get("postalCode", ""),
                ]
                text = ", ".join([normalize_text(p) for p in parts if p])
                if text:
                    return text
        return self.safe_locator_text(
            page,
            ['[data-testid*="address"]', '[class*="address"]', 'a[href*="map"]', 'span:has-text("Address")'],
            default="N/A"
        )

    def _extract_description(self, page: Page) -> str:
        try:
            meta = page.locator('meta[name="description"]')
            if meta.count() > 0:
                content = meta.first.get_attribute("content") or ""
                if content:
                    return normalize_text(content)
        except Exception:
            pass

        for selector in ['[data-testid*="description"]', '[class*="description"]', 'p']:
            try:
                loc = page.locator(selector)
                for i in range(min(loc.count(), 20)):
                    text = normalize_text(loc.nth(i).inner_text(), default="")
                    if len(text) > 120:
                        return text
            except Exception:
                continue
        return "N/A"

    def _extract_star_rating(self, page: Page) -> Optional[float]:
        jsonlds = self._extract_jsonld(page)
        for item in jsonlds:
            star = item.get("starRating")
            if isinstance(star, dict):
                rating = clean_float(str(star.get("ratingValue") or star.get("value")))
                if rating is not None and 0 < rating <= 5:
                    return rating
            rating = clean_float(str(item.get("starRating")))
            if rating is not None and 0 < rating <= 5:
                return rating

        star_text = self.safe_locator_text(
            page,
            ['[aria-label*="star"]', '[data-testid*="star"]', '[class*="star"]'],
            default=""
        )
        patterns = [
            r"\b(\d(?:\.\d)?)\s*[- ]?star(?:s)?\b",
            r"\b(\d(?:\.\d)?)\s*/\s*5\s*stars?\b",
            r"\b(\d(?:\.\d)?)\s+out of\s+5\s+stars?\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, star_text, flags=re.IGNORECASE)
            if match:
                rating = clean_float(match.group(1))
                if rating is not None and 0 < rating <= 5:
                    return rating
        return None

    def _extract_primary_hotel_info(self, page: Page, list_row: Dict[str, Any]) -> Dict[str, Any]:
        title = self._first_non_empty(
            [
                self.safe_locator_text(page, ['h1', 'h2', '[data-testid*="title"]'], default=""),
                list_row.get("name", ""),
            ],
            default=list_row.get("name", "N/A"),
        )

        hotel = {
            "hotel_id": list_row["hotel_id"],
            "name": title,
            "price_min": list_row.get("price_min"),
            "rating": list_row.get("rating"),
            "review_count": list_row.get("review_count"),
            "location_short": list_row.get("location_short", "Da Nang"),
            "property_type": list_row.get("property_type", "Accommodation"),
            "link": list_row.get("link", "N/A"),
            "full_address": self._extract_address(page),
            "description": self._extract_description(page),
            "star_rating": self._extract_star_rating(page),
        }

        jsonlds = self._extract_jsonld(page)
        for jd in jsonlds:
            kind = str(jd.get("@type", "")).lower()
            if kind in {"hotel", "resort", "lodgingbusiness", "hostel", "apartment", "villa"}:
                hotel["name"] = normalize_text(jd.get("name"), default=hotel["name"])
                hotel["property_type"] = self.detect_property_type(kind)
                agg = jd.get("aggregateRating", {})
                if isinstance(agg, dict):
                    hotel["rating"] = clean_float(str(agg.get("ratingValue", hotel["rating"]))) or hotel["rating"]
                    hotel["review_count"] = clean_int(str(agg.get("reviewCount", hotel["review_count"]))) or hotel["review_count"]
                star = jd.get("starRating")
                if isinstance(star, dict):
                    star_value = clean_float(str(star.get("ratingValue") or star.get("value")))
                    if star_value is not None and 0 < star_value <= 5:
                        hotel["star_rating"] = star_value
                elif star is not None:
                    star_value = clean_float(str(star))
                    if star_value is not None and 0 < star_value <= 5:
                        hotel["star_rating"] = star_value

        return hotel

    def crawl_prices(self, page: Page, hotel_id: str, room_id_by_name: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        records = []
        seen = set()
        known_room_ids = room_id_by_name or {}
        placeholder_room_ids = set()

        selectors = [
            '[data-testid="room_inventory_price_summary"]',
            '[data-testid="room_inventory_cheapest_rate"]',
            '[data-testid="selected-price-display"]',
            '[data-testid="overview_cheapest_price"]',
            '[data-testid^="room_inventory_card"]',
            '[data-testid^="room_inventory_group_card"]',
        ]

        for selector in selectors:
            try:
                blocks = page.locator(selector)
                count = blocks.count()
                if count == 0:
                    continue

                logging.info("[Traveloka] Price selector matched %s blocks via %s", count, selector)
                for i in range(count):
                    block = blocks.nth(i)
                    text = normalize_text(block.inner_text(), default="")
                    if not text or text in seen:
                        continue
                    seen.add(text)

                    chunks = self._split_room_chunks(text)
                    if not chunks:
                        chunks = [text]

                    for chunk in chunks:
                        parsed = self._parse_room_block(chunk)
                        price, currency = parse_price_and_currency(chunk)
                        if price is None:
                            continue
                        room_name = parsed["room_name"]
                        room_key = self.normalize_room_name_key(room_name)
                        room_id = known_room_ids.get(room_key) or self.stable_room_id(hotel_id, room_name)

                        if room_id not in placeholder_room_ids and room_key not in known_room_ids:
                            placeholder_room = {
                                "room_id": room_id,
                                "hotel_id": hotel_id,
                                "room_name": room_name,
                                "capacity": parsed["capacity"],
                                "bed_type": parsed["bed_type"],
                                "area": parsed["area"],
                                "view": parsed["view"],
                                "amenities_room": normalize_text(chunk, default="N/A"),
                            }
                            self.save_rooms(placeholder_room)
                            placeholder_room_ids.add(room_id)
                            known_room_ids[room_key] = room_id

                        item = {
                            "price_id": str(uuid.uuid4()),
                            "hotel_id": hotel_id,
                            "room_id": room_id,
                            "room_name": room_name,
                            "price": price,
                            "currency": currency,
                            "date": self.current_crawl_date(),
                            "is_discount": any(token in chunk.lower() for token in ["discount", "deal", "save", "promo", "exclusive"]),
                        }
                        records.append(item)
                        self.save_prices(item)
                break
            except Exception:
                continue

        return records

    def crawl_rooms(self, page: Page, hotel_id: str) -> List[Dict[str, Any]]:
        records = []
        seen = set()
        seen_room_ids = set()

        selectors = [
            '[data-testid="room-list-tray"]',
            '[data-testid="room_inventory_group_card"]',
            '[data-testid^="room_inventory_group_card"]',
            '[data-testid="room_inventory_card"]',
            '[data-testid^="room_inventory_card"]',
        ]

        for selector in selectors:
            try:
                blocks = page.locator(selector)
                count = blocks.count()
                if count == 0:
                    continue

                logging.info("[Traveloka] Room selector matched %s blocks via %s", count, selector)
                for i in range(count):
                    block = blocks.nth(i)
                    text = normalize_text(block.inner_text(), default="")
                    if not text or text in seen:
                        continue
                    seen.add(text)

                    chunks = self._split_room_chunks(text)
                    if not chunks:
                        chunks = [text]

                    for chunk in chunks:
                        parsed = self._parse_room_block(chunk)
                        if parsed["room_name"] == "N/A" and len(normalize_text(chunk, default="")) < 10:
                            continue
                        room_id = self.stable_room_id(hotel_id, parsed["room_name"])
                        if room_id in seen_room_ids:
                            continue
                        seen_room_ids.add(room_id)
                        item = {
                            "room_id": room_id,
                            "hotel_id": hotel_id,
                            "room_name": parsed["room_name"],
                            "capacity": parsed["capacity"],
                            "bed_type": parsed["bed_type"],
                            "area": parsed["area"],
                            "view": parsed["view"],
                            "amenities_room": chunk,
                        }
                        records.append(item)
                        self.save_rooms(item)
                break
            except Exception:
                continue

        return records

    def crawl_policies(self, page: Page, hotel_id: str) -> List[Dict[str, Any]]:
        text = self._collect_visible_text(
            page,
            ['[data-testid="section-policy"]', '[data-testid^="section-policy"]', '[data-testid*="policy"]',
             '[data-testid="text_cancellation_policy"]', 'section:has-text("Check-in")', 'section:has-text("Check-out")',
             'section:has-text("Children")', 'section:has-text("Pets")'],
            default=""
        )
        if not text:
            try:
                text = normalize_text(page.locator("body").inner_text(), default="")
            except:
                text = ""

        records = []
        for policy in self._policy_rows_from_text(text):
            item = {
                "policy_id": str(uuid.uuid4()),
                "hotel_id": hotel_id,
                "policy_type": policy["policy_type"],
                "policy_value": policy["policy_value"],
            }
            records.append(item)
            self.save_policies(item)

        return records

    def crawl_images(self, page: Page, hotel_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        records = []
        seen = set()
        try:
            imgs = page.locator('img')
            for i in range(min(imgs.count(), 250)):
                try:
                    src = imgs.nth(i).get_attribute("src") or imgs.nth(i).get_attribute("data-src") or ""
                    src = normalize_text(src, default="")
                    if not src or src in seen or not src.startswith("http"):
                        continue
                    seen.add(src)
                    item = {
                        "image_id": str(uuid.uuid4()),
                        "hotel_id": hotel_id,
                        "image_url": src,
                    }
                    records.append(item)
                    self.save_images(item)
                    if len(records) >= limit:
                        break
                except Exception:
                    continue
        except Exception:
            pass
        return records

    def crawl_reviews(self, page: Page, hotel_id: str, min_reviews: int = 20) -> List[Dict[str, Any]]:
        records = []
        seen = set()
        no_growth_rounds = 0
        max_no_growth_rounds = 4
        target_reviews = max(min_reviews, 1)

        review_click_selectors = [
            '[data-testid="link-REVIEW"]', '[data-testid="review-data-title"]', 'a:has-text("Reviews")',
            'button:has-text("Reviews")', 'a:has-text("See all reviews")', 'button:has-text("See all reviews")',
        ]

        self.click_if_present(page, review_click_selectors)
        page.wait_for_timeout(self.section_settle_wait_ms)

        try:
            review_section = page.locator('[data-testid="section-review-summary"], [data-testid="review-list-container"]')
            if review_section.count() > 0:
                review_section.first.scroll_into_view_if_needed()
                page.wait_for_timeout(self.section_settle_wait_ms)
        except Exception:
            pass

        for _ in range(self.max_review_pages):
            before_round_count = len(records)
            try:
                page.wait_for_timeout(self.review_round_wait_ms)
                review_blocks = page.locator('[data-testid^="summary-review-item-"], [data-testid="review-list-container"], [data-testid="summary-review-list"]')
                count = review_blocks.count()
                if count == 0:
                    review_blocks = page.locator('[data-testid="summary-review-ugc"], [data-testid="summary-review-list"]')
                    count = review_blocks.count()

                for i in range(min(count, 200)):
                    block = review_blocks.nth(i)
                    try:
                        text = normalize_text(block.inner_text(), default="")
                    except Exception:
                        continue
                    if not text or text in seen:
                        continue
                    if len(text) < 25:
                        continue

                    chunks = self._split_review_chunks(text)
                    if not chunks:
                        chunks = [text]

                    for chunk in chunks:
                        parsed = self._extract_review_from_chunk(chunk)
                        if parsed["review_text"] in seen:
                            continue
                        if parsed["review_text"] == "N/A" and parsed["reviewer_name"] == "N/A":
                            continue
                        if parsed["review_text"] == "N/A":
                            continue

                        review_date = normalize_text(parsed.get("review_date"), default="")
                        if not review_date or review_date == "N/A":
                            review_date = self.current_crawl_date()

                        item = {
                            "review_id": str(uuid.uuid4()),
                            "hotel_id": hotel_id,
                            "reviewer_name": parsed["reviewer_name"],
                            "review_text": parsed["review_text"],
                            "review_rating": parsed["review_rating"],
                            "review_date": review_date,
                            "helpful_count": parsed.get("helpful_count"),
                        }
                        seen.add(parsed["review_text"])
                        records.append(item)
                        self.save_reviews(item)
                        if len(records) >= target_reviews:
                            return records

                self.click_if_present(
                    page,
                    ['button:has-text("See all reviews")', 'button:has-text("Load more")', 'button:has-text("Show more")',
                     'button:has-text("Xem thêm")', 'button:has-text("Tải thêm")'],
                    timeout_ms=1500,
                )
                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(self.section_settle_wait_ms)

                if len(records) <= before_round_count:
                    no_growth_rounds += 1
                else:
                    no_growth_rounds = 0

                if no_growth_rounds >= max_no_growth_rounds:
                    break
            except TimeoutError:
                break
            except Exception:
                break

        return records

    def _detail_has_no_availability(self, page: Page) -> bool:
        text_fragments = []
        selectors = [
            '[data-testid*="sold"]', '[data-testid*="availability"]', 'text=Sold out', 'text=No rooms available',
            'text=Out of rooms', 'text=Unavailable', 'text=Hết phòng', 'text=Không còn phòng', 'text=Đã hết phòng',
        ]

        for selector in selectors:
            try:
                loc = page.locator(selector)
                count = min(loc.count(), 6)
                for idx in range(count):
                    text_fragments.append(normalize_text(loc.nth(idx).inner_text(), default=""))
            except Exception:
                continue

        try:
            body_text = normalize_text(page.locator("body").inner_text(), default="")
            if body_text:
                text_fragments.append(body_text[:4500])
        except Exception:
            pass

        haystack = " ".join([fragment for fragment in text_fragments if fragment]).lower()
        if not haystack:
            return False

        keywords = ["sold out", "no rooms available", "out of rooms", "fully booked", "unavailable",
                    "hết phòng", "không còn phòng", "đã hết phòng"]
        return any(keyword in haystack for keyword in keywords)

    def crawl_detail(self, context, item_from_list: Dict[str, Any]) -> bool:
        detail_page = context.new_page()
        link = item_from_list["link"]
        hotel_id = item_from_list["hotel_id"]

        try:
            if not self.goto_with_retry(detail_page, link):
                logging.error(f"[Traveloka] Skip detail due to repeated timeout: {link}")
                return False

            if self._page_has_verification(detail_page):
                logging.warning(f"[Traveloka] Verification page detected for {link}")
                return False

            detail_page.wait_for_timeout(self.detail_load_wait_ms)
            if self._detail_has_no_availability(detail_page):
                logging.info(f"[Traveloka] Skip sold-out/unavailable hotel quickly: {link}")
                return True

            self.click_if_present(detail_page, ['[data-testid="overview_select_room_button"]', '[data-testid="link-ROOMS"]'])
            try:
                room_section = detail_page.locator('[data-testid="section-room-search"], [data-testid="room-list-tray"]')
                if room_section.count() > 0:
                    room_section.first.scroll_into_view_if_needed()
                    detail_page.wait_for_timeout(self.section_settle_wait_ms)
            except Exception:
                pass

            self.click_if_present(detail_page, ['[data-testid="link-REVIEW"]'])
            try:
                review_section = detail_page.locator('[data-testid="section-review-summary"], [data-testid="review-list-container"]')
                if review_section.count() > 0:
                    review_section.first.scroll_into_view_if_needed()
                    detail_page.wait_for_timeout(self.section_settle_wait_ms)
            except Exception:
                pass

            hotel_row = self._extract_primary_hotel_info(detail_page, item_from_list)
            self.save_hotels(hotel_row)

            room_records = self.crawl_rooms(detail_page, hotel_id)
            room_id_by_name = {
                self.normalize_room_name_key(room.get("room_name", "N/A")): room["room_id"]
                for room in room_records
                if room.get("room_id")
            }

            price_records = self.crawl_prices(detail_page, hotel_id, room_id_by_name=room_id_by_name)
            if not room_records and not price_records:
                logging.info(f"[Traveloka] Skip heavy sections due to missing room/price data: {link}")
                random_sleep(0.4, 1.0)
                return True

            self.crawl_policies(detail_page, hotel_id)
            self.crawl_images(detail_page, hotel_id)
            self.crawl_reviews(detail_page, hotel_id, min_reviews=self.min_reviews)

            logging.info(f"✅ [Traveloka] Saved detail package for {hotel_id} | {hotel_row.get('name')}")
            random_sleep(0.8, 1.8)
            return True

        except Exception as exc:
            logging.error(f"[Traveloka] Detail crawl failed for {link}: {exc}")
            return False
        finally:
            detail_page.close()

    def run(self) -> None:
        logging.info("[Traveloka] Starting Traveloka crawler...")
        self.init_outputs(reset=self.reset_outputs)
        done_hotel_ids = self.load_done_hotel_ids_from_checkpoint() if self.resume_crawl else set()
        
        if done_hotel_ids:
            logging.info(f"[Traveloka] Checkpoint loaded: {len(done_hotel_ids)} completed hotels")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent=random.choice(self.user_agents),
                viewport={"width": 1440, "height": 1080},
                locale="en-US",
                java_script_enabled=True,
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            page = context.new_page()

            try:
                if self.stream_detail_during_list:
                    processed_counter = {"count": 0}

                    def _process_page_hotels(page_hotels: List[Dict[str, Any]], page_number: int) -> None:
                        total_on_page = len(page_hotels)
                        logging.info(f"[Traveloka] Page {page_number} produced {total_on_page} new hotels; starting detail crawl.")
                        for offset, hotel in enumerate(page_hotels, 1):
                            processed_counter["count"] += 1
                            logging.info(
                                f"[Traveloka] [page {page_number} | {offset}/{total_on_page} | total_processed={processed_counter['count']}] Crawl detail: {hotel['link']}"
                            )
                            success = self.crawl_detail(context, hotel)
                            if success and self.resume_crawl:
                                self.save_checkpoint_done(hotel, reason="processed_or_skipped")
                                done_hotel_ids.add(hotel["hotel_id"])
                            if processed_counter["count"] >= self.max_hotels:
                                break

                    hotels = self.crawl_list(
                        page,
                        skip_hotel_ids=done_hotel_ids if self.resume_crawl else None,
                        on_page_hotels=_process_page_hotels,
                    )
                    logging.info(f"[Traveloka] Total list records: {len(hotels)} | total streamed details: {processed_counter['count']}")
                else:
                    hotels = self.crawl_list(page, skip_hotel_ids=done_hotel_ids if self.resume_crawl else None)
                    logging.info(f"[Traveloka] Total list records: {len(hotels)}")
                    for idx, hotel in enumerate(hotels, 1):
                        if self.resume_crawl and hotel["hotel_id"] in done_hotel_ids:
                            logging.info(f"[Traveloka] [{idx}/{len(hotels)}] Skip completed: {hotel['link']}")
                            continue
                        logging.info(f"[Traveloka] [{idx}/{len(hotels)}] Crawl detail: {hotel['link']}")
                        success = self.crawl_detail(context, hotel)
                        if success and self.resume_crawl:
                            self.save_checkpoint_done(hotel, reason="processed_or_skipped")
                            done_hotel_ids.add(hotel["hotel_id"])
                        if idx >= self.max_hotels:
                            break
            except Exception as exc:
                logging.error(f"[Traveloka] Fatal error in main: {exc}")
            finally:
                browser.close()
                logging.info("[Traveloka] Crawler finished.")


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
    parser = argparse.ArgumentParser(description="Unified Crawler Orchestrator for Traveloka & Booking.com")
    parser.add_argument("--source", choices=["all", "traveloka", "booking"], default="all",
                        help="Choose which crawl source to execute (default: all)")
    parser.add_argument("--city", default="Da Nang", help="City keyword to search for Booking.com (default: Da Nang)")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run browser with visual interface")
    parser.set_defaults(headless=True)
    
    # Platform specific limits
    parser.add_argument("--max-pages", type=int, default=None, 
                        help="Override maximum list pages to crawl (Default: Traveloka=114, Booking=2)")
    parser.add_argument("--max-results", type=int, default=None,
                        help="Override maximum properties/hotels to crawl (Default: Traveloka=5000, Booking=50)")
    parser.add_argument("--reviews-limit", type=int, default=None,
                        help="Override reviews cào per property (Default: Traveloka=20, Booking=10)")

    args = parser.parse_args()

    logging.info(f"Starting unified crawler pipeline with config: {vars(args)}")

    sources_to_run = []
    if args.source == "all":
        sources_to_run = ["traveloka", "booking"]
    else:
        sources_to_run = [args.source]

    for source in sources_to_run:
        if source == "traveloka":
            max_pages = args.max_pages if args.max_pages is not None else 114
            max_hotels = args.max_results if args.max_results is not None else 5000
            min_reviews = args.reviews_limit if args.reviews_limit is not None else 20
            
            engine = TravelokaCrawlerEngine(
                headless=args.headless,
                max_pages=max_pages,
                max_hotels=max_hotels,
                min_reviews=min_reviews
            )
            try:
                engine.run()
            except Exception as e:
                logging.error(f"Traveloka crawler pipeline failed: {e}", exc_info=True)

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
