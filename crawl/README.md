# Crawl Admin (standalone, đa-engine)

Công cụ **độc lập** điều phối nhiều crawler + giao diện quản trị. SQLite riêng `crawl/data/crawl.db`; output CSV theo từng engine.

## Khởi tạo cơ sở dữ liệu (Seed Data)
Trước khi chạy công cụ lần đầu, bạn cần khởi tạo cấu trúc bảng SQLite và nạp dữ liệu mẫu ban đầu (Link: https://www.kaggle.com/datasets/huychieu/danang-travel-data):
```bash
# Chạy từ thư mục gốc của project
python crawl/seed.py
```

## Các Engine và Đầu ra (Output)
| Key | Nguồn | Công nghệ | File Output & Cơ sở dữ liệu |
|---|---|---|---|
| `foody` | Nhà hàng Foody | API discovery + Playwright detail (async) | **Dữ liệu được lưu tiệm tiến (progressive saving)**:<br>1. SQLite table `entities` (cập nhật ngay khi xong mỗi quán)<br>2. `data/foody/restaurant_detail.csv` (chi tiết nhà hàng)<br>3. `data/foody/reviews_output.csv` (reviews thô)<br>4. `data/foody/reviews_cleaned.csv` (reviews đã tiền xử lý: chuẩn hóa văn bản, xử lý slang/viết tắt, tính điểm recency và chuẩn hóa thời gian) |
| `traveloka` | Khách sạn Traveloka | Playwright sync | `data/traveloka/{hotels,rooms,prices,policies,reviews,images}.csv` |
| `booking` | Khách sạn Booking.com | Playwright sync | `data/booking/{hotels,rooms,prices,policies,reviews,images}.csv` |
| `ingest` | **Đẩy CSV → Qdrant** | embed bge-m3 + **upsert** | Upsert trực tiếp dữ liệu từ các file CSV trên lên Qdrant collection tương ứng |

## Ingest lên Qdrant (nút riêng)
- Bấm thẻ **"⬆ Đẩy lên Qdrant"** sau khi cào thành công → embed (bge-m3) + **upsert** (theo `stable_uuid`, KHÔNG xoá collection → giữ nguyên `places_danang` + dữ liệu cũ). Idempotent (chạy lại không nhân bản).
- Phạm vi: nhà hàng (Foody) + khách sạn/phòng/review (Traveloka/Booking). KHÔNG đụng places.
- Cần `backend/.env` có `QDRANT_URL`/`QDRANT_API_KEY` (cùng Qdrant app chính) + bge-m3 trong `backend/models/.cache` (load offline). KHÔNG vào scheduler/"Chạy tất cả" (chỉ bấm tay).

## Tính năng
- **Chạy từng engine** (nút Chạy = ép chạy) hoặc **Chạy tất cả** (theo freshness).
- **Cơ chế ghi file tiệm tiến (Progressive saving)**: Foody crawler tự động lưu thông tin nhà hàng và append các reviews mới cào được ngay lập tức sau khi xong từng quán. Hỗ trợ resume hoàn hảo (nếu bị dừng giữa chừng, lần sau chạy tiếp không mất mát dữ liệu).
- **Scheduler** tự chạy định kỳ (mặc định 24h) các engine "tới hạn".
- **Freshness** theo engine: bỏ qua engine vừa chạy < `JOB_FRESHNESS_HOURS`. Foody còn có freshness theo từng quán (chỉ crawl lại quán đủ cũ).
- **Giao diện quản trị hiện đại**: Dark theme glassmorphism, Log realtime (SSE), lịch sử run, accordion danh sách chi tiết Nhà hàng và Khách sạn đã cào.

## Cài đặt & chạy
```bash
pip install -r crawl/requirements.txt
python -m playwright install chromium
cd crawl
uvicorn app.server:app --port 8100 --reload
```
Mở http://localhost:8100

## Cấu hình (env, tùy chọn)
Các biến môi trường cấu hình trong file `.env` hoặc truyền trực tiếp khi khởi chạy:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CRAWL_SCHEDULE_ENABLED` | `true` | Bật/tắt scheduler tự động cào định kỳ |
| `CRAWL_SCHEDULE_HOURS` | `24` | Chu kỳ chạy của scheduler (giờ) |
| `CRAWL_JOB_FRESHNESS_HOURS` | `20` | Bỏ qua engine (Foody/Traveloka/Booking) vừa chạy thành công trong vòng < ngần này giờ |
| `CRAWL_FRESHNESS_HOURS` | `48` | Bỏ qua các địa điểm/khách sạn đơn lẻ mới được cào trong vòng < ngần này giờ |
| `CRAWL_STALE_HOURS` | `720` | Số giờ hết hạn (stale) của dữ liệu (mặc định 30 ngày). Đạt mốc này sẽ ép cào lại |
| `CRAWL_FOODY_HEADLESS` | `true` | Chế độ headless cho Foody (vì crawl nhẹ qua API) |
| `CRAWL_TRAVELOKA/BOOKING_HEADLESS` | `false / true` | Chế độ headless cho Traveloka/Booking |
| `CRAWL_DISCOVERY_MAX_NEW` | `100` | Giới hạn tối đa số địa điểm mới thêm vào hàng đợi của Foody mỗi lần |
| `CRAWL_TRAVELOKA_MAX_PAGES/MAX_HOTELS/REVIEWS` | `3/30/10` | Giới hạn Traveloka (số trang/số khách sạn tối đa/số review tối thiểu) |
| `CRAWL_BOOKING_MAX_PAGES/MAX_PROPERTIES/MIN_REVIEWS` | `2/30/10` | Giới hạn Booking.com (số trang/số khách sạn tối đa/số review tối thiểu) |
| `CRAWL_BOOKING_CITY` | `Da Nang` | Tên thành phố mục tiêu để cào và kiểm tra địa giới trên Booking.com |
| `CRAWL_MAX_WORKERS` | `4` | Số luồng chạy song song tối đa (Foody) |
| `CRAWL_PORT` | `8100` | Port khởi chạy web server quản trị |

## Cấu trúc thư mục
```
crawl/app/
  config.py        cấu hình
  schema.sql/db.py SQLite: sources, entities, crawl_runs, crawl_logs, engine_state
  logbus.py        pub/sub log SSE
  discover.py      discovery URL Foody (API)
  foody_crawler.py detail crawler Foody (Playwright async)
  review_preprocessor.py tiền xử lý và dọn dẹp review quán ăn
  engines/
    __init__.py    REGISTRY foody/traveloka/booking (mỗi engine async run(ctx))
    hotel_crawler.py  Traveloka + Booking engine (Playwright sync)
  static/
    style.css      mã CSS giao diện
  orchestrator.py  chạy engine lần lượt + khóa 1-run + freshness
  server.py        FastAPI: /api/jobs, run, run-all, SSE log, scheduler
  templates/
    index.html     giao diện quản trị
```

## Lưu ý
- Traveloka/Booking chống bot rất mạnh; chạy headless dễ bị chặn hơn. Do đó `CRAWL_TRAVELOKA_HEADLESS` mặc định là `false` để chạy giao diện nổi. Bạn có thể bật ẩn danh bằng cách chuyển `CRAWL_TRAVELOKA_HEADLESS=true` hoặc `CRAWL_BOOKING_HEADLESS=true`.
- Mỗi lúc chỉ chạy **1 engine** để đảm bảo tài nguyên hệ thống (Playwright ngốn tài nguyên trình duyệt lớn).
