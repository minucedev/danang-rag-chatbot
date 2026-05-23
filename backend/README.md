# Backend - FastAPI RAG Server

Backend xu ly chat streaming, session history, user profile, goi y theo profile va pipeline RAG. Code hien tai dung `llama-cpp-python` de chay Qwen GGUF; LLM khong duoc load truc tiep bang HuggingFace 4-bit trong duong chay server.

## Backend dang lam gi

- Load embedding model `BAAI/bge-m3` bang `sentence-transformers`.
- Load local LLM GGUF qua `llama_cpp.Llama`.
- Dung cung LLM cho 2 viec:
  - `LLMQueryAnalyzer`: phan tich intent, rewritten query va filters truoc khi retrieve.
  - Sinh cau tra loi streaming.
- Retrieve song song tu Qdrant theo intent, rerank, dedupe, tra source cards truoc token.
- Luu sessions, messages, profiles vao SQLite `data/chats.db`.
- Optional: khi retrieve 0 ket qua va co `GEMINI_API_KEY`, fallback sang Gemini streaming.

## Yeu cau

| Thanh phan | Yeu cau |
|------------|---------|
| Python | 3.10 hoac 3.11 |
| GPU NVIDIA | Khuyen nghi, toi thieu khoang 6GB VRAM cho demo muot hon |
| CUDA/driver | Driver moi; PyTorch wheel CUDA 12.1 trong huong dan |
| RAM | 12GB+ |
| Disk | 10-15GB cho cache/model |
| Qdrant Cloud | URL + API key co du 7 collections |
| GGUF model | Mac dinh `models/qwen2.5-3b-instruct-q4_k_m.gguf` khi chay trong `backend/` |

Kiem tra:

```powershell
python --version
nvidia-smi
```

## Buoc 1 - Tao virtual environment

Chay tu thu muc goc repo:

```powershell
cd E:\University\HK2_Nam4\PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Neu PowerShell chan activate:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Buoc 2 - Tao `backend/.env`

```powershell
copy backend\.env.example backend\.env
```

Noi dung toi thieu:

```env
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
HF_TOKEN=your-huggingface-token

LLM_GGUF_PATH=models/qwen2.5-3b-instruct-q4_k_m.gguf
```

Dat model GGUF tai:

```text
backend/models/qwen2.5-3b-instruct-q4_k_m.gguf
```

Hoac tro `LLM_GGUF_PATH` den file khac. Duong dan tuong doi se duoc resolve theo working directory luc chay `uvicorn`; huong dan nay chay trong `backend/`, nen `models/...` nghia la `backend/models/...`.

## Buoc 3 - Cai packages

Phai cai PyTorch CUDA truoc de tranh pip keo nham ban CPU:

```powershell
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r backend/requirements.txt
```

Verify PyTorch:

```powershell
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

`llama-cpp-python` co the cai CPU-only tuy theo moi truong. Neu log cho thay model khong offload GPU hoac toc do qua cham, can cai lai `llama-cpp-python` voi CUDA build phu hop may cua ban, sau do giu `LLM_N_GPU_LAYERS=-1`.

## Buoc 4 - Chay server

```powershell
cd backend
uvicorn app.main:app --port 8000
```

Startup se chay cac buoc:

```text
Loading embedding model...
Loading LLM (llama.cpp)...
Connecting to Qdrant...
Initializing database...
Warming up pipeline (first GPU pass)...
Server ready.
```

Lan dau co the cham do load model/cache. Sau khi ready:

```powershell
curl http://localhost:8000/api/health
```

Swagger UI: `http://localhost:8000/docs`.

## API endpoints

| Method | URL | Mo ta |
|--------|-----|-------|
| `GET` | `/api/health` | Health check CUDA/model/Qdrant |
| `POST` | `/api/chat/stream` | Chat streaming SSE |
| `GET` | `/api/sessions` | List sessions |
| `POST` | `/api/sessions` | Tao session |
| `GET` | `/api/sessions/{id}` | Lay session |
| `GET` | `/api/sessions/{id}/messages` | Lay messages |
| `PATCH` | `/api/sessions/{id}` | Rename session |
| `DELETE` | `/api/sessions/{id}` | Xoa session |
| `GET` | `/api/profile/{session_id}` | Lay profile |
| `PUT` | `/api/profile/{session_id}` | Upsert profile |
| `DELETE` | `/api/profile/{session_id}` | Xoa profile |
| `POST` | `/api/recommend` | Goi y theo profile |

SSE chat event sequence:

```text
meta -> waiting? -> intent -> sources -> fallback? -> token* -> done
```

## Bien moi truong

| Bien | Bat buoc | Mac dinh | Mo ta |
|------|----------|----------|-------|
| `QDRANT_URL` | Co | - | URL Qdrant Cloud |
| `QDRANT_API_KEY` | Co | - | API key Qdrant |
| `HF_TOKEN` | Khuyen nghi | - | Token HuggingFace de tai `BAAI/bge-m3` on dinh hon |
| `EMBED_MODEL_NAME` | Khong | `BAAI/bge-m3` | Embedding model |
| `LLM_GGUF_PATH` | Co neu khong dat model mac dinh | `models/qwen2.5-3b-instruct-q4_k_m.gguf` | File GGUF cho llama.cpp |
| `LLM_N_CTX` | Khong | `4096` | Context window llama.cpp |
| `LLM_N_GPU_LAYERS` | Khong | `-1` | So layer offload GPU; `-1` = toi da |
| `DB_PATH` | Khong | `data/chats.db` | SQLite database |
| `DEFAULT_MAX_TOKENS` | Khong | `512` | Token toi da moi cau tra loi |
| `DEFAULT_TEMPERATURE` | Khong | `0.2` | Nhiet do generate |
| `DEFAULT_TOP_K` | Khong | `5` | Top K moi collection |
| `SCORE_THRESHOLD` | Khong | `0.3` | Nguong score Qdrant |
| `GEMINI_API_KEY` | Khong | rong | Bat Gemini fallback khi retrieve 0 ket qua |
| `GEMINI_MODEL` | Khong | `gemini-2.0-flash` | Gemini fallback model |
| `GEMINI_BASE_URL` | Khong | Google Generative Language v1beta | Endpoint fallback |
| `GEMINI_TIMEOUT_SECONDS` | Khong | `30` | Timeout fallback |
| `GEMINI_FALLBACK_PREFIX_DISCLAIMER` | Khong | `true` | Chen disclaimer khi fallback |
| `HF_HOME` | Khong | HuggingFace default | Cache model, nen dung path ngan tren Windows |

## Tests

Smoke/unit cu:

```powershell
cd backend
python test_phase1.py
python test_phase2.py
```

Pytest suite moi:

```powershell
cd backend
pip install -r requirements-dev.txt
pytest
```

Mot so test khong can GPU vi mock pipeline/Qdrant. E2E chat that can Qdrant credentials, GGUF va backend ready.

## Troubleshooting

### `python` khong nhan lenh

Cai Python 3.10/3.11 va tick `Add Python to PATH`, hoac dung Python Launcher:

```powershell
py -3.11 --version
```

### `QDRANT_URL` missing

`backend/.env` chua ton tai hoac chay server sai working directory.

```powershell
ls backend\.env
```

Chay theo huong dan: `cd backend` roi `uvicorn app.main:app --port 8000`.

### `401 Unauthorized` tu Qdrant

Sai `QDRANT_API_KEY` hoac URL cluster. Lay lai key trong Qdrant Cloud dashboard.

### Khong tim thay GGUF

Loi thuong gap:

```text
ValueError: Failed to load model from file
```

Kiem tra:

```powershell
ls backend\models
```

Neu file nam o noi khac, sua `LLM_GGUF_PATH` trong `backend/.env`.

### Llama.cpp chay CPU qua cham

`llama-cpp-python` co the dang la CPU build. Cai lai ban co CUDA support phu hop moi truong cua ban, giu:

```env
LLM_N_GPU_LAYERS=-1
```

### CUDA false voi PyTorch

Thuong la cai nham PyTorch CPU:

```powershell
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu121
python -c "import torch; print(torch.cuda.is_available())"
```

### Windows path qua dai

Dung cache ngan:

```env
HF_HOME=D:\hf_cache
```

```powershell
mkdir D:\hf_cache
```

### Gemini fallback khong hoat dong

Neu muon fallback, dat `GEMINI_API_KEY`. Neu de rong, pipeline se bo qua Gemini va dung local LLM theo du lieu retrieve duoc.
