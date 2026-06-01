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

# HuggingFace LLM (Qwen3.5-4B via Transformers)
LLM_HF_MODEL_NAME: str = os.getenv("LLM_HF_MODEL_NAME", "Qwen/Qwen3.5-4B")

# llama.cpp GGUF (legacy — không dùng nữa, giữ để không break .env cũ)
LLM_GGUF_PATH: str = os.getenv("LLM_GGUF_PATH", "models/qwen2.5-3b-instruct-q4_k_m.gguf")
LLM_N_CTX: int = int(os.getenv("LLM_N_CTX", "4096"))
LLM_N_GPU_LAYERS: int = int(os.getenv("LLM_N_GPU_LAYERS", "-1"))

# HuggingFace
HF_TOKEN: str | None = os.getenv("HF_TOKEN")
if HF_TOKEN:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

# Database
DB_PATH: str = os.getenv("DB_PATH", "data/chats.db")

# Generation defaults
DEFAULT_MAX_TOKENS: int = int(os.getenv("DEFAULT_MAX_TOKENS", "512"))
DEFAULT_TEMPERATURE: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.2"))
DEFAULT_TOP_K: int = int(os.getenv("DEFAULT_TOP_K", "5"))
SCORE_THRESHOLD: float = float(os.getenv("SCORE_THRESHOLD", "0.3"))
MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "5"))

# 4-bit quantization (giảm VRAM, tăng tốc generation ~30-50%)
LLM_LOAD_IN_4BIT: bool = os.getenv("LLM_LOAD_IN_4BIT", "false").lower() in ("1", "true", "yes")

# Model nhỏ riêng cho analyzer (default Qwen2.5-0.5B thay vì 4B → analyzer ~0.5s)
ANALYZER_HF_MODEL_NAME: str = os.getenv("ANALYZER_HF_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")

# Gemini fallback — khi Qdrant retrieve trả 0 kết quả, gọi Gemini thay vì local LLM.
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_BASE_URL: str = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)
GEMINI_TIMEOUT_SECONDS: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
GEMINI_FALLBACK_PREFIX_DISCLAIMER: bool = (
    os.getenv("GEMINI_FALLBACK_PREFIX_DISCLAIMER", "true").lower() in ("1", "true", "yes")
)
# Gemini làm primary generator (auto-enable khi có API key, tắt bằng USE_GEMINI_GENERATION=false)
USE_GEMINI_GENERATION: bool = (
    os.getenv("USE_GEMINI_GENERATION", "true").lower() in ("1", "true", "yes")
    and bool(GEMINI_API_KEY)
)

# Event crawler (SerpAPI). Crawler chạy định kỳ trong lifespan,
# upsert vào bảng `events` của SQLite. Empty key = crawler bị skip.
SERPAPI_KEY: str = os.getenv("SERPAPI_KEY", "")
CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))
DEFAULT_RADIUS_KM: int = int(os.getenv("DEFAULT_RADIUS_KM", "30"))
DEFAULT_EVENT_DAYS: int = int(os.getenv("DEFAULT_EVENT_DAYS", "7"))
DEFAULT_EVENT_LIMIT: int = int(os.getenv("DEFAULT_EVENT_LIMIT", "50"))
# Bảo vệ POST /api/admin/crawl/events. Empty = endpoint bị disable.
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

# Reranker — BGE cross-encoder để rerank sau vector search.
RERANKER_MODEL_NAME: str = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
TOP_K_RETRIEVE: int = int(os.getenv("TOP_K_RETRIEVE", "15"))
TOP_K_RERANK: int = int(os.getenv("TOP_K_RERANK", "5"))
RERANK_SCORE_THRESHOLD: float = float(os.getenv("RERANK_SCORE_THRESHOLD", "0.3"))

# Place crawler — crawl địa điểm từ missed_queries và cập nhật định kỳ.
PLACE_CRAWL_INTERVAL_HOURS: int = int(os.getenv("PLACE_CRAWL_INTERVAL_HOURS", "4"))
NEW_PLACES_CRAWL_INTERVAL_HOURS: int = int(os.getenv("NEW_PLACES_CRAWL_INTERVAL_HOURS", "24"))
MAX_PLACE_RETRY: int = int(os.getenv("MAX_PLACE_RETRY", "3"))
PLACE_CRAWL_BATCH: int = int(os.getenv("PLACE_CRAWL_BATCH", "10"))
