"""Trang vỏ /admin — gộp dashboard Crawl + Metrics vào 1 màn hình, switch bằng tab.

Nhúng 2 dashboard sẵn có (/admin/crawl/, /admin/metrics/) bằng iframe (cùng origin → JS/SSE/CSS
của chúng chạy nguyên). Iframe metrics lazy-load lần đầu bấm sang tab Metrics.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_SHELL_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Admin — Đà Nẵng RAG</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; font-family: Inter, system-ui, Arial, sans-serif; }
    .tabbar {
      display: flex; align-items: center; gap: 8px;
      height: 52px; padding: 0 16px; background: #0f172a; border-bottom: 1px solid #1e293b;
    }
    .tabbar .brand { color: #e2e8f0; font-weight: 700; margin-right: auto; font-size: 15px; }
    .tabbar button {
      padding: 8px 18px; border: 0; border-radius: 8px; cursor: pointer;
      font-weight: 600; font-size: 14px; transition: background .15s, color .15s;
    }
    .tabbar button.active { background: #2563eb; color: #fff; }
    .tabbar button:not(.active) { background: #1e293b; color: #94a3b8; }
    .tabbar button:not(.active):hover { background: #334155; color: #cbd5e1; }
    iframe { border: 0; width: 100%; height: calc(100vh - 52px); display: block; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <div class="tabbar">
    <span class="brand">🛠️ Admin — Đà Nẵng RAG</span>
    <button id="t-crawl" class="active" onclick="show('crawl')">🕷️ Crawl</button>
    <button id="t-metrics" onclick="show('metrics')">📊 Metrics</button>
  </div>

  <iframe id="f-crawl" src="/admin/crawl/" title="Crawl Admin"></iframe>
  <iframe id="f-metrics" class="hidden" title="Metrics Admin"></iframe>

  <script>
    const frames = { crawl: document.getElementById("f-crawl"), metrics: document.getElementById("f-metrics") };
    const tabs = { crawl: document.getElementById("t-crawl"), metrics: document.getElementById("t-metrics") };
    // Lazy-load: chỉ gán src cho iframe metrics lần đầu mở (tránh SSE/log metrics kết nối sớm).
    const SRC = { crawl: "/admin/crawl/", metrics: "/admin/metrics/" };

    function show(mode) {
      for (const key of ["crawl", "metrics"]) {
        const on = key === mode;
        if (on && !frames[key].src) frames[key].src = SRC[key];
        frames[key].classList.toggle("hidden", !on);
        tabs[key].classList.toggle("active", on);
      }
    }
  </script>
</body>
</html>
"""


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/", response_class=HTMLResponse)
async def admin_shell() -> HTMLResponse:
    return HTMLResponse(_SHELL_HTML)
