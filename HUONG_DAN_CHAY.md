# Hướng Dẫn Chạy — Da Nang Travel Chatbot

Hướng dẫn ngắn gọn để chạy dự án từ đầu. Cần **2 cửa sổ terminal**: một cho backend, một cho frontend.

> Tài liệu chi tiết (kiến trúc, API, tính năng) xem trong [`README.md`](README.md).

---

## 0. Cần chuẩn bị

| Thành phần | Phiên bản | Kiểm tra |
|------------|-----------|----------|
| Python | 3.10+ | `python --version` |
| Node.js | 20+ | `node --version` |
| Qdrant Cloud | URL + API key | (đã có sẵn cluster) |
| Gemini API key | khuyến nghị | lấy ở https://aistudio.google.com/apikey |

> **Không cần GPU.** Hướng dẫn này dùng cấu hình **CPU + Gemini** (xem mục 2).

---

## 1. Cấu hình `.env`

```powershell
copy backend\.env.example backend\.env
```

Mở `backend\.env`, điền tối thiểu:

```env
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-qdrant-key
GEMINI_API_KEY=your-gemini-key
HF_TOKEN=your-huggingface-token        # khuyến nghị, tránh rate limit khi tải model
```

> ⚠️ **Không bao giờ commit** file `.env` (đã được gitignore sẵn).

---

## 2. Cấu hình cho máy CPU / ít RAM

Vẫn trong `backend\.env`, đặt các giá trị sau để chạy nhẹ:

```env
LLM_HF_MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct   # model nhỏ thay cho 4B
USE_GEMINI_GENERATION=true                      # Gemini trả lời chính
GEMINI_MODEL=gemini-2.0-flash
ENABLE_RERANKER=false                           # tắt reranker, tiết kiệm ~2.2GB RAM
```

**Tại sao:** Gemini lo phần sinh câu trả lời (nhanh, không tốn RAM máy), local LLM chỉ làm việc nhẹ. Tắt reranker giúp tránh hết RAM (OOM) trên máy < 8GB trống.

---

## 3. Cài & chạy Backend (terminal 1)

```powershell
# Tạo virtualenv (chạy ở thư mục gốc dự án)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Nếu PowerShell chặn activate:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

pip install --upgrade pip
pip install torch                       # bản CPU là đủ (KHÔNG cần --index-url cu121)
pip install -r backend\requirements.txt
playwright install chromium             # 1 lần — cho dashboard crawl (mục 7)

# Khởi động server
cd backend
python -m uvicorn app.main:app --port 8000
```

**Chờ tới khi thấy log `Server ready.`**
- Lần đầu mất vài phút để tải model embedding/analyzer từ HuggingFace.
- Nếu đã có sẵn model trong `backend\models\.cache\huggingface`, app tự load offline (không gọi mạng).

Kiểm tra:

```powershell
curl http://localhost:8000/api/health
# Kỳ vọng trên CPU: {"status":"ok","cuda":false,"qdrant":"ok","reranker":"not_loaded",...}
```

Swagger UI: http://localhost:8000/docs

---

## 4. Cài & chạy Frontend (terminal 2)

```powershell
cd frontend
npm install
npm run dev
```

Mở trình duyệt: **http://localhost:3000**

---

## 4b. Tạo tài khoản & đăng nhập

App **yêu cầu đăng nhập** (mỗi tài khoản có chat/yêu thích/lịch trình riêng). Không có trang đăng ký
công khai — admin tạo tài khoản bằng CLI:

```powershell
python backend\scripts\create_user.py demo demo123456
```

Mở **http://localhost:3000** → bị chuyển tới `/login` → đăng nhập bằng tài khoản vừa tạo.

> Token lưu trong SQLite (`backend/data/chats.db`), gửi qua `Authorization: Bearer`. Đăng xuất ở nút
> **Đăng xuất** cuối sidebar. Dữ liệu chat/yêu thích ẩn danh CŨ (trước khi có login) sẽ vô chủ — muốn
> sạch thì xóa `backend\data\chats.db*` rồi khởi động lại.

---

## 5. Thử nhanh

Gõ vào ô chat: `Gợi ý khách sạn 4 sao ở Sơn Trà`
→ Hiện intent "Khách sạn", các thẻ địa điểm, câu trả lời stream dần.

Nếu hỏi địa điểm mà DB chưa có (vd `du lịch ở Cẩm Lệ`), Gemini sẽ trả lời từ kiến thức chung kèm ghi chú, và crawler sẽ tự bổ sung dữ liệu thật sau (xem mục 6).

---

## 6. Tự động cập nhật dữ liệu (chạy nền)

Khi backend đang chạy, có 3 job tự động (APScheduler):

| Job | Chu kỳ | Việc |
|-----|--------|------|
| `missed_place_crawl` | mỗi **4h** | crawl địa điểm cho các câu hỏi từng "0 kết quả" |
| `event_crawl` | mỗi **24h** (chạy ngay khi khởi động) | crawl sự kiện Đà Nẵng |
| `new_places_crawl` | mỗi **24h** | crawl địa điểm mới theo nhóm |

> Cần `SERPAPI_KEY` trong `.env` thì crawler mới hoạt động (để trống = tắt). Các job chỉ chạy khi backend còn bật.

Muốn crawl ngay không cần chờ:

```powershell
# Cần đặt ADMIN_TOKEN trong .env, rồi dùng đúng token đó ở header
curl -X POST http://localhost:8000/api/admin/crawl/places `
  -H "X-Admin-Token: your-admin-token" `
  -H "Content-Type: application/json" `
  -d '{\"missed_only\": true}'
```

---

## 7. Crawl Admin Dashboard (đã gộp vào backend)

Tool crawl Foody/Traveloka/Booking trước đây chạy riêng ở cổng 8100, **nay nằm chung trong backend**.
Không cần chạy lệnh thứ hai — khi backend bật là dashboard có sẵn:

**http://localhost:8000/admin/crawl/**

- Bấm nút **▶ Chạy** từng engine hoặc **▶ Chạy tất cả** để crawl thủ công; log realtime + lịch sử hiện ngay trên trang.
- Ingest đẩy dữ liệu lên Qdrant, **dùng chung embedder BGE-M3** với chatbot (không tốn thêm ~2GB RAM).
- CSV xuất ở `backend/crawl_data/`, SQLite riêng ở `backend/data/crawl.db`.

> **Auto-crawl MẶC ĐỊNH TẮT** (máy ~4GB RAM, tránh OOM khi Playwright + chatbot chạy cùng lúc).
> Bật lịch tự động: đặt `CRAWL_SCHEDULE_ENABLED=true` trong `backend\.env`.
> Cần bảo vệ các nút crawl trên cổng public: đặt `CRAWL_ADMIN_REQUIRE_TOKEN=true` + `ADMIN_TOKEN=...`
> (khi đó các thao tác ghi cần header `X-Admin-Token`).

Seed dữ liệu ban đầu từ `raw_data/` (tuỳ chọn): `python backend/scripts/seed.py`.

---

## Lỗi thường gặp

| Lỗi | Cách xử lý |
|-----|-----------|
| `uvicorn: command not found` | Dùng `python -m uvicorn app.main:app --port 8000` |
| Server treo ở "Loading embedding model" | Model chưa tải xong (lần đầu) hoặc mạng chậm — chờ thêm; đảm bảo có `HF_TOKEN` |
| Process bị kill / hết RAM (OOM) | Đặt `ENABLE_RERANKER=false` và dùng model `Qwen2.5-0.5B` (mục 2) |
| `/api/health` trả 500 | Backend chưa load xong — chờ `Server ready.` |
| UI báo lỗi kết nối API | Backend chưa chạy hoặc chưa ở cổng 8000 |
| Gemini báo quota/model retired | Kiểm tra `GEMINI_MODEL=gemini-2.0-flash` và còn hạn mức API |

---

## Chạy test (tuỳ chọn)

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests\ -q
# Kỳ vọng: 113 passed, 1 xfailed
```
