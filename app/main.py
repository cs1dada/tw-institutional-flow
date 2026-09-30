"""FastAPI 應用程式進入點。

啟動方式：
    python -m uvicorn app.main:app --reload --port 8000

前端是獨立的 Vue 專案 (frontend/)，有兩種用法：

- 開發前端：另外跑 `npm run dev`，Vite 會把 /api 轉發到這裡
- 只看網站：先 `npm run build`，本服務即可直接提供 dist/ 的頁面
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.etf_routes import router as etf_router
from app.api.quote_routes import router as quote_router
from app.api.routes import router
from app.api.sino_routes import router as sino_router
from app.db import init_schema

DIST_DIR = config.BASE_DIR / "dist"

# 建置產物會註冊 Service Worker 供 PWA 離線使用，但在本機開發時它會攔截請求，
# 讓重新建置後的前端遲遲不更新 (畫面停在舊版，硬重新整理也無效)。
# 本服務改為不註冊，並主動註銷既有的註冊與快取；線上的靜態站不受影響。
PWA_REGISTER_TAG = '<script id="vite-plugin-pwa:register-sw" src="./registerSW.js"></script>'
UNREGISTER_SW_SCRIPT = """<script>
navigator.serviceWorker?.getRegistrations().then((list) => {
    // 之前造訪時若已註冊過，一併清掉，否則舊版前端會一直被送出來
    const stale = list.filter((reg) => reg.unregister());
    if (stale.length) {
        caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
            .then(() => location.reload());
    }
});
</script>"""


@asynccontextmanager
async def lifespan(app):
    init_schema()
    yield
    # Shioaji 是有狀態的連線，且同一帳號最多 5 個，關閉時必須登出
    if config.SINO_ENABLED:
        from app.fetchers import sinotrade

        sinotrade.logout()


app = FastAPI(title="台股三大法人類股資金流向", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.include_router(etf_router)
app.include_router(quote_router)
app.include_router(sino_router)


@app.middleware("http")
async def no_cache_page(request, call_next):
    """頁面不快取，避免重新建置後瀏覽器仍載入舊版。"""
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/sw.js")
def self_destroying_sw():
    """本機模式改送一份會自我註銷的 Service Worker。

    只把頁面上的註冊標籤拿掉是不夠的：先前註冊過的 Service Worker 會攔截
    首頁請求並送出自己快取的舊 HTML，新的頁面根本到不了瀏覽器。
    瀏覽器每次導覽都會重新抓取這支腳本 (不走 HTTP 快取)，因此這裡回傳的
    自毀版會接手，清掉所有快取、註銷自己，再讓開著的分頁重新載入。

    線上的靜態站仍使用建置產出的真正 sw.js，不受影響。
    """
    return Response(
        """self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.map((key) => caches.delete(key)));
        await self.registration.unregister();
        const windows = await self.clients.matchAll({ type: "window" });
        windows.forEach((client) => client.navigate(client.url));
    })());
});
""",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


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
    # 個股即時行情需要富果金鑰，未設定時前端不顯示入口
    html = html.replace(
        'window.APP_QUOTE = "off"',
        f'window.APP_QUOTE = "{"on" if config.QUOTE_ENABLED else "off"}"',
    )
    # 永豐即時行情需要 Shioaji 金鑰，未設定時前端不顯示入口
    html = html.replace(
        'window.APP_SINO = "off"',
        f'window.APP_SINO = "{"on" if config.SINO_ENABLED else "off"}"',
    )
    html = html.replace(PWA_REGISTER_TAG, UNREGISTER_SW_SCRIPT)
    return HTMLResponse(html)


# 建置產物內的資源以相對路徑引用，因此掛在根目錄下
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=DIST_DIR), name="dist")
