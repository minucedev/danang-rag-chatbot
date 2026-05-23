# Frontend - Next.js Chat UI

Frontend la giao dien chatbot du lich Da Nang: session sidebar, filter dropdown, quick replies, source cards va chat streaming qua SSE.

## Stack

- Next.js `16.2.4` App Router
- React `19.2.4`
- TypeScript
- Tailwind CSS 4
- Radix/shadcn-style UI components
- TanStack Query
- `fetch` + `ReadableStream` de doc SSE POST stream

## Yeu cau

- Node.js `20+`
- npm
- Backend FastAPI neu muon chat that

Kiem tra:

```powershell
node --version
npm --version
```

## Cai dat

```powershell
cd frontend
npm install
```

## Cau hinh backend URL

File `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Neu backend chay tren may GPU rieng:

```env
NEXT_PUBLIC_API_URL=http://192.168.1.100:8000
```

Backend hien chi allow CORS mac dinh cho:

```text
http://localhost:3000
http://127.0.0.1:3000
```

Neu frontend chay tu host/IP khac, can them origin trong `backend/app/main.py`.

## Chay dev server

```powershell
npm run dev
```

Mo `http://localhost:3000`.

Frontend co the render khi backend chua chay. Gui tin nhan luc nay se hien toast loi ket noi.

## Scripts

| Lenh | Mo ta |
|------|-------|
| `npm run dev` | Chay Next dev server |
| `npm run build` | Build production |
| `npm run start` | Chay production sau build |
| `npm run lint` | Chay ESLint |
| `npx tsc --noEmit` | Type-check TypeScript |

## Luong chat

1. `useChat` goi `POST /api/chat/stream` voi body:

```json
{
  "session_id": "optional-session-id",
  "message": "Goi y khach san 4 sao o Son Tra",
  "filters": {
    "district": "son tra",
    "min_rating": 8,
    "min_price": 500000,
    "max_price": 2000000
  }
}
```

2. Frontend doc SSE events:

```text
meta -> waiting? -> intent -> sources -> fallback? -> token* -> done
```

3. `meta` tra session/message IDs; frontend ghi thang vao TanStack Query cache de tranh mat tin nhan khi rerender.
4. `sources` render source cards truoc khi token ve.
5. `token` append vao assistant bubble.
6. `done` finalize message.

## Cau truc thu muc

```text
frontend/
|- app/
|  |- layout.tsx        Inter Vietnamese font, providers, toaster
|  |- page.tsx          redirect sang /chat
|  `- chat/
|     |- layout.tsx     shell voi SessionSidebar
|     |- page.tsx       new chat + quick replies
|     `- [sessionId]/   chat session view
|- components/
|  |- chat/             input, message list, source cards, intent badge
|  |- filters/          FilterSidebar
|  |- sessions/         session list, rename/delete, new chat
|  `- ui/               local UI primitives
|- hooks/
|  |- useChat.ts        SSE stream + abort + status
|  |- useSessions.ts    TanStack Query cho sessions/messages
|  `- useFilters.ts     URL search params
|- lib/
|  |- api.ts            REST fetch wrapper
|  |- sse.ts            SSE parser cho POST stream
|  |- nfc.ts            normalize input tieng Viet
|  |- format.ts         VND, intent labels, relative date
|  `- utils.ts          cn()
`- constants/
   |- districts.ts
   `- quickReplies.ts
```

## Tinh nang UI

| Tinh nang | Mo ta |
|-----------|-------|
| Quick replies | 6 cau goi y o empty state |
| Streaming | Assistant bubble hien token dan |
| Intent badge | Hien intent nhu Khach san, Nha hang, Dia diem cu the |
| Source cards | Ten, quan, rating, gia, dia chi, Google Maps link |
| Filters | District, min rating, min price, max price; luu tren URL |
| Session history | List/rename/delete sessions |
| Stop generation | AbortController dung stream |
| Multi-turn | Gui tiep trong session cu, backend lay history |

## Verify voi backend

```powershell
curl http://localhost:8000/api/health
```

Sau do mo UI va gui:

```text
Goi y khach san 4 sao o Son Tra
```

Ky vong:

- Co intent badge.
- Co source cards.
- Cau tra loi stream dan.
- Sidebar co session moi.
- Reload `/chat/{sessionId}` van co history.

## Troubleshooting

### `node_modules` missing

```powershell
npm install
```

### Toast "Loi chat"

Backend chua chay, backend chua `Server ready.`, hoac `NEXT_PUBLIC_API_URL` sai.

### CORS error

Dam bao frontend chay dung `http://localhost:3000` hoac them origin vao backend CORS.

### Trang trang/hydration issue

Xoa cache Next:

```powershell
Remove-Item -Recurse -Force .next
npm run dev
```

### Font tieng Viet khong dung

Next dung `Inter` voi subset `vietnamese`. Neu build lan dau bi chan mang khi tai font, chay lai `npm run dev` sau khi co mang.
