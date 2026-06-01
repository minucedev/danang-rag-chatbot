# Da Nang Travel Chatbot — PBL7

Chatbot du lịch Đà Nẵng sử dụng RAG pipeline: phân tích câu hỏi bằng LLM, tìm kiếm vector trong Qdrant (7 collections khách sạn / nhà hàng / địa điểm), rerank bằng BGE cross-encoder, rồi trả lời streaming qua FastAPI + Next.js. Hỗ trợ multi-turn conversation, profile cá nhân hóa, crawl sự kiện + địa điểm tự động, và tối ưu latency qua Gemini Flash + model nhỏ cho analyzer.

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
        ├─ BAAI/bge-m3                      embedding (truy vấn vector)
        ├─ BAAI/bge-reranker-v2-m3          cross-encoder reranker
        ├─ Qwen2.5-0.5B-Instruct (HF)       analyzer LLM (intent + filters, nhanh)
        ├─ Qwen3.5-4B (HF Transformers)     generator LLM (trả lời)
        ├─ Gemini 2.0 Flash                 primary generator khi có API key (~0.5s TTFT)
        ├─ Qdrant Cloud                     vector DB, 7 collections
        ├─ SQLite local                     sessions, messages, profiles,
        │                                   events, missed_queries, session_context
        └─ APScheduler                      3 background jobs (events + places)
```

**RAG pipeline per query:**

```
Câu hỏi
  → NFC normalize + query enrichment (history)
  → Qwen2.5-0.5B Analyzer  → intent + rewritten_query + filters  (~0.5s)
  → [CHITCHAT] → Gemini/local LLM trực tiếp, bỏ qua Qdrant
  → [EVENT_SEARCH] → query SQLite events
  → retrieve_by_intent() → Qdrant vector search (TOP_K_RETRIEVE=15/collection)
  → BGE cross-encoder reranker → TOP_K_RERANK=5 kết quả tốt nhất
  → [SPECIFIC_SEARCH miss] → exact name fallback (Qdrant scroll + MatchText)
  → [Gemini API key] → Gemini Flash primary generator  (~0.5-1s TTFT)
  → [fallback] → Qwen3.5-4B local generator
  → stream tokens → SSE done
```

---

## Yêu Cầu Hệ Thống

| Thành phần | Bắt buộc | Ghi chú |
|------------|----------|---------|
| Node.js | 20+ | Frontend Next.js 16 |
| npm | Có | Đi kèm Node.js |
| Python | 3.10+ | 3.13 hoạt động, khuyến nghị 3.11 nếu dùng bitsandbytes |
| GPU NVIDIA + driver | Khuyến nghị | ≥8GB VRAM (fp16) hoặc ≥4GB (4-bit); CPU fallback chậm hơn |
| CUDA 12.1 | Khuyến nghị | Dùng wheel PyTorch CUDA 12.1 |
| Qdrant Cloud | Có | URL + API key, 7 collections đã được import |
| HuggingFace Token | Khuyến nghị | Tránh rate limit khi tải model lần đầu |
| Disk trống | ~20GB | HF model cache (~12GB cho Qwen3.5-4B + 0.5B), embedding cache, packages |

Kiểm tra môi trường:

```powershell
node --version    # 20+
npm --version
python --version
nvidia-smi        # NVIDIA GPU driver
```

> Model LLM (~8GB) và embedding model (~1.5GB) **tự tải từ HuggingFace** khi khởi động lần đầu. Không cần tải tay.

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

# === MODELS (HuggingFace — tự tải lần đầu) ===
HF_TOKEN=your-huggingface-token        # khuyến nghị, tránh rate limit
LLM_HF_MODEL_NAME=Qwen/Qwen3.5-4B             # generator LLM
ANALYZER_HF_MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct  # analyzer LLM (nhanh hơn)
LLM_LOAD_IN_4BIT=false                         # true nếu VRAM < 8GB (cần bitsandbytes)

EMBED_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-m3

# === RETRIEVAL ===
TOP_K_RETRIEVE=15        # số kết quả lấy từ Qdrant trước rerank
TOP_K_RERANK=5           # số kết quả sau rerank
RERANK_SCORE_THRESHOLD=0.3
SCORE_THRESHOLD=0.3

# === GENERATION ===
DEFAULT_MAX_TOKENS=1024
DEFAULT_TEMPERATURE=0.2
MAX_HISTORY_TURNS=5      # số lượt hội thoại giữ làm context

# === DATABASE ===
DB_PATH=data/chats.db

# === GEMINI (primary generator — khuyến nghị để giảm TTFT ~0.5s) ===
# Khi có API key, Gemini Flash thay thế local LLM cho generation.
# USE_GEMINI_GENERATION=false để tắt và dùng local LLM.
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.0-flash
USE_GEMINI_GENERATION=true
GEMINI_FALLBACK_PREFIX_DISCLAIMER=true

# === EVENT CRAWLER (SerpAPI, tuỳ chọn) ===
SERPAPI_KEY=             # để trống = tắt crawler
CACHE_TTL_HOURS=24
DEFAULT_EVENT_DAYS=7

# === PLACE CRAWLER (tuỳ chọn, cần SERPAPI_KEY) ===
PLACE_CRAWL_INTERVAL_HOURS=4
NEW_PLACES_CRAWL_INTERVAL_HOURS=24
MAX_PLACE_RETRY=3
PLACE_CRAWL_BATCH=10

# === ADMIN ===
ADMIN_TOKEN=             # bảo vệ POST /api/admin/crawl/*. Để trống = tắt endpoint
```

> **Không commit** `.env`, file DB, hoặc HuggingFace cache.

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

# Tuỳ chọn: 4-bit quantization (tiết kiệm ~4GB VRAM)
# pip install bitsandbytes  # sau đó set LLM_LOAD_IN_4BIT=true trong .env
```

### 3. Khởi động backend

```powershell
cd backend
uvicorn app.main:app --port 8000
```

Chờ đến khi thấy log `Server ready.`. **Lần đầu mất 5-15 phút** do tải models từ HuggingFace:
- `BAAI/bge-m3` (~1.5GB) — embedding model
- `BAAI/bge-reranker-v2-m3` (~1GB) — reranker
- `Qwen/Qwen3.5-4B` (~8GB fp16 / ~4GB 4-bit) — generator LLM
- `Qwen/Qwen2.5-0.5B-Instruct` (~1GB) — analyzer LLM
- Kết nối Qdrant Cloud, khởi tạo SQLite, warmup pipeline

Từ lần 2 trở đi models được load từ cache (~1-3 phút).

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

### Latency Optimization

| Kỹ thuật | TTFT | Ghi chú |
|----------|------|---------|
| Gemini Flash primary | ~0.5–1s | Thay local LLM cho generation khi có API key |
| Qwen2.5-0.5B analyzer | ~0.5s | Thay 4B model cho intent classification |
| 4-bit quantization | -50% VRAM | `LLM_LOAD_IN_4BIT=true` + `pip install bitsandbytes` |
| **Tổng (Gemini + 0.5B)** | **~1–2s** | So với ~7–12s baseline |

### Session Memory

- Giữ **5 lượt** hội thoại gần nhất làm context cho LLM
- Tự động extract preference ngầm (district, budget) từ mỗi lượt → lưu vào `session_context`
- Lượt tiếp theo tự kế thừa preference làm filter mặc định

### Missed Query & Place Crawler

- Khi Qdrant trả 0 kết quả cho hotel/restaurant/place intent → ghi vào `missed_queries`
- APScheduler mỗi 4h: SerpAPI `google_local` → embed → upsert Qdrant
- APScheduler mỗi 24h: crawl địa điểm mới theo categories

### Profile & Recommendations

- Lưu profile theo session: `companions`, `budget_level`, `interests`, `dietary`, `trip_dates`
- `POST /api/recommend` trả top-N địa điểm khớp nhất, scoring: rating × 0.6 + interest boost × 0.4

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

**SSE events từ `/api/chat/stream`:** `meta` → `waiting?` → `intent` → `sources` → `token*` → `error?` → `done`

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

### E2E (cần backend + Qdrant)

| Query | Kỳ vọng |
|-------|---------|
| `Gợi ý khách sạn 4 sao ở Sơn Trà` | intent "Khách sạn", source cards với rating/giá, stream |
| `Lịch trình 3 ngày 2 đêm Đà Nẵng cho cặp đôi` | intent "Lịch trình", format Ngày 1/2/3 |
| `Bạn là AI gì?` | intent "Trò chuyện", sources rỗng, giới thiệu chatbot |
| `Novotel Đà Nẵng` | intent "Địa điểm cụ thể", thông tin đúng địa điểm |
| Hỏi tiếp `giá phòng thế nào?` | context kế thừa từ lượt trước |

---

## Tech Stack

**Backend:** FastAPI · uvicorn · transformers · accelerate · bitsandbytes (optional) · sentence-transformers · torch · qdrant-client · aiosqlite · sse-starlette · pydantic v2 · apscheduler · httpx

**Frontend:** Next.js 16 · React 19 · TypeScript 5 · Tailwind CSS 4 · TanStack Query v5 · Radix UI

**Models:**
- `BAAI/bge-m3` — multilingual embedding
- `BAAI/bge-reranker-v2-m3` — cross-encoder reranker
- `Qwen/Qwen2.5-0.5B-Instruct` — analyzer LLM (intent classification, ~0.5s)
- `Qwen/Qwen3.5-4B` — generator LLM (response generation, fp16 / 4-bit)
- `Gemini 2.0 Flash` — primary generator via API (khuyến nghị, ~0.5-1s TTFT)

**Infrastructure:** Qdrant Cloud · SQLite (WAL) · SerpAPI (Google Events + Local) · HuggingFace Hub
