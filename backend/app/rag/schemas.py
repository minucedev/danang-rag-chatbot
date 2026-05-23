from __future__ import annotations
from datetime import date
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from app import config


class ChatFilters(BaseModel):
    district: Optional[str] = None
    min_rating: Optional[float] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    filters: Optional[ChatFilters] = None


class SearchResultSchema(BaseModel):
    point_id: str
    collection: str
    score: float
    entity_name: str = ""
    place_name: str = ""
    district: str = ""
    rating: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    address: str = ""
    content: str = ""
    parent_entity_name: Optional[str] = None
    parent_entity_id: Optional[str] = None
    parent_rating: Optional[float] = None
    parent_address: Optional[str] = None
    room_name: Optional[str] = None
    capacity: Optional[int] = None
    bed_type: Optional[str] = None
    area_m2: Optional[float] = None
    room_view: Optional[str] = None
    cuisine: Optional[str] = None
    restaurant_type: Optional[str] = None
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    time_open: Optional[str] = None
    time_close: Optional[str] = None
    tags: Optional[List[str]] = None
    review_count: Optional[int] = None
    star_rating: Optional[float] = None
    price_level: Optional[str] = None
    price_currency: Optional[str] = None

    _REVIEW_COLLECTIONS = {
        config.COLLECTION_ACCOMMODATION_REVIEWS,
        config.COLLECTION_RESTAURANT_REVIEWS,
        config.COLLECTION_PLACE_REVIEWS,
    }

    def get_display_name(self) -> str:
        if self.collection in self._REVIEW_COLLECTIONS:
            for name in (self.parent_entity_name, self.entity_name, self.place_name):
                if name and name not in ("None", "", "null"):
                    return name
            return "Đang cập nhật"
        for name in (self.entity_name, self.place_name):
            if name and name not in ("None", "", "null"):
                return name
        return "Unknown"

    def get_price_display(self) -> str:
        if self.min_price is None:
            return "Không có thông tin giá"
        if self.max_price and self.max_price > self.min_price:
            return f"{self.min_price:,.0f} - {self.max_price:,.0f} VND"
        return f"{self.min_price:,.0f} VND"

    def get_rating_display(self) -> str:
        rating_value = self.parent_rating if self.parent_rating else self.rating
        if rating_value is None:
            return "Chưa có đánh giá"
        if self.review_count and self.review_count > 0:
            return f"{rating_value:.1f}/10 ({self.review_count:,} đánh giá)"
        return f"{rating_value:.1f}/10"

    def get_address_display(self) -> str:
        if self.collection in self._REVIEW_COLLECTIONS:
            if self.parent_address and self.parent_address not in ("None", "", "null"):
                return self.parent_address
        if self.address and self.address not in ("None", "", "null"):
            return self.address
        return "Chưa có địa chỉ"

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class MessageEntity(BaseModel):
    id: int
    session_id: str
    role: str  # 'user' | 'assistant'
    content: str
    sources: Optional[List[dict]] = None
    intent: Optional[str] = None
    created_at: int


class SessionEntity(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int


# ─── Recommend / user profile (ported from PBL_ lấy dữ liệu) ───────────────

Interest = Literal[
    "beach", "food", "cafe", "culture", "nightlife", "family", "adventure", "shopping"
]
Companions = Literal["solo", "couple", "family", "friends", "business"]
BudgetLevel = Literal["low", "mid", "high"]
Language = Literal["vi", "en"]

# Mỗi model "user-facing" mới đều dùng cùng config: nhận camelCase từ frontend (PBL
# convention) hoặc snake_case (legacy), và serialize ra camelCase khi route có
# `response_model_by_alias=True`. Không áp lên ChatRequest/SessionEntity/SearchResultSchema
# để giữ tương thích cho chat.py + sessions API hiện có.
_CAMEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TripDates(BaseModel):
    model_config = _CAMEL_CONFIG

    start: date
    end: date

    @model_validator(mode="after")
    def _check_order(self):
        if self.end < self.start:
            raise ValueError("trip_dates.end must be >= trip_dates.start")
        return self

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days + 1


class UserProfile(BaseModel):
    model_config = _CAMEL_CONFIG

    display_name: Optional[str] = Field(None, max_length=80)
    trip_dates: Optional[TripDates] = None
    duration_days: Optional[int] = Field(None, gt=0, le=60)
    companions: Optional[Companions] = None
    budget_level: Optional[BudgetLevel] = None
    interests: List[Interest] = Field(default_factory=list)
    dietary: Optional[str] = Field(None, max_length=200)
    language: Language = "vi"

    @model_validator(mode="after")
    def _reconcile_duration(self):
        # Nếu cả `trip_dates` và `duration_days` đều có nhưng lệch → trip_dates thắng
        # (1 source of truth), ghi đè duration_days cho khớp.
        if self.trip_dates and self.duration_days:
            actual = self.trip_dates.length_days
            if actual != self.duration_days:
                self.duration_days = actual
        return self


class RecommendRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    session_id: str
    limit: int = Field(10, gt=0, le=50)
    district: Optional[str] = None
    include_hotels: bool = False


class RecommendItem(BaseModel):
    """View model phẳng cho recommend response — KHÔNG expose SearchResultSchema
    để mọi thay đổi internal schema không thành breaking change cho API."""

    model_config = _CAMEL_CONFIG

    place_id: str
    name: str
    collection: str
    district: str = ""
    rating: Optional[float] = None
    rating_display: str = ""
    price_display: str = ""
    address: str = ""
    recommend_score: float = Field(..., ge=0.0, le=1.0)
    matched_interests: List[Interest] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    model_config = _CAMEL_CONFIG

    items: List[RecommendItem]
    profile_used: UserProfile
    relaxed: bool = False
    notes: List[str] = Field(default_factory=list)
