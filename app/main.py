"""FastAPI 應用程式進入點。

啟動方式：
    python -m uvicorn app.main:app --reload --port 8000

前端是獨立的 Vue 專案 (frontend/)，有兩種用法：

- 開發前端：另外跑 `npm run dev`，Vite 會把 /api 轉發到這裡
- 只看網站：先 `npm run build`，本服務即可直接提供 dist/ 的頁面
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.etf_routes import router as etf_router
from app.api.routes import router
from app.db import init_schema

DIST_DIR = config.BASE_DIR / "dist"


@asynccontextmanager
async def lifespan(app):
    init_schema()
    yield


app = FastAPI(title="台股三大法人類股資金流向", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.include_router(etf_router)


@app.middleware("http")
async def no_cache_page(request, call_next):
    """頁面不快取，避免重新建置後瀏覽器仍載入舊版。"""
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/")
def index():
    page = DIST_DIR / "index.html"
    if not page.exists():
        raise HTTPException(
            status_code=503,
            detail="尚未建置前端，請先在 frontend 目錄執行 npm install && npm run build",
        )
    html = page.read_text(encoding="utf-8")
    # 建置產物預設是靜態模式 (讀 docs/data 的 JSON)，
    # 由本服務提供時改走 /api，資料才會是資料庫的即時內容
    html = html.replace('window.APP_MODE = "static"', 'window.APP_MODE = "api"')
    html = html.replace(
        'window.APP_INTRADAY = "off"',
        f'window.APP_INTRADAY = "{"on" if config.INTRADAY_ENABLED else "off"}"',
    )
    return HTMLResponse(html)


# 建置產物內的資源以相對路徑引用，因此掛在根目錄下
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=DIST_DIR), name="dist")
