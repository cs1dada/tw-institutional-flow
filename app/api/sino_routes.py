"""永豐 Shioaji 即時行情端點。

只在本機模式提供：Shioaji 是需要登入的 Python SDK，金鑰不可能放進前端，
必須由後端持有連線並代為查詢，因此靜態站沒有這一頁。

未設定金鑰時整組端點回 404，不會建立任何連線。
"""
from fastapi import APIRouter, HTTPException, Query

from app import config
from app.fetchers.sinotrade import NotLoggedIn, QuotaExceeded
from app.services import sino_quote

router = APIRouter(prefix="/api/sino")


def _require_enabled():
    if not config.SINO_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="尚未設定 SHIOAJI_API_KEY 與 SHIOAJI_SECRET_KEY，永豐即時行情為關閉狀態",
        )


@router.get("/quote")
def sino_quote_view(code: str = Query("", max_length=20), force: bool = Query(False)):
    """大台、加權指數與指定個股，一次批次查詢取回。"""
    _require_enabled()
    try:
        return sino_quote.build_quote(code or None, force=force)
    except QuotaExceeded as exc:
        # 429 讓前端知道要放慢，而不是當成一般錯誤一直重試
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotLoggedIn as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"{exc}。這裡只能查詢上市櫃個股，期貨與指數已常駐在上方的卡片。",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/history/{code}")
def sino_history(code: str, months: int = Query(0, ge=0, le=36)):
    """個股歷史日線，供 K 線圖使用。週線與月線由前端聚合。"""
    _require_enabled()
    try:
        return sino_quote.build_history(code, months or None)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotLoggedIn as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/usage")
def sino_usage():
    """流量與 K 線次數用量。屬於帳務查詢，不佔行情查詢額度。"""
    _require_enabled()
    try:
        return sino_quote.build_usage()
    except NotLoggedIn as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/search")
def sino_search(q: str = Query("", max_length=20), limit: int = Query(20, ge=1, le=50)):
    """依代號或名稱搜尋個股，查的是登入時下載的合約清單，不送出行情查詢。"""
    _require_enabled()
    try:
        return {"items": sino_quote.search(q, limit=limit)}
    except NotLoggedIn as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
