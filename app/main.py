"""FastAPI 應用程式進入點。

啟動方式：
    python -m uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.etf_routes import router as etf_router
from app.api.routes import router
from app.db import init_schema


@asynccontextmanager
async def lifespan(app):
    init_schema()
    yield


app = FastAPI(title="台股三大法人類股資金流向", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.include_router(etf_router)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """靜態檔不快取，避免修改前端後瀏覽器仍載入舊版。"""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def asset_version():
    """以前端檔案的更新時間作為版本，避免瀏覽器沿用舊的快取。"""
    files = [config.STATIC_DIR / "style.css", config.STATIC_DIR / "app.js"]
    return str(int(max(path.stat().st_mtime for path in files)))


@app.get("/")
def index():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{v}}", asset_version())
    # 本機由 FastAPI 提供頁面，前端走 API；靜態版由匯出腳本寫死為 static
    html = html.replace("{{mode}}", "api")
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
