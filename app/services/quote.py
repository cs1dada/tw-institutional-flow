"""個股即時行情的組裝與快取。

這一頁與盤中觀察頁的差別在於「查的範圍」：盤中觀察要掃全市場，
這裡只看使用者指定的一檔，外加常駐的微台與加權指數。請求數天然很少，
但自動更新會把它乘上分頁數與使用者數，因此每一種資料各有一層快取，
同一段時間內的重複查詢共用同一份結果。

取得失敗時沿用上一份快取並標記 stale，讓畫面不會整個空掉，
同時明確告訴使用者這不是當下的報價。
"""
import logging
import threading
import time
from datetime import datetime

from app import config
from app.fetchers import fugle, taifex

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# 各類資料的快取：{"payload": 內容, "fetched_at": 取得時間}
_overview = {"payload": None, "fetched_at": 0.0}
_stocks = {}
_candles = {}


def _fresh(entry, ttl):
    return entry and entry.get("payload") is not None and time.time() - entry["fetched_at"] < ttl


def _cached(entry, error):
    """回傳上一份快取並標記為過期資料。完全沒有快取時往上丟錯誤。"""
    if not entry or entry.get("payload") is None:
        raise error
    payload = dict(entry["payload"])
    payload["stale"] = True
    payload["error"] = str(error)
    return payload


def _now_text():
    return datetime.now().strftime("%H:%M:%S")


def build_overview(force=False):
    """常駐的微台與加權指數，附上期現價差。

    兩個來源互相獨立，其中一邊失敗仍會回傳另一邊的資料，
    這樣期交所或富果單邊出狀況時畫面不會整個空白。
    """
    with _lock:
        if not force and _fresh(_overview, config.QUOTE_CACHE_SECONDS):
            return _overview["payload"]

        future = None
        index = None
        errors = []

        try:
            future = taifex.fetch_future()
        except Exception as exc:
            logger.warning("微台報價取得失敗：%s", exc)
            errors.append(f"微台：{exc}")

        try:
            index = fugle.fetch_index()
        except Exception as exc:
            logger.warning("加權指數取得失敗：%s", exc)
            errors.append(f"加權：{exc}")

        if future is None and index is None:
            return _cached(_overview, RuntimeError("；".join(errors)))

        basis = None
        if future and index and future.get("price") and index.get("price"):
            # 期貨減現貨，正值為正價差
            basis = round(future["price"] - index["price"], 2)

        payload = {
            "future": future,
            "index": index,
            "basis": basis,
            "session": taifex.in_session(),
            "updated_at": _now_text(),
            "stale": False,
            "error": "；".join(errors) if errors else None,
        }
        _overview["payload"] = payload
        _overview["fetched_at"] = time.time()
        return payload


def build_stock(code, force=False):
    """單一個股的即時報價與當日分時走勢。"""
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("請輸入股票代號")

    with _lock:
        entry = _stocks.get(code)
        if not force and _fresh(entry, config.QUOTE_CACHE_SECONDS):
            return entry["payload"]

        try:
            quote = fugle.fetch_stock(code)
        except Exception as exc:
            logger.warning("個股報價取得失敗 (%s)：%s", code, exc)
            return _cached(entry, exc)

        payload = {
            "quote": quote,
            "candles": _build_candles(code),
            "updated_at": _now_text(),
            "stale": False,
            "error": None,
        }
        _stocks[code] = {"payload": payload, "fetched_at": time.time()}
        return payload


def _build_candles(code):
    """分時 K 線。變化比報價慢，因此用較長的快取；失敗時沿用舊的。

    呼叫端已持有 _lock，這裡不再自行上鎖。
    """
    entry = _candles.get(code)
    if _fresh(entry, config.QUOTE_CANDLE_CACHE_SECONDS):
        return entry["payload"]

    try:
        rows = fugle.fetch_candles(code)
    except Exception as exc:
        # 走勢圖不是主要資訊，取不到就沿用舊的，不影響報價顯示
        logger.warning("分時 K 線取得失敗 (%s)：%s", code, exc)
        return entry["payload"] if entry else []

    _candles[code] = {"payload": rows, "fetched_at": time.time()}
    return rows


def search_stocks(conn, keyword, limit=20):
    """依代號或名稱搜尋個股，供輸入框的建議清單使用。

    資料來自本機的 stock_info，不會對外送出任何請求。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    pattern = f"%{keyword}%"
    rows = conn.execute(
        """
        SELECT code, name, market, industry, is_etf
        FROM stock_info
        WHERE code LIKE ? OR name LIKE ?
        ORDER BY
            -- 代號完全相同的排最前面，其次是代號開頭相符的
            CASE WHEN code = ? THEN 0 WHEN code LIKE ? THEN 1 ELSE 2 END,
            code
        LIMIT ?
        """,
        (pattern, pattern, keyword, f"{keyword}%", limit),
    )
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "industry": config.INDUSTRY_ETF if row["is_etf"] else (
                row["industry"] or config.INDUSTRY_UNKNOWN
            ),
        }
        for row in rows
    ]
