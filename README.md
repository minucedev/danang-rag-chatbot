# Da Nang Travel Chatbot — PBL7

Chatbot du lịch Đà Nẵng sử dụng RAG pipeline: phân tích câu hỏi bằng LLM, tìm kiếm vector trong Qdrant (7 collections khách sạn / nhà hàng / địa điểm), rerank bằng BGE cross-encoder, rồi trả lời streaming qua FastAPI + Next.js. Hỗ trợ multi-turn conversation, profile cá nhân hóa, crawl sự kiện + địa điểm tự động.

---

## Kiến trúc

```text
Browser (http://localhost:3000)
        │
        │ HTTP + SSE streaming
        ▼
FastAPI (http://localhost:8000)
  ├─ POST /api/chat/stream              chat streaming (SSE)
  ├─ GET/POST/PATCH/DELETE /api/sessions lịch sử hội thoại
  ├─ GET/PUT/DELETE /api/profile        profile theo session
  ├─ POST /api/recommend                gợi ý theo profile
  ├─ POST /api/admin/crawl/*            trigger crawl thủ công
  └─ GET /api/health                    health check
        │
        ├─ BAAI/bge-m3                  embedding (truy vấn vector)
        ├─ BAAI/bge-reranker-v2-m3      cross-encoder reranker
        ├─ Qwen2.5-3B GGUF (llama.cpp)  analyzer + answer LLM
        ├─ Qdrant Cloud                 vector DB, 7 collections
        ├─ SQLite local                 sessions, messages, profiles,
        │                               events, missed_queries, session_context
        ├─ Gemini 2.0 Flash (tuỳ chọn) fallback khi Qdrant không có kết quả
        └─ APScheduler                  3 background jobs (events + places)
```

**RAG pipeline per query:**

```
Câu hỏi
  → NFC normalize + query enrichment (history)
  → LLMQueryAnalyzer  → intent + rewritten_query + filters
  → [CHITCHAT] → trả lời trực tiếp, bỏ qua Qdrant
  → [EVENT_SEARCH] → query SQLite events
  → retrieve_by_intent() → Qdrant vector search (TOP_K_RETRIEVE=15/collection)
  → BGE reranker → TOP_K_RERANK=5 kết quả tốt nhất
  → [SPECIFIC_SEARCH miss] → exact name fallback (Qdrant scroll + MatchText)
  → LLM generate → stream tokens → SSE done
  → [0 results + GEMINI_API_KEY] → Gemini fallback streaming
```

---

## Yêu Cầu Hệ Thống

| Thành phần | Bắt buộc | Ghi chú |
|------------|----------|---------|
| Node.js | 20+ | Frontend Next.js 16 |
| npm | Có | Đi kèm Node.js |
| Python | 3.10 hoặc 3.11 | Tránh 3.12+ nếu dùng package CUDA |
| GPU NVIDIA + driver | Khuyến nghị | ≥6GB VRAM để chạy đủ 2 model (bge-m3 + reranker + Qwen); CPU fallback chậm hơn |
| CUDA 12.1 | Khuyến nghị | Dùng wheel PyTorch CUDA 12.1 |
| Qdrant Cloud | Có | URL + API key, 7 collections đã được import |
| Model GGUF | Có | Mặc định: `backend/models/qwen2.5-3b-instruct-q4_k_m.gguf` |
| Disk trống | ~15GB | Embedding cache HuggingFace, GGUF, Python packages |

Kiểm tra môi trường:

```powershell
node --version    # 20+
npm --version
python --version  # 3.10 hoặc 3.11
nvidia-smi        # NVIDIA GPU driver
```

---

## Chạy Nhanh Frontend

Frontend không cần GPU và có thể chạy khi backend chưa lên.

```powershell
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`. Nếu gửi tin nhắn khi backend chưa chạy, UI sẽ báo lỗi kết nối API.

---

## Chạy Full Stack

### 1. Cấu hình backend

```powershell
copy backend\.env.example backend\.env
```

Chỉnh sửa `backend/.env`:

```env
# === BẮT BUỘC ===
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key

# === MODELS ===
HF_TOKEN=your-huggingface-token        # tránh rate limit khi tải bge-m3
LLM_GGUF_PATH=models/qwen2.5-3b-instruct-q4_k_m.gguf
LLM_N_CTX=4096
LLM_N_GPU_LAYERS=-1                    # -1 = đẩy tất cả lên GPU

EMBED_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-m3

# === RETRIEVAL ===
TOP_K_RETRIEVE=15        # số kết quả lấy từ Qdrant trước rerank
TOP_K_RERANK=5           # số kết quả sau rerank
RERANK_SCORE_THRESHOLD=0.3
SCORE_THRESHOLD=0.3      # ngưỡng similarity Qdrant
DEFAULT_TOP_K=5          # top-k cho các path không dùng reranker

# === GENERATION ===
DEFAULT_MAX_TOKENS=512
DEFAULT_TEMPERATURE=0.2
MAX_HISTORY_TURNS=5      # số lượt hội thoại giữ làm context

# === DATABASE ===
DB_PATH=data/chats.db

# === GEMINI FALLBACK (tuỳ chọn) ===
# Bật khi Qdrant trả 0 kết quả. Để trống = tắt.
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
GEMINI_FALLBACK_PREFIX_DISCLAIMER=true

# === EVENT CRAWLER (SerpAPI, tuỳ chọn) ===
SERPAPI_KEY=             # để trống = tắt crawler
CACHE_TTL_HOURS=24
DEFAULT_EVENT_DAYS=7
DEFAULT_LIMIT=50

# === PLACE CRAWLER (tuỳ chọn, cần SERPAPI_KEY) ===
PLACE_CRAWL_INTERVAL_HOURS=4       # crawl missed queries mỗi 4h
NEW_PLACES_CRAWL_INTERVAL_HOURS=24 # crawl địa điểm mới mỗi 24h
MAX_PLACE_RETRY=3
PLACE_CRAWL_BATCH=10

# === ADMIN ===
ADMIN_TOKEN=             # bảo vệ POST /api/admin/crawl/*. Để trống = tắt endpoint
```

Đặt file GGUF tại `backend/models/qwen2.5-3b-instruct-q4_k_m.gguf` hoặc sửa `LLM_GGUF_PATH`.

> **Không commit** `.env`, file DB, model GGUF, hoặc HuggingFace cache.

### 2. Cài đặt backend

```powershell
# Tạo virtualenv từ thư mục root
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Nếu PowerShell chặn activate:
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r backend/requirements.txt
```

### 3. Khởi động backend

```powershell
cd backend
uvicorn app.main:app --port 8000
```

Chờ đến khi thấy log `Server ready.`. Lần đầu mất vài phút do:
- Tải embedding model (`BAAI/bge-m3`) từ HuggingFace
- Tải reranker model (`BAAI/bge-reranker-v2-m3`)
- Load GGUF vào GPU qua llama.cpp
- Kết nối Qdrant Cloud
- Khởi tạo SQLite và warmup pipeline

Kiểm tra:

```powershell
curl http://localhost:8000/api/health
# Kỳ vọng: {"status":"ok","cuda":true,"qdrant":"ok","reranker":"ok",...}
```

Swagger UI: `http://localhost:8000/docs`

### 4. Chạy frontend

Mở terminal mới:

```powershell
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`.

---

## Tính Năng

### 11 Query Intents

| Intent | Hiển thị | Mô tả | Collections |
|--------|----------|-------|-------------|
| `hotel_search` | Khách sạn | Tìm khách sạn, resort, homestay | hotels + rooms + reviews |
| `restaurant_search` | Nhà hàng | Tìm nhà hàng, quán ăn, cafe | restaurants + reviews |
| `place_search` | Địa điểm | Địa điểm tham quan, check-in | places + reviews |
| `review_search` | Đánh giá | Xem đánh giá, nhận xét | 3 review collections |
| `room_search` | Phòng | Loại phòng, tiện nghi, view | rooms + hotels + reviews |
| `price_search` | Giá cả | So sánh giá, lọc ngân sách | hotels + restaurants |
| `specific_search` | Địa điểm cụ thể | Tìm đúng tên + exact name fallback | 3 primary collections |
| `event_search` | Sự kiện | Lễ hội, sự kiện đang diễn ra | SQLite events table |
| `itinerary_search` | Lịch trình | Lên kế hoạch nhiều ngày | hotels + restaurants + places |
| `chitchat` | Trò chuyện | Câu hỏi chung, giới thiệu AI | (không dùng Qdrant) |
| `general` | Tổng quát | Fallback | 3 primary collections |

### Session Memory

- Giữ **5 lượt** hội thoại gần nhất làm context cho LLM
- Tự động extract preference ngầm (district, budget) từ mỗi lượt → lưu vào `session_context`
- Lượt tiếp theo tự kế thừa preference làm filter mặc định

### Missed Query & Place Crawler

- Khi Qdrant trả 0 kết quả cho hotel/restaurant/place intent → ghi vào bảng `missed_queries`
- APScheduler mỗi 4h: lấy pending queries → SerpAPI `google_local` → embed → upsert Qdrant
- APScheduler mỗi 24h: crawl địa điểm mới theo categories (nhà hàng mới, khách sạn mới, ...)

### Profile & Recommendations

- Lưu profile theo session: `companions`, `budget_level`, `interests`, `dietary`, `trip_dates`
- `POST /api/recommend` trả top-N địa điểm khớp với profile, có scoring: rating × 0.6 + interest boost × 0.4

---

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/chat/stream` | Chat streaming (SSE) |
| GET | `/api/sessions` | Danh sách sessions |
| POST | `/api/sessions` | Tạo session mới |
| GET | `/api/sessions/{id}` | Chi tiết session |
| GET | `/api/sessions/{id}/messages` | Lịch sử tin nhắn |
| PATCH | `/api/sessions/{id}` | Đổi tên session |
| DELETE | `/api/sessions/{id}` | Xóa session |
| GET | `/api/profile/{session_id}` | Lấy profile |
| PUT | `/api/profile/{session_id}` | Tạo/cập nhật profile |
| DELETE | `/api/profile/{session_id}` | Xóa profile |
| POST | `/api/recommend` | Gợi ý theo profile |
| GET | `/api/health` | Health check (cuda, qdrant, reranker) |
| POST | `/api/admin/crawl/events` | Trigger event crawl (`X-Admin-Token` header) |
| POST | `/api/admin/crawl/places` | Trigger place crawl (`X-Admin-Token` header) |

**SSE events từ `/api/chat/stream`:** `meta` → `waiting?` → `intent` → `sources` → `fallback?` → `token*` → `done`

---

## Cấu Trúc Thư Mục

```text
PPBL_chat/
├── backend/
│   ├── app/
│   │   ├── api/             chat, sessions, health, profile, recommend, admin
│   │   ├── rag/             analyzer, intent, retrieval, rerank, llm,
│   │   │                    pipeline, memory, gemini_fallback, recommend,
│   │   │                    events_retrieval, schemas
│   │   ├── crawlers/        events_crawler, places_crawler, serpapi_adapter
│   │   ├── db/              sessions, profiles, events, missed_queries (schema.sql)
│   │   ├── utils/           nfc.py (Unicode normalize), slugify_vn.py
│   │   ├── main.py          FastAPI app + lifespan (startup/shutdown)
│   │   └── config.py        Tất cả env vars
│   ├── tests/               84 pytest tests (không cần GPU)
│   ├── data/                chats.db (tự tạo, gitignored)
│   ├── models/              GGUF models (gitignored)
│   ├── .env.example
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── app/                 Next.js App Router (chat, layout, providers)
│   ├── components/          chat/, filters/, sessions/, ui/
│   ├── hooks/               useChat (SSE), useSessions, useFilters
│   ├── lib/                 api.ts, sse.ts, format.ts, utils.ts
│   ├── constants/           districts.ts, quickReplies.ts
│   └── package.json
├── pbl7-rag.ipynb           Jupyter notebook nghiên cứu/prototype (Kaggle)
├── docs/                    Tài liệu kỹ thuật nội bộ
├── README.md                File này
└── CLAUDE.md                Hướng dẫn AI agent
```

---

## Kiểm Tra

### Backend unit tests (không cần GPU)

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests/ -q
# Kỳ vọng: 84 passed, 2 skipped
```

### Frontend type check + lint

```powershell
cd frontend
npm run lint
npx tsc --noEmit
```

### E2E (cần backend + Qdrant + GGUF)

| Query | Kỳ vọng |
|-------|---------|
| `Gợi ý khách sạn 4 sao ở Sơn Trà` | intent "Khách sạn", source cards với rating/giá, câu trả lời stream |
| `Lịch trình 3 ngày 2 đêm Đà Nẵng cho cặp đôi` | intent "Lịch trình", format Ngày 1/Ngày 2/Ngày 3 |
| `Bạn là AI gì?` | intent "Trò chuyện", sources rỗng, giới thiệu chatbot |
| `Novotel Đà Nẵng` | intent "Địa điểm cụ thể", thông tin đúng địa điểm |
| Hỏi tiếp `giá phòng thế nào?` | context kế thừa từ lượt trước |

---

## Tech Stack

**Backend:** FastAPI · uvicorn · llama-cpp-python · sentence-transformers · torch · qdrant-client · aiosqlite · sse-starlette · pydantic v2 · apscheduler · httpx

**Frontend:** Next.js 16 · React 19 · TypeScript 5 · Tailwind CSS 4 · TanStack Query v5 · Radix UI

**Models:** BAAI/bge-m3 · BAAI/bge-reranker-v2-m3 · Qwen2.5-3B-Instruct Q4_K_M (GGUF) · Gemini 2.0 Flash (optional)

**Infrastructure:** Qdrant Cloud · SQLite (WAL) · SerpAPI (Google Events + Local)
