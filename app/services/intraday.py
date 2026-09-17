"""盤中類股強弱的即時聚合。

與盤後的類股資金流向頁不同，這裡沒有三大法人買賣超可用 —— 法人進出是
收盤後才公布的，盤中不存在任何官方即時籌碼資料。因此本頁改以
「成交金額」衡量資金規模，以「成交金額加權漲跌幅」衡量方向：

    區塊面積 = 該類股開盤至今的成交金額
    區塊顏色 = 該類股以成交金額加權的漲跌幅

這是實際成交統計，不含推估成分，與盤後的買賣超是兩種不同的東西，
因此獨立成一頁，不與法人買賣超混在同一張圖上。

掃完全市場約需 15 秒，所以結果會快取 INTRADAY_CACHE_SECONDS 秒，
多個瀏覽器分頁共用同一份，不會各自觸發一輪掃描。
"""
import logging
import threading
import time
from datetime import datetime

from app import config
from app.fetchers import intraday as fetcher

logger = logging.getLogger(__name__)

# 個股以陣列輸出，欄位名只寫一次
STOCK_FIELDS = (
    "code", "name", "market", "industry", "price", "pct", "amount", "volume",
)

# 大盤與櫃買的即時指數頻道，各自對應一個市場別，用來附上該市場的成交統計
INDEX_CHANNELS = {
    "tse_t00.tw": {"code": "TAIEX", "name": "加權指數", "market": config.MARKET_TWSE},
    "otc_o00.tw": {"code": "TPEX", "name": "櫃買指數", "market": config.MARKET_TPEX},
}

# 視為平盤的漲跌幅門檻，避免浮點誤差把零判成漲跌
FLAT_EPSILON = 1e-9

_lock = threading.Lock()
_cache = {"payload": None, "fetched_at": 0.0}
# 被來源拒絕時的退避狀態：在 until 之前不再嘗試，連續失敗則加倍等待
_backoff = {"until": 0.0, "seconds": 0.0}


def _now():
    return datetime.now()


def is_trading_time(now=None):
    """是否在盤中時段。週末與非交易時間不需要向外抓取。"""
    now = now or _now()
    if now.weekday() >= 5:
        return False
    return config.INTRADAY_OPEN <= now.strftime("%H:%M") <= config.INTRADAY_CLOSE


def _targets(conn):
    """全市場個股清單。ETF 歸入虛擬類別，與盤後頁的處理方式一致。"""
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "industry": config.INDUSTRY_ETF if row["is_etf"] else (
                row["industry"] or config.INDUSTRY_UNKNOWN
            ),
            "is_etf": row["is_etf"],
        }
        for row in conn.execute(
            "SELECT code, name, market, industry, is_etf FROM stock_info ORDER BY code"
        )
    ]


def _fetch_indexes():
    """大盤與櫃買的即時指數。失敗不影響類股資料，回傳空 list。"""
    try:
        raws = fetcher.fetch_batch(list(INDEX_CHANNELS))
    except Exception as exc:
        logger.warning("盤中指數抓取失敗：%s", exc)
        return []

    items = []
    for raw in raws:
        meta = INDEX_CHANNELS.get(f"{raw.get('ex')}_{raw.get('c')}.tw")
        value = fetcher.to_float(raw.get("z"))
        prev = fetcher.to_float(raw.get("y"))
        if not meta or value is None or not prev:
            continue
        items.append(
            {
                "code": meta["code"],
                "name": meta["name"],
                "market": meta["market"],
                "value": round(value, 2),
                "prev_close": round(prev, 2),
                "diff": round(value - prev, 2),
                "pct": round((value - prev) / prev * 100, 2),
                # MIS 在指數上給的 m 是成交張數、r 是成交筆數，都不是金額；
                # 金額另外由個股加總而來 (見 _build)，與類股分布的合計一致
                "volume": int(fetcher.to_float(raw.get("m")) or 0),
                "trades": int(fetcher.to_float(raw.get("r")) or 0),
                "time": (raw.get("t") or "").strip(),
            }
        )
    return items


def _aggregate(stocks):
    """把個股聚合成類股。

    加權漲跌幅以成交金額為權重：一檔沒什麼成交量的股票漲停，
    不該讓整個類股看起來很強。
    """
    groups = {}
    for stock in stocks:
        group = groups.setdefault(
            stock["industry"],
            {
                "industry": stock["industry"],
                "amount": 0.0,
                "up_amount": 0.0,
                "down_amount": 0.0,
                "up_count": 0,
                "down_count": 0,
                "flat_count": 0,
                "stock_count": 0,
                "_weighted": 0.0,
            },
        )
        amount = stock["amount"]
        group["stock_count"] += 1
        group["amount"] += amount
        group["_weighted"] += stock["pct"] * amount
        if stock["pct"] > FLAT_EPSILON:
            group["up_count"] += 1
            group["up_amount"] += amount
        elif stock["pct"] < -FLAT_EPSILON:
            group["down_count"] += 1
            group["down_amount"] += amount
        else:
            group["flat_count"] += 1

    items = []
    for group in groups.values():
        amount = group["amount"]
        group["weighted_pct"] = round(group.pop("_weighted") / amount, 3) if amount else 0.0
        group["amount"] = round(amount)
        group["up_amount"] = round(group["up_amount"])
        group["down_amount"] = round(group["down_amount"])
        items.append(group)
    items.sort(key=lambda g: g["amount"], reverse=True)
    return items


def _build(conn):
    """實際執行一輪全市場掃描並聚合。"""
    targets = _targets(conn)
    started = time.time()
    quotes, failed = fetcher.fetch_quotes([(t["code"], t["market"]) for t in targets])
    elapsed = time.time() - started

    stocks = []
    latest_time = ""
    for target in targets:
        quote = quotes.get(target["code"])
        # 整天都沒有成交的個股不列入統計，否則會以平盤灌水檔數
        if not quote or not quote["traded"]:
            continue
        amount = fetcher.quote_amount(quote)
        pct = (quote["price"] - quote["prev_close"]) / quote["prev_close"] * 100
        stocks.append(
            {
                "code": target["code"],
                "name": target["name"] or quote["name"],
                "market": target["market"],
                "industry": target["industry"],
                "price": quote["price"],
                "pct": pct,
                "amount": amount,
                "volume": quote["volume"],
            }
        )
        latest_time = max(latest_time, quote["time"])

    # 各市場的成交金額由個股加總，與類股分布的合計同一個來源
    market_amount = {}
    for stock in stocks:
        market_amount[stock["market"]] = market_amount.get(stock["market"], 0) + stock["amount"]
    indexes = _fetch_indexes()
    for index in indexes:
        index["amount"] = round(market_amount.get(index["market"], 0))

    now = _now()
    return {
        "date": now.strftime("%Y%m%d"),
        "updated_at": now.strftime("%H:%M:%S"),
        # 報價本身的最後成交時間，收盤後會固定在 13:30 附近
        "quote_time": latest_time,
        "trading": is_trading_time(now),
        "indexes": indexes,
        "industries": _aggregate(stocks),
        "stock_fields": list(STOCK_FIELDS),
        "stocks": [
            [
                s["code"], s["name"], s["market"], s["industry"],
                s["price"], round(s["pct"], 2), round(s["amount"]), s["volume"],
            ]
            for s in sorted(stocks, key=lambda s: s["amount"], reverse=True)
        ],
        "scanned": len(targets),
        "quoted": len(stocks),
        "failed_batches": failed,
        "elapsed": round(elapsed, 1),
    }


def _is_degraded(payload, cached):
    """判斷這一輪的結果是否不完整到不該拿來取代舊資料。

    MIS 在請求過於頻繁時會直接斷線 (RemoteDisconnected)，整輪可能一檔
    都抓不到。若照樣寫入快取，畫面會瞬間變成空的；沿用上一份雖然稍舊，
    但比空白有用得多。
    """
    if payload["quoted"] == 0:
        return True
    return bool(cached) and payload["quoted"] < cached["quoted"] * 0.5


def _enter_backoff():
    """拉長下一次嘗試的等待時間，連續失敗則加倍。"""
    seconds = min(
        max(_backoff["seconds"] * 2, config.INTRADAY_BACKOFF_SECONDS),
        config.INTRADAY_BACKOFF_MAX,
    )
    _backoff["seconds"] = seconds
    _backoff["until"] = time.time() + seconds
    logger.warning("盤中來源暫時不可用，%.0f 秒內不再嘗試", seconds)


def _clear_backoff():
    _backoff["seconds"] = 0.0
    _backoff["until"] = 0.0


def _result(payload, cached_flag, age, stale):
    return dict(payload, cached=cached_flag, age=round(age, 1), stale=stale)


def build_intraday(conn, force=False):
    """取得盤中資料，必要時才重新掃描。

    收盤後不再向外抓取，直接沿用最後一份快照；服務在收盤後才啟動時
    仍會抓一次，讓使用者至少看得到當日收盤的結果。
    """
    with _lock:
        cached = _cache["payload"]
        now = time.time()
        age = now - _cache["fetched_at"]

        if cached and not force:
            if age < config.INTRADAY_CACHE_SECONDS:
                return _result(cached, True, age, False)
            if not is_trading_time():
                return _result(cached, True, age, False)

        # 來源正在退避中，直接回上一份，不再送出請求
        if now < _backoff["until"] and cached:
            return _result(cached, True, age, True)

        payload = _build(conn)
        if _is_degraded(payload, cached):
            logger.warning(
                "盤中掃描結果不完整：%d/%d 檔有報價，失敗批次 %d",
                payload["quoted"], payload["scanned"], payload["failed_batches"],
            )
            _enter_backoff()
            if cached:
                return _result(cached, True, time.time() - _cache["fetched_at"], True)
            return _result(payload, False, 0.0, True)

        _clear_backoff()
        _cache["payload"] = payload
        _cache["fetched_at"] = time.time()
        logger.info(
            "盤中掃描完成：%d/%d 檔有報價，耗時 %.1f 秒，失敗批次 %d",
            payload["quoted"], payload["scanned"], payload["elapsed"], payload["failed_batches"],
        )
        return _result(payload, False, 0.0, False)
