# Da Nang Travel Chatbot - PBL7

Ung dung chatbot du lich Da Nang dung RAG: phan tich cau hoi, tim du lieu khach san/nha hang/dia diem trong Qdrant, sau do tra loi streaming qua FastAPI + Next.js.

## Kien truc hien tai

```text
Browser (http://localhost:3000)
        |
        | HTTP + SSE streaming
        v
FastAPI (http://localhost:8000)
  |- POST /api/chat/stream       chat streaming
  |- GET/POST /api/sessions      lich su hoi thoai
  |- GET/PUT/DELETE /api/profile profile theo session
  |- POST /api/recommend         goi y theo profile
  `- GET /api/health             health check
        |
        |- BAAI/bge-m3                     embedding model
        |- Qwen2.5 GGUF qua llama.cpp      analyzer + answer LLM
        |- Qdrant Cloud                    vector DB, 7 collections
        |- SQLite local                    sessions, messages, profiles
        `- Gemini fallback optional        khi retrieve khong co ket qua
```

## Can chuan bi

| Thanh phan | Bat buoc | Ghi chu |
|------------|----------|---------|
| Node.js | 20+ | Frontend Next.js 16 |
| npm | Co | Di kem Node.js |
| Python | 3.10 hoac 3.11 | Tranh 3.12+ neu package CUDA gap loi |
| GPU NVIDIA + driver | Khuyen nghi cho backend | Cau hinh demo nen co khoang 6GB VRAM tro len; khong co GPU van co the thu UI |
| CUDA/PyTorch CUDA | Khuyen nghi | Dung wheel CUDA 12.1 trong huong dan |
| Qdrant Cloud | Co cho full RAG | Can URL + API key dung voi 7 collections cua project |
| Model GGUF | Co cho backend local | Mac dinh: `backend/models/qwen2.5-3b-instruct-q4_k_m.gguf` |
| Disk trong | 10-15GB | Cho embedding cache, model GGUF, Python packages |

May hien tai can verify:

```powershell
node --version
npm --version
python --version
nvidia-smi
```

Neu `python` hoac `nvidia-smi` khong nhan, can cai Python/Add to PATH hoac cai dung NVIDIA driver truoc khi chay backend.

## Chay nhanh frontend UI

Frontend khong can GPU va co the chay khi backend chua len.

```powershell
cd frontend
npm install
npm run dev
```

Mo `http://localhost:3000`. Neu gui tin nhan khi backend chua chay, UI se bao loi ket noi API.

## Chay full stack

### 1. Tao backend env

```powershell
copy backend\.env.example backend\.env
```

Sua `backend/.env`:

```env
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
HF_TOKEN=your-huggingface-token

LLM_GGUF_PATH=models/qwen2.5-3b-instruct-q4_k_m.gguf

# Optional fallback khi Qdrant retrieve 0 ket qua
GEMINI_API_KEY=
```

Dat file GGUF tai `backend/models/qwen2.5-3b-instruct-q4_k_m.gguf`, hoac sua `LLM_GGUF_PATH` thanh duong dan that. Khong commit `.env`, API key, file DB, cache hoac model local.

### 2. Cai backend

```powershell
cd E:\University\HK2_Nam4\PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r backend/requirements.txt
```

Neu PowerShell chan activate:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 3. Chay backend

```powershell
cd backend
uvicorn app.main:app --port 8000
```

Cho den khi log co `Server ready.`. Lan dau co the mat vai phut do load embedding, GGUF, ket noi Qdrant, init SQLite va warmup pipeline.

Verify:

```powershell
curl http://localhost:8000/api/health
```

Swagger UI: `http://localhost:8000/docs`.

### 4. Chay frontend

Mo terminal moi:

```powershell
cd frontend
npm install
npm run dev
```

Mo `http://localhost:3000`.

## Cau truc thu muc

```text
PPBL_chat/
|- backend/
|  |- app/
|  |  |- api/       chat, sessions, health, profile, recommend
|  |  |- rag/       analyzer, retrieval, rerank, llama.cpp, Gemini fallback
|  |  |- db/        SQLite sessions/messages/profiles
|  |  `- utils/     NFC normalize, Vietnamese slugify
|  |- data/         chats.db tu tao, gitignored
|  |- models/       GGUF local, nen gitignore neu model lon
|  |- .env.example
|  `- README.md
|- frontend/
|  |- app/          Next.js App Router
|  |- components/   chat, filters, sessions, shadcn/ui
|  |- hooks/        useChat, useSessions, useFilters
|  |- lib/          api, SSE parser, format, utils
|  `- README.md
|- pbl7-rag.ipynb   notebook nghien cuu/prototype
|- RUN_LOCAL.md     huong dan notebook + lien ket sang app
`- plan.md          tien do du an
```

## Kiem tra nhanh

Backend unit tests khong can GPU:

```powershell
cd backend
python test_phase1.py
python test_phase2.py
pip install -r requirements-dev.txt
pytest
```

Frontend type/lint:

```powershell
cd frontend
npm run lint
npx tsc --noEmit
```

E2E can backend + Qdrant + GGUF:

- Vao `http://localhost:3000`
- Gui query: `Goi y khach san 4 sao o Son Tra`
- Ky vong: co intent badge, source cards, cau tra loi stream dan, session duoc luu.

## Tai lieu chi tiet

- Backend: [backend/README.md](backend/README.md)
- Frontend: [frontend/README.md](frontend/README.md)
- Notebook: [RUN_LOCAL.md](RUN_LOCAL.md)
