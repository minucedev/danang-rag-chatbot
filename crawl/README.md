# Crawl Admin (standalone)

Công cụ **độc lập** để crawl dữ liệu (Foody) + giao diện quản trị. **Chưa nối** với app chính
(`backend/`, `frontend/`) — chỉ gồm giao diện + pipeline. SQLite riêng tại `crawl/data/crawl.db`.

## Tính năng (v1)
- Quản lý danh sách **nguồn URL** (entity Foody) qua UI.
- **Chạy crawl** theo logic `crawl-update.txt`: lưu `last_crawl_at` mỗi entity, chỉ crawl
  entity **mới / quá hạn freshness / quá cũ**; crawl xong **ghi đè hoàn toàn** dữ liệu cũ.
- **Bảng entity**: tên, quận, trạng thái, số review, lần crawl gần nhất, độ cũ.
- **Log realtime** (SSE) trong khi crawl.

> v2 (chưa làm): tự khám phá entity từ trang listing; crawler **review** theo ngày crawl gần nhất.

## Cài đặt
```bash
# từ thư mục gốc repo, dùng venv của dự án hoặc venv mới
pip install -r crawl/requirements.txt
python -m playwright install chromium      # tải Chromium (~150MB)
```

## Chạy
```bash
# từ thư mục crawl/  (để "app" là package import được)
cd crawl
uvicorn app.server:app --port 8100 --reload
```
Mở http://localhost:8100

## Cấu hình (env, tùy chọn)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CRAWL_FRESHNESS_HOURS` | 24 | Mới crawl < ngần này giờ → bỏ qua |
| `CRAWL_STALE_HOURS` | 720 | Quá cũ (30 ngày) → ép crawl lại |
| `CRAWL_MAX_WORKERS` | 4 | Số page Playwright song song |
| `CRAWL_HEADLESS` | true | Chạy trình duyệt ẩn |
| `CRAWL_PORT` | 8100 | Cổng server |
| `CRAWL_DB_PATH` | crawl/data/crawl.db | Đường dẫn SQLite |

## Cấu trúc
```
crawl/app/
  config.py         cấu hình
  schema.sql        bảng: sources, entities, crawl_runs, crawl_logs
  db.py             truy cập SQLite (aiosqlite)
  foody_crawler.py  crawl chi tiết 1 URL (Playwright) — refactor từ crawl1.py
  pipeline.py       chọn entity theo độ cũ → crawl song song → ghi đè → log
  server.py         FastAPI: trang admin + REST + SSE log
  templates/index.html  giao diện (Tailwind CDN + JS)
```
