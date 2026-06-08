"""Router qdrant-admin — gắn vào /admin/qdrant. Xem dữ liệu Qdrant qua 1 file snapshot.

Trang đọc từ file snapshot (backend/data/qdrant_snapshot.json) → xem nhanh, không cần Qdrant.
Nút "Cập nhật" gọi POST /api/update → tạo AsyncQdrantClient on-demand (KHÔNG nạp model), scroll
tối đa N điểm/collection (không lấy vector), ghi đè file atomic. Static mount ở main.py/admin_app.py.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from qdrant_client import AsyncQdrantClient
from starlette.requests import Request

from app import config as backend_config

logger = logging.getLogger("app.api.qdrant_admin")

router = APIRouter(prefix="/admin/qdrant", tags=["qdrant-admin"])

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "qdrant_admin" / "templates")
)

# __file__ = backend/app/api/qdrant_admin.py → parents[2] = backend/
_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "qdrant_snapshot.json"

# Dashboard ở cổng public 8000. Bật cờ này để route GHI (update) cần x-admin-token = ADMIN_TOKEN.
# Mặc định MỞ (đã có cổng cookie admin gác /admin*).
_REQUIRE_TOKEN = os.getenv("QDRANT_ADMIN_REQUIRE_TOKEN", "false").lower() in ("1", "true", "yes")


def _require_write_auth(x_admin_token: str | None = Header(default=None)) -> None:
    if not _REQUIRE_TOKEN:
        return
    if not backend_config.ADMIN_TOKEN or x_admin_token != backend_config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Qdrant admin write disabled or bad token")


# ── Helpers thuần (test được) ────────────────────────────────────────────────
def _read_snapshot() -> Optional[dict]:
    """Đọc file snapshot. Trả None nếu chưa có / hỏng (degrade an toàn cho trang)."""
    if not _SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("đọc snapshot Qdrant thất bại: %s", exc)
        return None


def _paginate(points: list, offset: int, limit: int) -> list:
    """Cắt trang an toàn: offset/limit âm hoặc vượt biên → trả [] / phần còn lại."""
    if offset < 0:
        offset = 0
    if limit <= 0:
        return []
    return points[offset:offset + limit]


def _count_by(points: list, field: str, split: bool = False, top: Optional[int] = None) -> list:
    """Đếm số điểm theo payload[field]. Bỏ rỗng/None. split=True tách chuỗi nhiều giá trị theo
    dấu ',' hoặc ';' (vd cuisine). Trả [{key,count}] giảm dần; nếu `top` → cắt + gộp 'Khác'."""
    counts: dict[str, int] = {}
    for p in points:
        raw = (p.get("payload") or {}).get(field)
        if raw is None or raw == "":
            continue
        values = raw if isinstance(raw, list) else [raw]
        parts: list[str] = []
        for v in values:
            s = str(v).strip()
            if not s:
                continue
            if split:
                parts.extend(seg.strip() for seg in re.split(r"[,;]", s) if seg.strip())
            else:
                parts.append(s)
        for key in parts:
            counts[key] = counts.get(key, 0) + 1
    items = sorted(({"key": k, "count": c} for k, c in counts.items()), key=lambda x: -x["count"])
    if top is not None and len(items) > top:
        head = items[:top]
        rest = sum(it["count"] for it in items[top:])
        if rest:
            head.append({"key": "Khác", "count": rest})
        return head
    return items


def _rating_hist(points: list, field: str = "rating") -> list:
    """Histogram điểm đánh giá: gộp theo round(rating) (hợp mọi thang /10 hay 1–5). Bỏ giá trị
    thiếu/không phải số. Trả [{bucket,count}] tăng dần theo bucket."""
    buckets: dict[int, int] = {}
    for p in points:
        v = (p.get("payload") or {}).get(field)
        if v is None or isinstance(v, bool):
            continue
        try:
            b = round(float(v))
        except (TypeError, ValueError):
            continue
        buckets[b] = buckets.get(b, 0) + 1
    return [{"bucket": b, "count": buckets[b]} for b in sorted(buckets)]


def _collection_stats(col: dict, name: str) -> dict:
    """Thống kê phân bố cho 1 collection từ mẫu điểm đã lưu (col['points'])."""
    points = col.get("points", [])
    special = None
    if name == "restaurants_danang":
        # Dùng restaurant_type (sạch: "Nhà hàng, Buffet, Café/Dessert…") thay vì cuisine
        # (field cuisine của Foody trộn lẫn món + đối tượng phù hợp, không gọn để thống kê).
        special = {"label": "Loại hình", "items": _count_by(points, "restaurant_type", split=True, top=10)}
    elif name == "accommodation_hotels_danang":
        items = [{"key": f"{b['bucket']} sao", "count": b["count"]}
                 for b in _rating_hist(points, "star_rating")]
        special = {"label": "Hạng sao", "items": items}
    return {
        "name": name,
        "total": col.get("total", 0),
        "stored": col.get("stored", len(points)),
        "by_district": _count_by(points, "district", top=12),
        "rating_hist": _rating_hist(points, "rating"),
        "special": special,
    }


def _overview(snap: Optional[dict]) -> dict:
    """Tổng quan (không kèm points) cho trang chính."""
    if not snap:
        return {"updated_at": None, "max_per_collection": None, "collections": []}
    cols = [
        {
            "name": name,
            "total": c.get("total", 0),
            "stored": c.get("stored", len(c.get("points", []))),
            "error": c.get("error"),
        }
        for name, c in (snap.get("collections") or {}).items()
    ]
    return {
        "updated_at": snap.get("updated_at"),
        "max_per_collection": snap.get("max_per_collection"),
        "collections": cols,
    }


def _write_snapshot(snap: dict) -> None:
    """Ghi atomic (.tmp → replace) để lần Update lỗi giữa chừng không làm hỏng file cũ."""
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_SNAPSHOT_PATH)


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _TEMPLATES.TemplateResponse(request, "index.html", {})


@router.get("/api/snapshot")
async def api_snapshot():
    """Tổng quan các collection từ file snapshot (không gọi Qdrant)."""
    return _overview(_read_snapshot())


@router.get("/api/collections/{collection}/points")
async def api_points(collection: str, offset: int = 0, limit: int = 50):
    """Duyệt payload từng điểm của 1 collection (đọc từ file snapshot, phân trang)."""
    snap = _read_snapshot()
    col = (snap or {}).get("collections", {}).get(collection) if snap else None
    if col is None:
        raise HTTPException(status_code=404, detail="Chưa có snapshot cho collection này — bấm Cập nhật")
    points = col.get("points", [])
    return {
        "name": collection,
        "total": col.get("total", 0),
        "stored": col.get("stored", len(points)),
        "offset": offset,
        "limit": limit,
        "points": _paginate(points, offset, limit),
    }


@router.get("/api/collections/{collection}/stats")
async def api_stats(collection: str):
    """Thống kê phân bố (quận, rating, đặc thù) của 1 collection — từ mẫu trong file snapshot."""
    snap = _read_snapshot()
    col = (snap or {}).get("collections", {}).get(collection) if snap else None
    if col is None:
        raise HTTPException(status_code=404, detail="Chưa có snapshot cho collection này — bấm Cập nhật")
    return _collection_stats(col, collection)


@router.post("/api/update")
async def api_update(_: None = Depends(_require_write_auth)):
    """Lấy lại dữ liệu từ Qdrant (tối đa N điểm/collection, bỏ vector) rồi ghi đè file snapshot.

    Lỗi kết nối Qdrant → 502, file snapshot cũ giữ nguyên (chỉ replace khi build xong).
    """
    cap = backend_config.QDRANT_SNAPSHOT_MAX_PER_COLLECTION
    client = AsyncQdrantClient(
        url=backend_config.QDRANT_URL, api_key=backend_config.QDRANT_API_KEY, timeout=20
    )
    try:
        # Kiểm tra kết nối 1 lần (fail nhanh thay vì timeout từng collection).
        try:
            existing = {c.name for c in (await client.get_collections()).collections}
        except Exception as exc:
            logger.error("Update Qdrant: không kết nối được: %s", exc)
            raise HTTPException(status_code=502, detail=f"Không kết nối được Qdrant: {exc}")

        collections: dict = {}
        for name in backend_config.ALL_COLLECTIONS:
            if name not in existing:
                collections[name] = {"total": 0, "stored": 0, "points": [], "error": "collection không tồn tại"}
                continue
            total = (await client.count(collection_name=name, exact=True)).count
            points: list = []
            next_off = None
            while len(points) < cap:
                batch, next_off = await client.scroll(
                    collection_name=name,
                    limit=min(256, cap - len(points)),
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not batch:
                    break
                for p in batch:
                    points.append({"id": str(p.id), "payload": p.payload or {}})
                if next_off is None:
                    break
            collections[name] = {"total": total, "stored": len(points), "points": points}

        snap = {"updated_at": int(time.time()), "max_per_collection": cap, "collections": collections}
        _write_snapshot(snap)
        return _overview(snap)
    finally:
        await client.close()
