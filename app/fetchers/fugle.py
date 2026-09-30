"""富果行情 API 抓取 (個股與指數即時報價、分時 K 線)。

富果的端點需要在標頭帶上金鑰，且免費方案有每分鐘請求數上限，
因此這裡自備一個滑動視窗節流器：超過上限時主動等待，
寧可讓畫面慢一點，也不要收到 429 之後整段時間都取不到資料。

單檔查詢天然低頻 (使用者看哪一檔才查哪一檔)，真正會放大請求數的是
自動更新，因此節流與快取兩層都要有，快取在 services/quote.py。
"""
import logging
import threading
import time

import requests

from app import config

logger = logging.getLogger(__name__)

# 一張 = 1000 股
SHARES_PER_LOT = 1000

_lock = threading.Lock()
# 送出時間的滑動視窗，用來判斷這一分鐘內還能不能再送
_calls = []
_session = None


class QuotaExceeded(RuntimeError):
    """已達自訂的每分鐘上限，呼叫端應改用快取或稍後再試。"""


class SymbolNotFound(RuntimeError):
    """富果查無此代號。多半是輸入了期貨合約或不存在的代號。"""


def _get_session():
    global _session
    if _session is None:
        session = requests.Session()
        session.headers.update({"X-API-KEY": config.FUGLE_API_KEY})
        _session = session
    return _session


def _reserve():
    """取得一次請求的額度，額度用完時丟出 QuotaExceeded。

    這裡刻意不等待：呼叫端是 HTTP 請求的處理流程，讓它卡住幾十秒
    會拖住整個回應，回傳上一份快取才是合理的行為。
    """
    with _lock:
        now = time.time()
        _calls[:] = [t for t in _calls if now - t < 60]
        if len(_calls) >= config.FUGLE_MAX_CALLS_PER_MINUTE:
            raise QuotaExceeded(
                f"已達每分鐘 {config.FUGLE_MAX_CALLS_PER_MINUTE} 次的自訂上限"
            )
        _calls.append(now)


def _get(path, params=None):
    _reserve()
    resp = _get_session().get(
        f"{config.FUGLE_BASE_URL}{path}", params=params, timeout=config.REQUEST_TIMEOUT
    )
    if resp.status_code == 429:
        raise QuotaExceeded("富果回應 429，已超出方案的速率限制")
    if resp.status_code == 403:
        raise RuntimeError("富果回應 403，此端點不在目前的方案內")
    if resp.status_code == 404:
        raise SymbolNotFound("查無此代號")
    if resp.status_code != 200:
        raise RuntimeError(f"富果回應 HTTP {resp.status_code}")
    return resp.json()


def _level(rows):
    """把五檔轉成前端好用的格式，沒有掛單時回傳空 list。"""
    return [
        {"price": row.get("price"), "size": row.get("size")}
        for row in (rows or [])
        if row.get("price")
    ]


def fetch_stock(code):
    """個股即時報價。"""
    raw = _get(f"/intraday/quote/{code}")
    total = raw.get("total") or {}
    # 內外盤量：以買方成交 (內盤) 與賣方成交 (外盤) 判斷買賣力道
    at_bid = total.get("tradeVolumeAtBid") or 0
    at_ask = total.get("tradeVolumeAtAsk") or 0
    return {
        "code": raw.get("symbol"),
        "name": raw.get("name"),
        "price": raw.get("lastPrice") or raw.get("closePrice"),
        "prev_close": raw.get("previousClose"),
        "change": raw.get("change"),
        "pct": raw.get("changePercent"),
        "open": raw.get("openPrice"),
        "high": raw.get("highPrice"),
        "low": raw.get("lowPrice"),
        "avg": raw.get("avgPrice"),
        "amplitude": raw.get("amplitude"),
        "volume": total.get("tradeVolume"),
        "amount": total.get("tradeValue"),
        "transaction": total.get("transaction"),
        "at_bid": at_bid,
        "at_ask": at_ask,
        "bids": _level(raw.get("bids")),
        "asks": _level(raw.get("asks")),
        # 盤中為 True，盤前試撮與收盤後為 False
        "continuous": bool(raw.get("isContinuous")),
        "time": _clock(raw.get("lastUpdated")),
    }


def fetch_index():
    """加權指數即時值。

    指數沒有「成交」這回事，因此沒有 lastPrice，即時值放在 closePrice；
    previousClose 才是昨收。total 內的 tradeValue 為全市場成交金額。
    """
    raw = _get(f"/intraday/quote/{config.FUGLE_INDEX_SYMBOL}")
    total = raw.get("total") or {}
    return {
        "code": raw.get("symbol"),
        "name": config.FUGLE_INDEX_NAME,
        "price": raw.get("closePrice") or raw.get("previousClose"),
        "prev_close": raw.get("previousClose"),
        "change": raw.get("change"),
        "pct": raw.get("changePercent"),
        "open": raw.get("openPrice"),
        "high": raw.get("highPrice"),
        "low": raw.get("lowPrice"),
        # 全市場的成交統計，不是單一商品的
        "amount": total.get("tradeValue"),
        "volume": total.get("tradeVolume"),
        "transaction": total.get("transaction"),
        "time": _clock(raw.get("lastUpdated")),
    }


def fetch_candles(code):
    """當日分時 K 線，供走勢圖使用。"""
    raw = _get(
        f"/intraday/candles/{code}", {"timeframe": config.QUOTE_CANDLE_TIMEFRAME}
    )
    return [
        {
            # 日期字串為 ISO 格式，前端只需要時分
            "time": (row.get("date") or "")[11:16],
            "close": row.get("close"),
            "volume": row.get("volume"),
            "average": row.get("average"),
        }
        for row in (raw.get("data") or [])
        if row.get("close")
    ]


def _clock(epoch_us):
    """富果的時間戳為微秒級 epoch，轉成 HH:MM:SS。"""
    if not epoch_us:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(epoch_us / 1_000_000))
