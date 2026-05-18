# Plan: Chatbot UI cho RAG Du lịch Đà Nẵng

> **File này là kế hoạch chính thức.** Mọi công việc thực thi phải theo đúng các phase dưới đây. Khi hoàn thành 1 task, tick `[x]` vào checkbox tương ứng. KHÔNG bỏ qua phase. KHÔNG thêm task không có trong plan mà không bàn bạc trước.

---

## Mục tiêu tổng (Overall Goal)

Xây giao diện chatbot **hoàn chỉnh, polished, demo-ready** cho hệ thống RAG du lịch Đà Nẵng (đã có sẵn trong `pbl7-rag.ipynb`). Phục vụ demo đồ án PBL — phải trông như sản phẩm thật, chạy ổn định ≥ 2 giờ liên tục.

**Tech stack đã chốt:**
- Backend: **FastAPI** (Python 3.10/3.11) chạy trên máy local có GPU NVIDIA
- Frontend: **Next.js 14** (App Router, TypeScript, Tailwind, shadcn/ui)
- Database (sessions): **SQLite** qua aiosqlite
- Streaming: **SSE** (Server-Sent Events)
- Vector DB: **Qdrant Cloud** (đang dùng, không đổi)

**Thiết kế chi tiết:** xem mục "Reference design decisions" cuối file.

---

## Phase 1 — Pipeline extraction từ notebook

**Goal:** Tách logic RAG từ `pbl7-rag.ipynb` thành Python modules có thể import được. Pipeline phải chạy được async (cho FastAPI) và NFC-normalize input.

### Tasks
- [x] Tạo cấu trúc thư mục `backend/` với layout chuẩn
- [x] Tạo `backend/.env.example` với `QDRANT_URL`, `QDRANT_API_KEY`, `HF_TOKEN`
- [x] Tạo `backend/requirements.txt` (gộp từ Cell 1 notebook + thêm `fastapi`, `uvicorn[standard]`, `sse-starlette`, `aiosqlite`, `pydantic>=2`)
- [x] Tạo `backend/app/config.py` — load `.env`, định nghĩa constants (collections, model names, paths)
- [x] Tạo `backend/app/utils/nfc.py` — function `normalize_nfc(text: str) -> str`
- [x] Tạo `backend/app/utils/slugify_vn.py` — function `slugify_vn(text: str) -> str` (strip diacritic + lowercase)
- [x] Tạo `backend/app/rag/schemas.py` — Pydantic models: `SearchResult`, `ChatRequest`, `ChatFilters`, `MessageEntity`, `SessionEntity`
- [x] Tạo `backend/app/rag/intent.py` — `QueryIntent` enum + `detect()` (lift từ Cell 3, áp NFC)
- [x] Tạo `backend/app/rag/retrieval.py` — dùng `AsyncQdrantClient` thay `QdrantClient`, dùng `asyncio.gather` thay `ThreadPoolExecutor`, fetch_parent_entity với cache
- [x] Tạo `backend/app/rag/rerank.py` — lift `rerank_results()` từ Cell 4
- [x] Tạo `backend/app/rag/llm.py` — load Qwen 4-bit, hàm `generate_streaming(prompt) -> AsyncIterator[str]` dùng `TextIteratorStreamer`
- [x] Tạo `backend/app/rag/memory.py` — heuristic context: `needs_context()`, `build_search_query(history, new_query)`
- [x] Tạo `backend/app/rag/pipeline.py` — class `RAGPipeline` async với method `answer_stream(query, filters, history) -> AsyncIterator[Event]`
- [x] Build prompt template tiếng Việt với 1-2 few-shot examples (đặt trong `pipeline.py`)

### Verification
- [x] `python test_phase1.py` — utils/intent/memory/schemas pass (không cần GPU)
- [ ] Smoke test trên GPU machine: gọi `pipeline.answer_stream("Khách sạn Sơn Trà")` → trả về events đúng
- [x] NFC test: `normalize_nfc` pass
- [x] Slugify test: `slugify_vn("Hải Châu") == "hai chau"` pass

### Definition of Done
- [x] Tất cả task xong, logic tests pass. GPU smoke test cần chạy trên máy đích.

---

## Phase 2 — SQLite + sessions module

**Goal:** Có persistence layer cho chat history. Sessions + messages persist được qua restart server.

### Tasks
- [x] Tạo `backend/app/db/schema.sql` — 2 tables (`sessions`, `messages`) + indexes + `PRAGMA journal_mode=WAL`
- [x] Tạo `backend/app/db/sessions.py` — aiosqlite connection management
- [x] Function: `create_session(title) -> session_id`
- [x] Function: `list_sessions(limit, offset) -> List[SessionEntity]`
- [x] Function: `get_session(id) -> SessionEntity | None`
- [x] Function: `rename_session(id, new_title)`
- [x] Function: `delete_session(id)` (CASCADE messages)
- [x] Function: `add_message(session_id, role, content, sources_json, intent) -> message_id`
- [x] Function: `get_messages(session_id) -> List[MessageEntity]`
- [x] Function: `update_message_content(message_id, content)` (cho streaming finalize)
- [x] Function: `auto_title_from_message(content: str) -> str` (cắt 40 chars, strip xuống dòng)
- [x] Init DB ở `lifespan` của FastAPI: `data/chats.db` ← done trong `main.py`

### Verification
- [x] Unit test: tạo session → list → có 1 entry với title đúng
- [x] Unit test: thêm 5 messages → get_messages trả đúng thứ tự + đúng sources_json
- [x] Unit test: delete session → messages bị xóa CASCADE
- [x] WAL mode bật: `data/chats.db-wal` xuất hiện sau ghi

### Definition of Done
- [x] 8/8 unit tests pass (`python test_phase2.py`)

---

## Phase 3 — FastAPI skeleton + SSE chat endpoint

**Goal:** Có HTTP server với 1 endpoint chat streaming hoạt động. Test được bằng `curl`.

### Tasks
- [x] Tạo `backend/app/main.py` — FastAPI app với CORS cho `http://localhost:3000`
- [x] `lifespan`: load encoder + Qwen + init DB + warmup query
- [x] Module-level `inference_lock = asyncio.Lock()` (trong `chat.py`)
- [x] Tạo `backend/app/api/health.py` — `GET /api/health` trả CUDA/model/Qdrant status
- [x] Tạo `backend/app/api/chat.py` — `POST /api/chat/stream` (SSE)
- [x] Body schema: `{session_id?, message, filters?}`
- [x] Auto-create session nếu `session_id` null, trả `session_id` trong event `meta`
- [x] SSE event sequence: `meta` → `intent` → `sources` → `token`* → `done`
- [x] Persist user message ngay khi nhận, persist assistant message (placeholder) trước khi stream
- [x] Update assistant message content khi stream xong (hoặc bị abort)
- [x] Implement abort: `request.is_disconnected()` + `StoppingCriteria` set `threading.Event`
- [x] Headers SSE: `Cache-Control: no-cache`, `X-Accel-Buffering: no`
- [x] Heartbeat: `ping=15` qua sse_starlette
- [x] Source dedup: theo `(collection, point_id)` trong `retrieval.py`

### Verification
- [ ] `curl -N -X POST http://localhost:8000/api/chat/stream ...` — cần GPU machine
- [x] OpenAPI docs `/docs` load được: routes verified locally
- [ ] `GET /api/health` trả `{cuda: true, ...}` — cần GPU machine
- [ ] Cold start ≤ 90s, abort < 1s, concurrency — cần GPU machine

### Definition of Done
- [x] Code complete + imports OK. GPU tests cần chạy trên máy đích.

---

## Phase 4 — Sessions API

**Goal:** Frontend có thể list/load/rename/delete sessions qua REST.

### Tasks
- [ ] Tạo `backend/app/api/sessions.py`
- [x] `GET /api/sessions` — list sessions (paginated)
- [x] `GET /api/sessions/{id}/messages` — load history (gồm sources)
- [x] `PATCH /api/sessions/{id}` — rename `{title: string}`
- [x] `DELETE /api/sessions/{id}` — delete
- [x] Register router trong `main.py`

### Verification
- [ ] Test cả endpoints qua `/docs` UI — cần server chạy trên GPU machine
- [x] Logic verified qua Phase 2 unit tests (create/delete/get_messages)

### Definition of Done
- [x] 5 endpoints implemented + Pydantic validated. E2E test cần GPU machine.

---

## Phase 5 — Next.js shell + chat UI + SSE consumer

**Goal:** Giao diện chat tối thiểu chạy được: gõ message, thấy answer stream ra, persist sau reload.

### Tasks
- [x] `npx create-next-app@latest frontend --typescript --tailwind --app --no-src-dir`
- [x] Cài: `@tanstack/react-query`, `react-markdown`, `lucide-react`, shadcn/ui setup
- [x] `npx shadcn-ui@latest init` + add components: button, input, textarea, card, badge, slider, select, dialog, scroll-area, separator, skeleton, sonner (toast)
- [x] Tạo `frontend/app/layout.tsx` — root layout với `Inter({subsets:['latin','vietnamese']})` + QueryClientProvider + Toaster
- [x] Tạo `frontend/app/page.tsx` — redirect tới `/chat`
- [x] Tạo `frontend/app/chat/layout.tsx` — 2-column shell (SessionSidebar trái, main phải)
- [x] Tạo `frontend/app/chat/page.tsx` — empty state với welcome + quick replies + streaming inline
- [x] Tạo `frontend/app/chat/[sessionId]/page.tsx` — view 1 session
- [x] Tạo `frontend/lib/api.ts` — fetch wrapper cơ bản
- [x] Tạo `frontend/lib/sse.ts` — `streamSSE()` async generator (fetch + ReadableStream)
- [x] Tạo `frontend/lib/nfc.ts` — `normalizeNFC()` cho input
- [x] Tạo `frontend/lib/format.ts` — currency vi-VN, intent label VN map
- [x] Tạo `frontend/hooks/useChat.ts` — state machine: idle/streaming/waiting/error, gọi SSE, append tokens, AbortController
- [x] Tạo `frontend/components/chat/ChatInput.tsx` — textarea + Enter to send + Stop button khi đang stream
- [x] Tạo `frontend/components/chat/MessageList.tsx`
- [x] Tạo `frontend/components/chat/MessageBubble.tsx` — user vs assistant style, react-markdown
- [x] Tạo `frontend/components/chat/IntentBadge.tsx`
- [x] Tạo `frontend/lib/utils.ts` — cn() helper (clsx + tailwind-merge)
- [x] Cài `class-variance-authority`, `clsx`, `tailwind-merge`

### Verification
- [x] `npm run dev` chạy tại `localhost:3000` — Ready in 651ms, không lỗi
- [x] `npx tsc --noEmit` — 0 errors
- [ ] Gõ message → Send → thấy intent badge hiện → chữ stream ra dần (cần backend GPU)
- [ ] Reload trang giữa stream → message marked "(Bị ngắt)" hoặc giữ nguyên đến token cuối
- [ ] Click Stop → stream dừng < 1s
- [ ] Diacritic VN render đẹp (không fallback font)

### Definition of Done
- [x] Code complete, TypeScript clean, dev server starts. E2E test cần GPU machine.

---

## Phase 6 — Source cards + intent badge

**Goal:** Hiển thị các entity được retrieve dưới dạng card đẹp, có ảnh placeholder, rating, giá, địa chỉ, link Google Maps.

### Tasks
- [x] Tạo `frontend/components/chat/SourceCard.tsx` — card cho 1 entity: name, district badge, rating ★, price VND, address, Google Maps link
- [x] Tạo `frontend/components/chat/SourceCardList.tsx` — horizontal scroll, expand/collapse nếu > 5 cards
- [x] Wire `sources` event vào AssistantBubble: cards hiện TRƯỚC text answer (nguồn hiện trước → UX nhanh hơn)
- [x] Loading state: skeleton cards khi `isStreaming` + chưa có sources
- [x] `IntentBadge` map VN đầy đủ 7 intents
- [x] Currency format: `1.500.000 ₫` qua `Intl.NumberFormat('vi-VN', ...)`

### Verification
- [ ] Query "khách sạn 5 sao Sơn Trà" → thấy 3-5 hotel cards, rating ★, giá VND đúng, Maps link đúng (cần backend GPU)
- [ ] Query không match → empty state card, CTA reset filter
- [ ] Cards không bị overflow ngang trên màn 1366px

### Definition of Done
- [x] Code complete. Layout verified static (TypeScript clean). E2E cần GPU machine.

---

## Phase 7 — Filter sidebar (URL params) + sessions sidebar

**Goal:** User có thể filter theo district/price/rating, switch giữa các session cũ.

### Tasks
- [x] Tạo `frontend/constants/districts.ts` — 8 quận hardcoded với label + slug
- [x] Tạo `frontend/components/filters/FilterSidebar.tsx` — collapsible dropdown, district chips, rating slider, price slider, badge count
- [x] Tạo `frontend/hooks/useFilters.ts` — đọc/ghi `useSearchParams` (district, min_rating, max_price)
- [x] Tạo `frontend/components/sessions/SessionSidebar.tsx` — list session, group theo relativeDate (Hôm nay/Hôm qua/Trước đó)
- [x] Tạo `frontend/components/sessions/SessionItem.tsx` — title + context menu (rename/delete) với dialogs
- [x] Tạo `frontend/components/sessions/NewChatButton.tsx`
- [x] Tạo `frontend/hooks/useSessions.ts` — TanStack Query: `useSessionsQuery`, `useRenameSession`, `useDeleteSession`, `useMessagesQuery`
- [x] Wire filter values vào `useChat.send(text, filters)` → POST kèm `filters` vào body
- [x] Confirm dialog khi delete session (trong SessionItem)

### Verification
- [ ] Apply filter → URL update `/chat/abc?district=son-tra&min_rating=8.0` → reload trang giữ filter (cần backend)
- [ ] Filtered query trả đúng entity
- [ ] Switch session → load đúng history với sources cũ
- [ ] Rename session → list update không cần reload
- [ ] Delete → confirm → xóa thành công, redirect về `/chat`

### Definition of Done
- [x] Code complete, components compile. E2E cần GPU machine.

---

## Phase 8 — Quick replies + polish + 2-hour soak

**Goal:** Empty state đẹp, edge cases handle gọn, demo trong 2h không crash/OOM.

### Tasks
- [x] Tạo `frontend/constants/quickReplies.ts` — 6 prompts: hotel/restaurant/place/review/price/itinerary
- [x] Tạo `frontend/components/chat/QuickReplies.tsx` — grid 2 cột, click → auto submit
- [x] Welcome message: "Xin chào! Tôi là trợ lý du lịch Đà Nẵng..." trong empty state
- [x] Loading states: skeleton cards khi streaming + typing cursor ▋ trong AssistantBubble
- [x] Sonner Toaster trong root layout
- [x] "Đang chờ lượt..." — status="waiting" hiển thị "Đang chờ máy chủ..." trong AssistantBubble
- [x] Stop button: visible khi đang stream (Square icon), Send khi idle
- [x] Disable textarea khi đang stream
- [x] Keyboard: Enter to send, Esc to stop, Shift+Enter for newline
- [x] Page title "Đà Nẵng Travel Assistant" + lang="vi"
- [x] Logo / branding ở header SessionSidebar (MessageSquare icon + "Đà Nẵng Travel")
- [x] Error toasts via sonner cho SSE error event (wired vào useChat: toast.error)
- [ ] Favicon

### Verification (DEMO TEST PLAN — 7 kịch bản)
- [ ] **Kịch bản 1**: First-time visit — empty chat, 6 quick reply cards đẹp, click 1 cái → stream ngon
- [ ] **Kịch bản 2**: Apply filter (district + rating) → query → cards đúng filter, URL có params
- [ ] **Kịch bản 3**: Multi-turn "cái nào có hồ bơi?" → context được gắn → results filtered
- [ ] **Kịch bản 4**: Switch session cũ → history load đúng + sources cũ render lại
- [ ] **Kịch bản 5**: Empty results (filter quá hẹp) → bot nói thẳng + CTA reset
- [ ] **Kịch bản 6**: Stop generation → Qwen dừng < 1s, message lưu state cuối
- [ ] **Kịch bản 7**: Reload giữa stream → message marked incomplete, có thể tiếp tục

### Verification kỹ thuật
- [ ] **2-hour soak test**: gửi 1 query mỗi 5 phút → không OOM (`nvidia-smi watch`), không crash, không leak SQLite connection
- [ ] **VRAM**: `nvidia-smi` thấy không vượt quá 80% sau 24 query
- [ ] **Concurrency**: mở 2 tab gửi cùng lúc → tab 2 hiện "Đang chờ lượt...", không vỡ
- [ ] **Vietnamese rendering**: screenshot, check `ữ ặ ợ` đẹp
- [ ] **Mobile responsive (basic)**: 1024px không vỡ layout (focus desktop)

### Definition of Done
- Toàn bộ 7 kịch bản pass trong 1 lần chạy liên tục
- 2-hour soak test pass

---

## Cross-cutting checks (chạy cuối)

- [ ] `.gitignore` chứa `.env`, `data/chats.db*`, `node_modules/`, `__pycache__/`, `.next/`
- [ ] `backend/README.md` — hướng dẫn setup + chạy `uvicorn`
- [ ] `frontend/README.md` — hướng dẫn `npm install` + `npm run dev`
- [ ] Update `RUN_LOCAL.md` reference tới backend/frontend mới
- [ ] Tất cả checkbox trong file này được tick `[x]`

---

## Phase 9 — Notebook sync addendum

> Phát sinh ngoài 8 phase gốc. Theo `rule.md` R2/R5: đã hỏi và user chốt qua câu
> hỏi làm rõ trước khi làm. Đồng bộ thêm logic từ `pbl7-rag.ipynb` (bản cập nhật).

### Tasks
- [x] Backend: thêm filter `min_price` (`ChatFilters.min_price`, `_build_filter`, post-filter trong `retrieve_by_intent`)
- [x] Frontend: `min_price` vào `Filters` interface + parse URL param (`useFilters.ts`)
- [x] Frontend: slider "Giá tối thiểu" + cập nhật badge count (`FilterSidebar.tsx`)
- [x] ~~auto-parse district/min_rating hard-filter~~ → REVERT: user chốt **soft boost**.
      Gỡ `_extract_filters_from_query` + `_DISTRICT_SLUGS`; district/rating tự suy
      ra từ câu hỏi chỉ tác động qua rerank, không lọc cứng (chỉ sidebar = hard).

### Phase 9b — Sửa 4 vấn đề runtime (user báo khi chạy thật)
- [x] #3a Fix `rerank.py`: so district bằng slug 2 phía (slugify_vn) — boost cũ chết do lệch dấu
- [x] #3b Fix `retrieval.py`: gỡ auto district/rating hard-filter (→ soft qua rerank)
- [x] #2 Tinh chỉnh tốc độ: context 8→5, content 300→160 (`pipeline.py`); `DEFAULT_MAX_TOKENS` 512→384, `MAX_HISTORY_TURNS` 3→2 (`config.py`); wire config vào `build_history_messages`
- [x] #4 Fix mất tin nhắn: `useChat.ts` ghi stream thẳng vào query cache (meta seed user, done/abort ghi assistant), bỏ invalidate+setTimeout đua refetch; `useSessions.ts` `staleTime` 0→30s
- [x] #1 "list nhanh" xác nhận KHÔNG phải bug (sources gửi trước token là cố ý)

### Verification
- [x] Frontend: `npx tsc --noEmit` → 0 error
- [x] Backend: `python -m py_compile` các file đã sửa → OK
- [ ] #3: "KS tốt nhất Đà Nẵng gần Sơn Trà" (no sidebar) → Sơn Trà được boost nhưng quận khác vẫn xuất hiện (cần GPU)
- [ ] #3: sidebar district=Hải Châu → chỉ Hải Châu (explicit=hard) (cần GPU)
- [ ] #4: chat mới + chat tiếp → tin nhắn không mất, reload còn đủ (cần backend GPU)
- [ ] #2: câu trả lời gọn hơn, list source vẫn 10 mục, nhanh hơn ở lượt nhiều history (cần GPU)

---

## Reference design decisions (rationale)

| Quyết định | Lý do |
|-----------|-------|
| Next.js + FastAPI thay Gradio/Streamlit | Demo PBL cần "trông giống sản phẩm thật". Gradio/Streamlit nhìn ra ngay là tool dev. |
| SSE thay WebSocket | Chat unidirectional khi generation. SSE đơn giản hơn, browser auto-reconnect. |
| `fetch` + `ReadableStream` thay `EventSource` | EventSource không POST được body. |
| Heuristic context thay LLM rewriting | Qwen-3B 4-bit rewriting hay hallucinate entity. Cùng GPU → double TTFT. Heuristic deterministic, free. |
| URL params cho filter thay Zustand | Shareable demo links, back-button work, ít state library hơn. |
| AsyncQdrantClient thay ThreadPoolExecutor | Mixing thread + async block SSE flush. |
| Gửi `sources` trước `token` | UI render citation cards trong khi LLM stream → cảm giác nhanh, "RAG-flavored". |
| `asyncio.Lock` cho inference | 1 GPU = 1 generation. Không lock thì 2 user đồng thời → OOM. |
| Warmup ở `lifespan` | Cold first request 60-90s. Warmup chuyển cost xuống lúc start. |
| SQLite + WAL thay Postgres | Single-user demo. Zero setup, file-based. |
| JSON blob cho sources thay normalize | Write-once, không query theo field. Normalize zero benefit. |
| NFC normalize bắt buộc | Windows IME / FB copy-paste mix NFC/NFD → bge-m3 sensitive. |
| Hardcode 8 districts thay API | Đà Nẵng có 8 quận cố định, không thay đổi. |
| Hardcode quick replies | YAGNI cho demo 2h. |
| Few-shot VN trong prompt | Qwen-3B không có VN example sẽ trả tiếng Anh ~20% lượt. |
| Phase 2 (DB) trước Phase 3 (SSE) | SSE cần `message_id` để gắn streamed tokens vào row. |

---

## Out of scope (Phase 9+ nếu user mở rộng)

- Auth / multi-user
- Map embed (Leaflet/Mapbox) — tạm Google Maps URL link
- Voice input
- Image upload
- Export PDF
- Analytics + feedback (👍👎)
- Dark mode
- Mobile responsive đầy đủ
