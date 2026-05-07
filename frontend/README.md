# Frontend — Next.js Chat UI

Giao diện chatbot du lịch Đà Nẵng: session sidebar, filter sidebar, streaming chat với source cards.

---

## Yêu cầu

- **Node.js 20+** — kiểm tra: `node --version`
- **npm** — đi kèm với Node.js

GPU không cần thiết để chạy frontend.

---

## Bước 1 — Cài packages

```powershell
cd frontend
npm install
```

Mất ~1-2 phút lần đầu.

---

## Bước 2 — Cấu hình backend URL

File `.env.local` đã có sẵn với giá trị mặc định:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Trường hợp backend chạy trên máy khác (ví dụ GPU server riêng):**

Sửa `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://192.168.1.100:8000
```

Thay `192.168.1.100` bằng IP thật của máy chạy backend.

> Backend phải cho phép CORS từ địa chỉ frontend. Mặc định đã cấu hình cho `localhost:3000`.  
> Nếu frontend chạy trên máy khác, cần sửa `backend/app/main.py` → `allow_origins` thêm IP của máy frontend.

---

## Bước 3 — Chạy dev server

```powershell
npm run dev
```

Mở `http://localhost:3000` trong trình duyệt.

Server khởi động trong ~1 giây. Terminal hiện:
```
▲ Next.js 16.x.x (Turbopack)
- Local:  http://localhost:3000
✓ Ready in 651ms
```

---

## Chạy không có backend

Frontend render hoàn toàn mà không cần backend:
- Giao diện hiển thị đầy đủ: session sidebar, quick replies, filter sidebar
- Gửi tin nhắn → toast đỏ "Lỗi chat" (network error vì backend không có)
- Dùng để review UI, screenshot, demo layout

---

## Cấu trúc thư mục

```
frontend/
├── app/
│   ├── layout.tsx              ← root layout: Inter font VN, providers, toast
│   ├── page.tsx                ← redirect → /chat
│   ├── providers.tsx           ← QueryClientProvider (TanStack Query)
│   └── chat/
│       ├── layout.tsx          ← 2-column: SessionSidebar + main
│       ├── page.tsx            ← empty state + quick replies
│       └── [sessionId]/
│           └── page.tsx        ← chat session view
├── components/
│   ├── chat/
│   │   ├── ChatInput.tsx       ← textarea, Enter/Stop button
│   │   ├── MessageList.tsx     ← auto-scroll message list
│   │   ├── MessageBubble.tsx   ← user (blue) & assistant (markdown)
│   │   ├── IntentBadge.tsx     ← "Khách sạn", "Nhà hàng", ...
│   │   ├── SourceCard.tsx      ← card: tên, quận, rating, giá, Maps link
│   │   ├── SourceCardList.tsx  ← horizontal scroll, expand/collapse
│   │   └── QuickReplies.tsx    ← 6 quick reply cards
│   ├── filters/
│   │   └── FilterSidebar.tsx   ← dropdown: district chips, rating/price slider
│   ├── sessions/
│   │   ├── SessionSidebar.tsx  ← danh sách session nhóm theo ngày
│   │   ├── SessionItem.tsx     ← rename/delete dialog
│   │   └── NewChatButton.tsx
│   └── ui/                     ← shadcn/ui components
├── hooks/
│   ├── useChat.ts              ← SSE stream, abort, status machine
│   ├── useSessions.ts          ← TanStack Query: list/rename/delete
│   └── useFilters.ts           ← URL search params: district/rating/price
├── lib/
│   ├── api.ts                  ← fetch wrapper với base URL
│   ├── sse.ts                  ← async generator đọc SSE stream
│   ├── nfc.ts                  ← NFC normalize input tiếng Việt
│   ├── format.ts               ← formatVND, intentLabel, relativeDate
│   └── utils.ts                ← cn() helper (clsx + tailwind-merge)
├── constants/
│   ├── districts.ts            ← 8 quận Đà Nẵng (label + slug)
│   └── quickReplies.ts         ← 6 quick reply prompts
├── .env.local                  ← NEXT_PUBLIC_API_URL (không commit)
└── next.config.ts
```

---

## Tính năng giao diện

| Tính năng | Mô tả |
|-----------|-------|
| **Quick replies** | 6 câu hỏi gợi ý khi vào lần đầu. Click để tự động gửi |
| **Streaming** | Câu trả lời hiện ra từng từ theo thời gian thực |
| **Intent badge** | Hiện "Đang tìm: Khách sạn / Nhà hàng / Địa điểm..." trong khi xử lý |
| **Source cards** | Card kết quả: tên, quận, rating ★, giá VND, link Google Maps |
| **Filter sidebar** | Lọc theo quận, đánh giá tối thiểu, giá tối đa. Filter lưu vào URL |
| **Session history** | Lịch sử hội thoại nhóm theo Hôm nay / Hôm qua / Trước đó |
| **Rename / Delete** | Đổi tên hoặc xóa session qua context menu |
| **Stop generation** | Nút Stop (■) dừng LLM đang stream |
| **Multi-turn** | Bot nhớ context từ các tin nhắn trước trong cùng session |

---

## Troubleshooting

### Trang trắng hoặc lỗi `hydration`

```powershell
# Xóa cache Next.js và build lại
rm -rf .next
npm run dev
```

### `ENOENT: node_modules not found`

```powershell
npm install
```

### Toast "Lỗi chat" ngay khi gửi message

Backend chưa chạy hoặc URL sai. Kiểm tra:
1. `curl http://localhost:8000/api/health` phải trả JSON
2. `NEXT_PUBLIC_API_URL` trong `.env.local` phải đúng

### CORS error trong console trình duyệt

```
Access to fetch at 'http://localhost:8000' from origin 'http://localhost:3000' has been blocked by CORS
```

Backend đang block. Thường do backend chưa khởi động hoàn toàn. Chờ "Server ready." trong terminal backend.

### Font tiếng Việt bị vỡ (không render dấu)

Xảy ra nếu mạng bị firewall block Google Fonts. Next.js tự host font, không cần mạng sau lần build đầu. Chạy `npm run dev` lại để download font.
