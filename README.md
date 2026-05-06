# Đà Nẵng Travel Chatbot — PBL7

Chatbot du lịch Đà Nẵng sử dụng RAG (Retrieval-Augmented Generation): tìm kiếm thông tin khách sạn, nhà hàng, địa điểm từ vector database Qdrant, sau đó sinh câu trả lời bằng Qwen2.5-3B.

## Kiến trúc hệ thống

```
Browser (localhost:3000)
        │  HTTP + SSE streaming
        ▼
FastAPI (localhost:8000)
  ├─ POST /api/chat/stream   ← streaming SSE
  ├─ GET/POST /api/sessions  ← lịch sử hội thoại
  └─ GET /api/health
        │
        ├─── BAAI/bge-m3       (embedding model, GPU)
        ├─── Qwen2.5-3B        (LLM 4-bit, GPU)
        ├─── Qdrant Cloud      (vector DB, 7 collections)
        └─── SQLite local      (sessions + messages)
```

## Yêu cầu phần cứng (cho full stack)

| Thành phần | Tối thiểu |
|------------|-----------|
| GPU NVIDIA (CUDA) | 6GB VRAM |
| RAM hệ thống | 12GB |
| Disk trống | 15GB (HuggingFace model cache) |
| CUDA version | 12.1+ |

> Không có GPU → chỉ chạy được frontend để xem UI. LLM sẽ không hoạt động.

## Chạy thử UI ngay (không cần GPU)

```powershell
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`. Giao diện hiển thị đầy đủ. Gửi tin nhắn sẽ báo lỗi toast đỏ vì backend chưa chạy.

## Chạy full stack (cần GPU + credentials)

**Terminal 1 — Backend:**

```powershell
# 1. Tạo venv và cài packages (xem backend/README.md để biết chi tiết)
cd PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r backend/requirements.txt

# 2. Tạo file backend/.env (bắt buộc)
# Xem backend/README.md mục "Bước 2"

# 3. Chạy backend
cd backend
uvicorn app.main:app --port 8000
# Chờ "Server ready." (~2-5 phút lần đầu)
```

**Terminal 2 — Frontend:**

```powershell
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`.

## Cấu trúc thư mục

```
PPBL_chat/
├── backend/          ← FastAPI server
│   ├── app/
│   │   ├── api/      ← routes: chat, sessions, health
│   │   ├── rag/      ← pipeline, retrieval, LLM, intent
│   │   ├── db/       ← SQLite sessions
│   │   └── utils/    ← NFC normalize, slugify
│   ├── .env          ← credentials (tự tạo, không commit)
│   ├── requirements.txt
│   └── README.md     ← hướng dẫn chi tiết backend
├── frontend/         ← Next.js app
│   ├── app/          ← routes
│   ├── components/   ← UI components
│   ├── hooks/        ← useChat, useSessions, useFilters
│   ├── lib/          ← api, sse, format, utils
│   └── README.md     ← hướng dẫn chi tiết frontend
├── pbl7-rag.ipynb    ← notebook gốc (Kaggle)
└── RUN_LOCAL.md      ← hướng dẫn chạy notebook local
```

## Hướng dẫn chi tiết

- **Backend**: xem [backend/README.md](backend/README.md)
- **Frontend**: xem [frontend/README.md](frontend/README.md)
- **Notebook gốc**: xem [RUN_LOCAL.md](RUN_LOCAL.md)
