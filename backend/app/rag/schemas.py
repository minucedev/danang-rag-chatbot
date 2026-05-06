from __future__ import annotations
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from app import config


class ChatFilters(BaseModel):
    district: Optional[str] = None
    min_rating: Optional[float] = None
    max_price: Optional[float] = None


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
