# Hướng dẫn chạy `pbl7-rag.ipynb` trên máy local

Notebook này được build cho Kaggle. Tài liệu này mô tả các bước cần thiết để kéo về chạy trên máy có GPU NVIDIA, vẫn giữ nguyên format `.ipynb`.

---

## 1. Yêu cầu phần cứng

| Thành phần | Tối thiểu | Khuyến nghị |
|------------|-----------|-------------|
| GPU NVIDIA (CUDA) | VRAM 6GB | VRAM ≥ 8GB |
| RAM hệ thống | 12GB | 16GB |
| Disk trống | 10GB | 15GB (cho HF cache) |
| Driver NVIDIA | ≥ 525.x | mới nhất |

> Tham khảo: Qwen2.5-3B 4-bit ≈ 2.5GB VRAM + bge-m3 ≈ 2.3GB VRAM + buffer cho inference.

**Không có GPU NVIDIA → không chạy được** (`bitsandbytes` 4-bit yêu cầu CUDA).

---

## 2. Cài đặt môi trường

### 2.1. Python
- Cài **Python 3.10** hoặc **3.11** (tránh 3.12+ vì một số package chưa stable trên 3.12).
- Trên Windows: tải từ python.org, tick **"Add Python to PATH"** khi cài.

### 2.2. CUDA Toolkit
- Cài **CUDA 12.1** (khớp với PyTorch wheel ở bước 2.4).
- Verify: chạy `nvidia-smi` trong terminal, phải thấy GPU và CUDA version.

### 2.3. Tạo virtual environment

**Linux / macOS:**
```bash
cd /path/to/PPBL_chat
python3.11 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
cd E:\University\HK2_Nam4\PPBL_chat
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Nếu PowerShell báo lỗi execution policy:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### 2.4. Cài PyTorch với CUDA
**Phải cài PyTorch CUDA TRƯỚC khi cài các package khác**, không thì pip kéo bản CPU.

```bash
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Verify:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
→ Phải in ra `True` và tên GPU.

### 2.5. Cài Jupyter (để mở notebook)
```bash
pip install jupyterlab ipykernel
python -m ipykernel install --user --name pbl7-rag --display-name "PBL7 RAG"
```

Hoặc dùng **VS Code** với extension Jupyter (khuyên dùng trên Windows).

### 2.6. Các package còn lại
**Không cần cài thủ công** — Cell 1 của notebook sẽ tự `pip install` khi chạy lần đầu (mất ~5 phút).

Các package sẽ được cài: `qdrant-client`, `sentence-transformers`, `transformers`, `accelerate`, `bitsandbytes`, `python-dotenv`, `pandas`, `langchain`, `langchain-community`.

---

## 3. Cấu hình Qdrant + HuggingFace

### 3.1. Tạo file `.env`
Tạo file `.env` ở **cùng thư mục với notebook** (`PPBL_chat/.env`):

```
QDRANT_URL=https://511742a9-e9a3-4261-91dd-5dbb998f21a7.us-west-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=<dán api key từ Qdrant Cloud dashboard>
HF_TOKEN=<token huggingface, optional nhưng khuyên dùng>
```

> ⚠️ Thêm `.env` vào `.gitignore` — KHÔNG commit file này.

### 3.2. HuggingFace token (optional)
- Tạo token tại https://huggingface.co/settings/tokens (chỉ cần quyền `read`).
- Có token → tránh rate-limit khi tải model lần đầu.

---

## 4. Chỉnh sửa notebook (1 thay đổi nhỏ)

Notebook hiện tại đọc credential từ Kaggle Secrets. Code đã có **fallback đọc env var**, chỉ cần thêm `load_dotenv()` để đọc file `.env`.

### Mở `pbl7-rag.ipynb`, sửa **Cell 2**:

Tìm dòng đầu cell 2 (sau block import `from langchain_core.callbacks import ...`) và thêm:

```python
from dotenv import load_dotenv
load_dotenv()  # Load .env nếu có (no-op nếu không tồn tại)

# (Optional) forward HF_TOKEN cho HuggingFace library
if os.getenv("HF_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.getenv("HF_TOKEN")
```

**Không cần đổi bất kỳ cell nào khác.** Logic intent detection, retrieval, reranking, LLM giữ nguyên.

---

## 5. Chạy notebook

### Cách 1: VS Code
1. Mở thư mục `PPBL_chat` trong VS Code.
2. Mở `pbl7-rag.ipynb`.
3. Click "Select Kernel" góc phải trên → chọn `.venv` vừa tạo.
4. **Run All**.

### Cách 2: JupyterLab
```bash
jupyter lab
```
→ Mở notebook trong trình duyệt → Kernel → chọn `PBL7 RAG` → Run All.

---

## 6. Verify từng bước

Chạy lần lượt và kiểm tra output:

| Cell | Output mong đợi | Nếu lỗi |
|------|-----------------|---------|
| 1 | `Packages ready.` | Network, hoặc Python version sai |
| 2 | `Qdrant URL: https://...` + `CUDA available: True` | `False` → bước 2.4 sai. Thiếu URL → file `.env` chưa load được |
| 3 | Không có output (chỉ define class) | — |
| 4 | Tải bge-m3 (~2.3GB lần đầu), không lỗi | `401 Unauthorized` → `QDRANT_API_KEY` sai. `Connection refused` → URL sai |
| 5 | `Local LLM ready: Qwen/Qwen2.5-3B-Instruct` | `CUDA out of memory` → đóng app khác. `bitsandbytes` lỗi → xem mục 7 |
| 6 | `RAG Pipeline initialized successfully!` | — |
| 7 | Demo 9 query, mỗi query in intent + answer + top results | — |
| 8 | Demo filtered search | — |

### Test nhanh sau cell 4
```python
print(client.get_collections())   # phải list 7 collections
print(encoder.encode(["test"]).shape)  # (1, 1024)
```

---

## 7. Troubleshooting

### `bitsandbytes` lỗi trên Windows
```
RuntimeError: CUDA Setup failed despite GPU being available
```
**Fix:**
```bash
pip install -U bitsandbytes
```
Nếu vẫn lỗi:
```bash
pip uninstall bitsandbytes -y
pip install bitsandbytes --no-cache-dir
```

### `CUDA out of memory` khi load Qwen
- Đóng các app chiếm VRAM (Chrome với hardware acceleration, game, Photoshop...)
- Hoặc đổi model nhỏ hơn — sửa cell 2:
  ```python
  LOCAL_LLM_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
  ```

### HF rate-limit (`429 Too Many Requests`)
- Đặt `HF_TOKEN` trong `.env` (xem mục 3.2).
- Hoặc tải model trước bằng CLI:
  ```bash
  huggingface-cli download Qwen/Qwen2.5-3B-Instruct
  huggingface-cli download BAAI/bge-m3
  ```

### Long Path lỗi trên Windows
```
OSError: [WinError 206] The filename or extension is too long
```
**Fix 1:** Bật Long Path trong Registry:
```
HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1
```

**Fix 2:** Đổi HF cache sang path ngắn — thêm vào `.env`:
```
HF_HOME=D:\hf_cache
```

### Qdrant timeout
Trong cell 4, đổi:
```python
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)
```
thành:
```python
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=120)
```

---

## 8. Thời gian ước tính

| Bước | Thời gian |
|------|-----------|
| Cài CUDA + Python + venv + PyTorch | 30-45 phút (lần đầu) |
| Cell 1 (cài packages) | ~5 phút (lần đầu), <5s sau đó |
| Cell 4-5 (tải models) | ~10-15 phút (lần đầu), ~1 phút sau đó |
| Cell 7 demo (9 queries) | ~3-5 phút |

**Lần chạy thứ 2 trở đi:** ~2 phút khởi động (model load từ cache).

---

## 9. Checklist cuối cùng trước khi Run All

- [ ] `nvidia-smi` thấy GPU
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` → `True`
- [ ] File `.env` tồn tại trong `PPBL_chat/`, có `QDRANT_URL` + `QDRANT_API_KEY`
- [ ] Đã thêm `load_dotenv()` vào đầu cell 2
- [ ] Kernel của notebook đang trỏ đúng vào `.venv`
- [ ] `.env` đã được thêm vào `.gitignore`
