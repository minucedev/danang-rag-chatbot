import os
from dotenv import load_dotenv

load_dotenv()

# Qdrant
QDRANT_URL: str = os.environ["QDRANT_URL"]
QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")

# Collections
COLLECTION_PLACES = "places_danang"
COLLECTION_PLACE_REVIEWS = "place_reviews_danang"
COLLECTION_RESTAURANTS = "restaurants_danang"
COLLECTION_RESTAURANT_REVIEWS = "restaurant_reviews_danang"
COLLECTION_ACCOMMODATION_HOTELS = "accommodation_hotels_danang"
COLLECTION_ACCOMMODATION_ROOMS = "accommodation_rooms_danang"
COLLECTION_ACCOMMODATION_REVIEWS = "accommodation_reviews_danang"

ALL_COLLECTIONS = [
    COLLECTION_PLACES,
    COLLECTION_PLACE_REVIEWS,
    COLLECTION_RESTAURANTS,
    COLLECTION_RESTAURANT_REVIEWS,
    COLLECTION_ACCOMMODATION_HOTELS,
    COLLECTION_ACCOMMODATION_ROOMS,
    COLLECTION_ACCOMMODATION_REVIEWS,
]

# Models
EMBED_MODEL_NAME: str = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "Qwen/Qwen2.5-3B-Instruct")
USE_4BIT: bool = os.getenv("USE_4BIT", "true").lower() == "true"

# HuggingFace
HF_TOKEN: str | None = os.getenv("HF_TOKEN")
if HF_TOKEN:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

# Database
DB_PATH: str = os.getenv("DB_PATH", "data/chats.db")

# Generation defaults
DEFAULT_MAX_TOKENS: int = int(os.getenv("DEFAULT_MAX_TOKENS", "512"))
DEFAULT_TEMPERATURE: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.3"))
DEFAULT_TOP_K: int = int(os.getenv("DEFAULT_TOP_K", "5"))
SCORE_THRESHOLD: float = float(os.getenv("SCORE_THRESHOLD", "0.3"))
MAX_HISTORY_TURNS: int = 3
