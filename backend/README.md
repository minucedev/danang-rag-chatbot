# Backend — FastAPI RAG Server

Server API xử lý chat streaming, session history, và pipeline RAG (Qdrant + bge-m3 + Qwen2.5-3B).

---

## Yêu cầu

| Thành phần | Yêu cầu |
|------------|---------|
| GPU NVIDIA | VRAM ≥ 6GB (Qwen 4-bit ~2.5GB + bge-m3 ~2.3GB) |
| RAM hệ thống | ≥ 12GB |
| Disk | ≥ 15GB (model cache) |
| Python | 3.10 hoặc 3.11 (tránh 3.12+) |
| CUDA | 12.1+ |
| Driver NVIDIA | mới nhất |

**Kiểm tra GPU trước:**
```powershell
nvidia-smi
```
Phải thấy tên GPU và CUDA version.

---

## Bước 1 — Tạo Python virtual environment

Chạy từ thư mục gốc `PPBL_chat/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Nếu lỗi execution policy:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

Sau khi activate, terminal hiện `(.venv)` ở đầu dòng.

---

## Bước 2 — Tạo file `.env`

Tạo file `backend/.env` (không phải `.env.example`):

```powershell
copy backend\.env.example backend\.env
```

Mở `backend/.env` và điền thông tin thật:

```env
QDRANT_URL=https://<cluster-id>.us-west-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=<api-key-của-bạn>
HF_TOKEN=<huggingface-token>

# Optional: tránh lỗi "filename too long" trên Windows
HF_HOME=D:\hf_cache
```

**Lấy credentials:**

| Credential | Cách lấy |
|------------|----------|
| `QDRANT_URL` | Qdrant Cloud dashboard → cluster → Connection → gRPC URL |
| `QDRANT_API_KEY` | Qdrant Cloud dashboard → cluster → API Keys → Create |
| `HF_TOKEN` | huggingface.co → Settings → Access Tokens → New token (chọn Read) |

> **Quan trọng:** Không commit file `.env` lên git. File này đã có trong `.gitignore`.

---

## Bước 3 — Cài PyTorch với CUDA

**Phải cài PyTorch CUDA TRƯỚC** khi cài các package khác:

```powershell
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Verify CUDA hoạt động:
```powershell
python -c "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0))"
```

Kết quả mong đợi:
```
CUDA: True | NVIDIA GeForce RTX ...
```

> Nếu in `False` → driver hoặc CUDA chưa đúng. Xem mục Troubleshooting.

---

## Bước 4 — Cài các package còn lại

```powershell
pip install -r backend/requirements.txt
```

Quá trình này mất ~3-5 phút. Các package chính:
- `fastapi`, `uvicorn[standard]`, `sse-starlette` — web server
- `sentence-transformers` — bge-m3 embedding
- `transformers`, `bitsandbytes`, `accelerate` — Qwen 4-bit LLM
- `qdrant-client[async]` — vector DB client
- `aiosqlite` — SQLite async

---

## Bước 5 — Chạy server

```powershell
cd backend
uvicorn app.main:app --port 8000
```

**Startup log (theo thứ tự):**

```
Loading embedding model...
  ← Lần đầu tải bge-m3 từ HuggingFace (~2.3GB, mất 5-10 phút)
  ← Lần sau load từ cache (~30 giây)

Loading LLM...
  ← Lần đầu tải Qwen2.5-3B-Instruct (~2.5GB, mất 5-10 phút)
  ← Lần sau load từ cache (~60 giây)

Connecting to Qdrant...
Initializing database...
  ← Tạo data/chats.db nếu chưa có

Warming up pipeline (first GPU pass)...
  ← Chạy 1 query dummy để cache GPU kernels (~30 giây)

Server ready.
INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Tổng thời gian startup:**
- Lần đầu (download model): 15-25 phút
- Lần sau (load từ cache): 2-3 phút

---

## Bước 6 — Verify hoạt động

**Kiểm tra health:**
```powershell
curl http://localhost:8000/api/health
```

Kết quả mong đợi:
```json
{
  "status": "ok",
  "cuda": true,
  "model": "Qwen/Qwen2.5-3B-Instruct",
  "qdrant": "ok",
  "pipeline_ready": true
}
```

**Xem API docs:**

Mở `http://localhost:8000/docs` — Swagger UI tự động từ FastAPI, test được tất cả endpoints.

**Endpoints chính:**

| Method | URL | Mô tả |
|--------|-----|--------|
| `GET` | `/api/health` | Kiểm tra trạng thái |
| `POST` | `/api/chat/stream` | Chat streaming (SSE) |
| `GET` | `/api/sessions` | Danh sách sessions |
| `POST` | `/api/sessions` | Tạo session mới |
| `GET` | `/api/sessions/{id}/messages` | Lịch sử tin nhắn |
| `PATCH` | `/api/sessions/{id}` | Đổi tên session |
| `DELETE` | `/api/sessions/{id}` | Xóa session |

---

## Cấu trúc thư mục

```
backend/
├── app/
│   ├── main.py          ← FastAPI app, CORS, lifespan (load models)
│   ├── config.py        ← đọc .env, constants
│   ├── api/
│   │   ├── chat.py      ← POST /api/chat/stream (SSE)
│   │   ├── sessions.py  ← CRUD sessions & messages
│   │   └── health.py    ← GET /api/health
│   ├── rag/
│   │   ├── pipeline.py  ← RAGPipeline: orchestrate retrieval + LLM
│   │   ├── retrieval.py ← AsyncQdrantClient, search theo intent
│   │   ├── intent.py    ← detect intent từ query (hotel/restaurant/place/...)
│   │   ├── rerank.py    ← rerank kết quả theo rating, district, intent
│   │   ├── llm.py       ← load Qwen, TextIteratorStreamer
│   │   ├── memory.py    ← heuristic multi-turn context
│   │   └── schemas.py   ← Pydantic models
│   ├── db/
│   │   ├── sessions.py  ← aiosqlite CRUD (WAL mode)
│   │   └── schema.sql   ← CREATE TABLE definitions
│   └── utils/
│       ├── nfc.py       ← NFC normalize cho tiếng Việt
│       └── slugify_vn.py ← strip diacritic cho filter quận
├── data/
│   └── chats.db         ← SQLite database (tự tạo, gitignored)
├── .env                 ← credentials (tự tạo, gitignored)
├── .env.example         ← template
├── requirements.txt
└── test_phase1.py, test_phase2.py  ← unit tests
```

---

## Troubleshooting

### `bitsandbytes` lỗi CUDA setup

```
RuntimeError: CUDA Setup failed despite GPU being available
```

Fix:
```powershell
pip uninstall bitsandbytes -y
pip install bitsandbytes --no-cache-dir
```

### `CUDA out of memory` khi load model

Triệu chứng: server crash với `torch.cuda.OutOfMemoryError`.

Fix:
1. Đóng Chrome (hardware acceleration), game, Photoshop — các app chiếm VRAM
2. Hoặc dùng model nhỏ hơn — thêm vào `backend/.env`:
   ```env
   LLM_MODEL_NAME=Qwen/Qwen2.5-1.5B-Instruct
   ```

### `QDRANT_URL is required` khi khởi động

File `backend/.env` chưa tồn tại hoặc đặt sai vị trí.

Verify:
```powershell
ls backend\.env   # phải thấy file này
```

### `401 Unauthorized` từ Qdrant

`QDRANT_API_KEY` sai. Lấy lại key từ Qdrant Cloud dashboard.

### `OSError: [WinError 206] filename too long`

Thêm vào `backend/.env`:
```env
HF_HOME=D:\hf_cache
```

Sau đó tạo thư mục:
```powershell
mkdir D:\hf_cache
```

### HuggingFace `429 Too Many Requests` (rate limit)

Cần có `HF_TOKEN` trong `.env`. Tải model trước:
```powershell
huggingface-cli download BAAI/bge-m3
huggingface-cli download Qwen/Qwen2.5-3B-Instruct
```

### `CUDA: False` dù có GPU

Nguyên nhân thường là cài nhầm PyTorch CPU. Fix:
```powershell
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Verify lại:
```powershell
python -c "import torch; print(torch.cuda.is_available())"
```

---

## Chạy unit tests (không cần GPU)

```powershell
cd backend
python test_phase1.py   # test utils, intent detection, schemas
python test_phase2.py   # test SQLite CRUD
```

Cả hai phải in `All checks passed`.

---

## Biến môi trường trong `.env`

| Biến | Bắt buộc | Mặc định | Mô tả |
|------|----------|----------|-------|
| `QDRANT_URL` | Có | — | URL cluster Qdrant Cloud |
| `QDRANT_API_KEY` | Có | — | API key Qdrant |
| `HF_TOKEN` | Khuyến nghị | — | HuggingFace token (tránh rate limit) |
| `EMBED_MODEL_NAME` | Không | `BAAI/bge-m3` | Model embedding |
| `LLM_MODEL_NAME` | Không | `Qwen/Qwen2.5-3B-Instruct` | Model LLM |
| `USE_4BIT` | Không | `true` | Dùng 4-bit quantization (cần GPU) |
| `HF_HOME` | Không | default | Thư mục cache model |
