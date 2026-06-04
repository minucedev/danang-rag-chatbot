# Crawl Admin (standalone, đa-engine)

Công cụ **độc lập** điều phối nhiều crawler + giao diện quản trị. **Chưa nối** app chính
(`backend/`, `frontend/`). SQLite riêng `crawl/data/crawl.db`; output CSV theo từng engine.

## Engine (v này)
| key | Nguồn | Công nghệ | Output |
|---|---|---|---|
| `foody` | Nhà hàng Foody | API discovery + Playwright detail (async) | `data/foody/restaurant_detail.csv` + bảng `entities` |
| `agoda` | Khách sạn Agoda | Playwright sync (`crawl1 (2).py` nguyên trạng) | `data/agoda/{hotels,rooms,prices,policies,reviews,images}.csv` |
| `booking` | Khách sạn Booking.com | Playwright sync (nguyên trạng) | `data/booking/...` |
| `ingest` | **Đẩy CSV → Qdrant** | embed bge-m3 + **upsert** (không recreate) | upsert vào `restaurants_danang`, `accommodation_*` |

→ Output CSV khớp schema mà ETL `qdrant-etl.ipynb` đọc; job `ingest` đẩy chính các CSV đó lên Qdrant.

## Ingest lên Qdrant (nút riêng)
- Bấm thẻ **"⬆ Đẩy lên Qdrant"** sau khi crawl → embed (bge-m3) + **upsert** (theo `stable_uuid`,
  KHÔNG xoá collection → giữ nguyên `places_danang` + dữ liệu cũ). Idempotent (chạy lại không nhân bản).
- Phạm vi: nhà hàng (Foody) + khách sạn/phòng/review (Agoda/Booking). KHÔNG đụng places.
- Cần `backend/.env` có `QDRANT_URL`/`QDRANT_API_KEY` (cùng Qdrant app chính) + bge-m3 trong
  `backend/models/.cache` (load offline). KHÔNG vào scheduler/"Chạy tất cả" (chỉ bấm tay).

## Tính năng
- **Chạy từng engine** (nút Chạy = ép chạy) hoặc **Chạy tất cả** (theo freshness).
- **Scheduler** tự chạy định kỳ (mặc định 24h) các engine "tới hạn".
- **Freshness** theo engine: bỏ qua engine vừa chạy < `JOB_FRESHNESS_HOURS`. Foody còn có
  freshness theo từng quán (chỉ crawl lại quán đủ cũ).
- **Log realtime** (SSE) + **lịch sử run** + bảng entity Foody.

## Cài đặt & chạy
```bash
pip install -r crawl/requirements.txt
python -m playwright install chromium
cd crawl
uvicorn app.server:app --port 8100 --reload
```
Mở http://localhost:8100

## Cấu hình (env, tùy chọn)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CRAWL_SCHEDULE_HOURS` | 24 | Chu kỳ scheduler |
| `CRAWL_JOB_FRESHNESS_HOURS` | 20 | Bỏ qua engine vừa chạy < ngần này |
| `CRAWL_FRESHNESS_HOURS` | 24 | Freshness từng quán Foody |
| `CRAWL_DISCOVERY_MAX_NEW` | 100 | Cap số quán Foody mỗi lần |
| `CRAWL_AGODA_MAX_PAGES/HOTELS/REVIEWS` | 3/30/10 | Giới hạn Agoda (thấp = an toàn) |
| `CRAWL_BOOKING_MAX_PAGES/PROPERTIES/MIN_REVIEWS` | 2/30/10 | Giới hạn Booking |
| `CRAWL_HEADLESS` | true | Trình duyệt ẩn (đặt `false` nếu bị chặn) |
| `CRAWL_SCHEDULE_ENABLED` | true | Bật/tắt scheduler |

## Cấu trúc
```
crawl/app/
  config.py        cấu hình
  schema.sql/db.py SQLite: sources, entities, crawl_runs, crawl_logs, engine_state
  logbus.py        pub/sub log SSE
  discover.py      discovery URL Foody (API)
  foody_crawler.py detail crawler Foody (Playwright async)
  engines/
    __init__.py    REGISTRY foody/agoda/booking (mỗi engine async run(ctx))
    hotel_crawler.py  Agoda + Booking engine (từ "crawl1 (2).py", sync)
  orchestrator.py  chạy engine lần lượt + khóa 1-run + freshness
  server.py        FastAPI: /api/jobs, run, run-all, SSE log, scheduler
  templates/index.html  UI thẻ engine + log + lịch sử
```

## Lưu ý
- Agoda/Booking chống bot mạnh; headless có thể bị chặn. Giữ giới hạn thấp; nếu lỗi xem log,
  thử `CRAWL_HEADLESS=false`. Engine khách sạn được điều phối **nguyên trạng** (không sửa logic).
- Mỗi lúc chỉ chạy **1 engine** (Playwright nặng).
