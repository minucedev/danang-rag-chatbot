from enum import Enum
from app.utils.nfc import normalize_nfc
from app import config


class QueryIntent(Enum):
    HOTEL_SEARCH = "hotel_search"
    RESTAURANT_SEARCH = "restaurant_search"
    PLACE_SEARCH = "place_search"
    REVIEW_SEARCH = "review_search"
    ROOM_SEARCH = "room_search"
    PRICE_SEARCH = "price_search"
    GENERAL = "general"

    @classmethod
    def detect(cls, query: str) -> "QueryIntent":
        q = normalize_nfc(query).lower()

        # Entity type keywords take priority over review/price keywords
        # e.g. "khách sạn có đánh giá tốt" → HOTEL not REVIEW
        if any(k in q for k in ["khách sạn", "hotel", "resort", "nghỉ dưỡng", "lưu trú"]):
            return cls.HOTEL_SEARCH
        if any(k in q for k in ["nhà hàng", "restaurant", "quán ăn", "ăn uống", "hải sản"]):
            return cls.RESTAURANT_SEARCH
        if any(k in q for k in ["địa điểm", "thắng cảnh", "tham quan", "du lịch", "bãi biển"]):
            return cls.PLACE_SEARCH
        if any(k in q for k in ["phòng", "room", "giường", "sức chứa", "capacity"]):
            return cls.ROOM_SEARCH
        if any(k in q for k in ["review", "đánh giá", "nhận xét", "comment", "chất lượng"]):
            return cls.REVIEW_SEARCH
        if any(k in q for k in ["giá", "price", "bao nhiêu", "chi phí", "budget"]):
            return cls.PRICE_SEARCH
        return cls.GENERAL

    @property
    def display(self) -> str:
        _map = {
            "hotel_search": "Khách sạn",
            "restaurant_search": "Nhà hàng",
            "place_search": "Địa điểm",
            "review_search": "Đánh giá",
            "room_search": "Phòng",
            "price_search": "Giá",
            "general": "Tổng quát",
        }
        return _map[self.value]


class CollectionRegistry:
    COLLECTIONS = {
        config.COLLECTION_PLACES: {
            "weight": 1.2,
            "priority_for_intent": {
                QueryIntent.PLACE_SEARCH: 1.5,
                QueryIntent.GENERAL: 1.2,
            },
        },
        config.COLLECTION_RESTAURANTS: {
            "weight": 1.2,
            "priority_for_intent": {
                QueryIntent.RESTAURANT_SEARCH: 1.5,
                QueryIntent.GENERAL: 1.2,
            },
        },
        config.COLLECTION_ACCOMMODATION_HOTELS: {
            "weight": 1.3,
            "priority_for_intent": {
                QueryIntent.HOTEL_SEARCH: 1.6,
                QueryIntent.ROOM_SEARCH: 1.4,
                QueryIntent.PRICE_SEARCH: 1.3,
                QueryIntent.GENERAL: 1.3,
            },
        },
        config.COLLECTION_PLACE_REVIEWS: {
            "weight": 1.0,
            "priority_for_intent": {QueryIntent.REVIEW_SEARCH: 1.6},
        },
        config.COLLECTION_RESTAURANT_REVIEWS: {
            "weight": 1.0,
            "priority_for_intent": {QueryIntent.REVIEW_SEARCH: 1.6},
        },
        config.COLLECTION_ACCOMMODATION_REVIEWS: {
            "weight": 1.0,
            "priority_for_intent": {QueryIntent.REVIEW_SEARCH: 1.6},
        },
        config.COLLECTION_ACCOMMODATION_ROOMS: {
            "weight": 0.95,
            "priority_for_intent": {QueryIntent.ROOM_SEARCH: 1.8},
        },
    }

    @classmethod
    def get_collections_by_intent(cls, intent: QueryIntent) -> list[str]:
        if intent == QueryIntent.HOTEL_SEARCH:
            return [
                config.COLLECTION_ACCOMMODATION_HOTELS,
                config.COLLECTION_ACCOMMODATION_REVIEWS,
                config.COLLECTION_ACCOMMODATION_ROOMS,
            ]
        if intent == QueryIntent.RESTAURANT_SEARCH:
            return [config.COLLECTION_RESTAURANTS, config.COLLECTION_RESTAURANT_REVIEWS]
        if intent == QueryIntent.PLACE_SEARCH:
            return [config.COLLECTION_PLACES, config.COLLECTION_PLACE_REVIEWS]
        if intent == QueryIntent.REVIEW_SEARCH:
            return [
                config.COLLECTION_PLACE_REVIEWS,
                config.COLLECTION_RESTAURANT_REVIEWS,
                config.COLLECTION_ACCOMMODATION_REVIEWS,
            ]
        if intent == QueryIntent.ROOM_SEARCH:
            return [
                config.COLLECTION_ACCOMMODATION_ROOMS,
                config.COLLECTION_ACCOMMODATION_HOTELS,
                config.COLLECTION_ACCOMMODATION_REVIEWS,
            ]
        if intent == QueryIntent.PRICE_SEARCH:
            return [config.COLLECTION_ACCOMMODATION_HOTELS, config.COLLECTION_RESTAURANTS]
        # GENERAL
        return [
            config.COLLECTION_ACCOMMODATION_HOTELS,
            config.COLLECTION_RESTAURANTS,
            config.COLLECTION_PLACES,
        ]

    @classmethod
    def get_weight(cls, collection: str, intent: QueryIntent) -> float:
        cfg = cls.COLLECTIONS.get(collection, {"weight": 1.0})
        base = cfg["weight"]
        priority = cfg.get("priority_for_intent", {}).get(intent, 1.0)
        return base * priority
