# Chay local: app full stack va notebook

Repo nay co 2 cach chay:

1. **App full stack**: backend FastAPI + frontend Next.js. Day la duong chay demo hien tai.
2. **Notebook `pbl7-rag.ipynb`**: prototype/nghien cuu goc. Notebook co the lech voi runtime app neu chua sync lai.

Neu muc tieu la demo san pham, uu tien chay app full stack theo README goc va README backend/frontend.

## 1. Chay app full stack

### Can chuan bi

- Python 3.10/3.11.
- Node.js 20+ va npm.
- Qdrant URL + API key.
- File GGUF cho local LLM, mac dinh:

```text
backend/models/qwen2.5-3b-instruct-q4_k_m.gguf
```

- GPU NVIDIA/CUDA neu muon backend chay duoc toc do demo. Khong co GPU van co the chay frontend UI rieng.

### Backend

```powershell
cd E:\University\HK2_Nam4\PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r backend/requirements.txt

copy backend\.env.example backend\.env
```

Sua `backend/.env`:

```env
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
HF_TOKEN=your-huggingface-token
LLM_GGUF_PATH=models/qwen2.5-3b-instruct-q4_k_m.gguf
```

Chay:

```powershell
cd backend
uvicorn app.main:app --port 8000
```

Verify:

```powershell
curl http://localhost:8000/api/health
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Mo `http://localhost:3000`.

## 2. Chay notebook `pbl7-rag.ipynb`

Notebook duoc tao cho moi truong Kaggle/Colab prototype. No khong phai entrypoint chinh cua app FastAPI hien tai.

### Yeu cau

| Thanh phan | Toi thieu | Khuyen nghi |
|------------|-----------|-------------|
| GPU NVIDIA | 6GB VRAM | 8GB+ |
| RAM | 12GB | 16GB+ |
| Disk trong | 10GB | 15GB+ |
| Python | 3.10/3.11 | 3.11 |

### Tao env cho notebook

```powershell
cd E:\University\HK2_Nam4\PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install jupyterlab ipykernel
python -m ipykernel install --user --name pbl7-rag --display-name "PBL7 RAG"
```

### Notebook `.env`

Neu notebook doc `.env` o thu muc goc, tao `PPBL_chat/.env`:

```env
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
HF_TOKEN=your-huggingface-token
```

Neu cell notebook van doc Kaggle Secrets, them `load_dotenv()` vao cell import:

```python
from dotenv import load_dotenv
load_dotenv()

if os.getenv("HF_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.getenv("HF_TOKEN")
```

### Mo notebook

VS Code:

1. Mo folder `PPBL_chat`.
2. Mo `pbl7-rag.ipynb`.
3. Select Kernel -> `PBL7 RAG`.
4. Run All.

JupyterLab:

```powershell
jupyter lab
```

## 3. Checklist truoc demo

- [ ] `node --version` >= 20.
- [ ] `python --version` la 3.10/3.11.
- [ ] `nvidia-smi` thay GPU neu chay backend local.
- [ ] `backend/.env` co `QDRANT_URL`, `QDRANT_API_KEY`, `LLM_GGUF_PATH`.
- [ ] File GGUF ton tai o duong dan `LLM_GGUF_PATH`.
- [ ] `curl http://localhost:8000/api/health` tra JSON.
- [ ] `npm run dev` frontend ready o `http://localhost:3000`.
- [ ] Gui query tren UI co source cards va answer streaming.

## 4. Troubleshooting nhanh

### Backend bao khong co Qdrant env

Kiem tra `backend/.env` ton tai va chay server tu `backend/`:

```powershell
cd backend
uvicorn app.main:app --port 8000
```

### Backend khong load duoc GGUF

Kiem tra file:

```powershell
ls backend\models
```

Neu dung duong dan khac, sua `LLM_GGUF_PATH`.

### Frontend bao Loi chat

Backend chua ready hoac `frontend/.env.local` sai:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Notebook va app cho ket qua khac nhau

Day la binh thuong neu notebook chua sync voi code app. App hien tai dung FastAPI + llama.cpp GGUF + LLMQueryAnalyzer + SQLite sessions/profiles; notebook la prototype/doc nghien cuu.
