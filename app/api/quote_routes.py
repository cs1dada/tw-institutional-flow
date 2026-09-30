"""個股即時行情端點。

只在本機模式提供：富果的金鑰不能放進前端 (打開網頁就等於公開金鑰)，
期交所的端點也沒有 CORS 標頭，兩者都必須由後端代抓，
因此靜態站沒有這一頁。

未設定 FUGLE_API_KEY 時整組端點回 404，不會對外送出任何請求。
"""
from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import connect
from app.fetchers.fugle import QuotaExceeded, SymbolNotFound
from app.services import quote

router = APIRouter(prefix="/api/quote")


def _require_enabled():
    if not config.QUOTE_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="尚未設定 FUGLE_API_KEY，個股即時行情為關閉狀態",
        )


@router.get("/overview")
def quote_overview(force: bool = Query(False)):
    """常駐的微台與加權指數，附期現價差。"""
    _require_enabled()
    try:
        return quote.build_overview(force=force)
    except QuotaExceeded as exc:
        # 429 讓前端知道要放慢，而不是當成一般錯誤一直重試
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stock/{code}")
def quote_stock(code: str, force: bool = Query(False)):
    """單一個股的即時報價、五檔與當日分時走勢。"""
    _require_enabled()
    try:
        return quote.build_stock(code, force=force)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SymbolNotFound as exc:
        # 最常見的原因是把期貨合約代碼 (例如 TMFJ6-F) 輸進個股查詢
        raise HTTPException(
            status_code=404,
            detail=f"查無代號 {code}。這裡只能查詢上市櫃個股，"
                   "期貨與指數已常駐在上方的卡片。",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/search")
def quote_search(q: str = Query("", max_length=20), limit: int = Query(20, ge=1, le=50)):
    """依代號或名稱搜尋個股，只查本機資料庫。"""
    _require_enabled()
    conn = connect()
    try:
        return {"items": quote.search_stocks(conn, q, limit=limit)}
    finally:
        conn.close()
