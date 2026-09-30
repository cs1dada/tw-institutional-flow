"""永豐 Shioaji 行情抓取。

與其他抓取器最大的不同是 Shioaji 是**有狀態**的：要先登入建立連線，
之後的查詢都走同一個連線。官方限制同一帳號最多 5 個連線，因此這裡
維持單一實例，第一次用到才登入 (lazy)，服務關閉時登出。

官方限制 (https://sinotrade.github.io/zh/tutor/limit/)：

    每日流量      500 MB，早上 8:00 重置
    行情查詢      snapshots / ticks / kbars 合計 10 秒 50 次
    盤中 kbars    270 次
    訂閱數        200 檔；連線數 5 個；登入 1000 次/日

超過流量後行情查詢會**回傳空值而不是報錯**，是會靜默失敗的那種錯。
因此這裡在每次查詢前都先過節流器，並把 kbars 另外記次數，
兩者都抓在官方上限之下。
"""
import datetime as dt
import logging
import threading
import time

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_api = None
_contracts = {}

# 行情查詢的送出時間，用於滑動視窗節流
_queries = []
# kbars 的每日計數：{"date": 日期, "count": 次數}
_kbar_usage = {"date": None, "count": 0}
# 歷史日線的每日計數。一次要拉一整年的 1 分 K，成本與當日分時差一個數量級，
# 因此與 _kbar_usage 分開計算
_history_usage = {"date": None, "count": 0}


class QuotaExceeded(RuntimeError):
    """已達自訂的查詢上限，呼叫端應改用快取或稍後再試。"""


class NotLoggedIn(RuntimeError):
    """尚未設定金鑰或登入失敗。"""


def _reserve(kind="quote"):
    """取得一次行情查詢的額度。

    刻意不等待：呼叫端是 HTTP 請求的處理流程，卡住幾秒會拖住整個回應，
    回傳上一份快取才是合理的行為。
    """
    now = time.time()
    window = config.SHIOAJI_QUERY_WINDOW_SECONDS
    _queries[:] = [t for t in _queries if now - t < window]
    if len(_queries) >= config.SHIOAJI_MAX_QUERIES_PER_WINDOW:
        raise QuotaExceeded(
            f"已達自訂上限 ({window} 秒 {config.SHIOAJI_MAX_QUERIES_PER_WINDOW} 次)"
        )
    _queries.append(now)


def _reserve_kbar():
    """kbars 另有每日次數上限，與流量無關，用完就不能再查。"""
    today = dt.date.today()
    if _kbar_usage["date"] != today:
        _kbar_usage["date"] = today
        _kbar_usage["count"] = 0
    if _kbar_usage["count"] >= config.SINO_KBAR_DAILY_LIMIT:
        raise QuotaExceeded(
            f"今日 K 線查詢已達自訂上限 {config.SINO_KBAR_DAILY_LIMIT} 次"
        )
    _kbar_usage["count"] += 1


def _reserve_history():
    """歷史日線的每日次數上限，用來擋住流量而不是次數。"""
    today = dt.date.today()
    if _history_usage["date"] != today:
        _history_usage["date"] = today
        _history_usage["count"] = 0
    if _history_usage["count"] >= config.SINO_HISTORY_DAILY_LIMIT:
        raise QuotaExceeded(
            f"今日歷史 K 線查詢已達自訂上限 {config.SINO_HISTORY_DAILY_LIMIT} 次"
        )
    _history_usage["count"] += 1


def get_api():
    """取得已登入的 Shioaji 實例，第一次用到才登入。"""
    global _api
    if not config.SINO_ENABLED:
        raise NotLoggedIn("尚未設定 SHIOAJI_API_KEY 與 SHIOAJI_SECRET_KEY")
    if _api is not None:
        return _api

    with _lock:
        if _api is not None:
            return _api
        import shioaji as sj

        api = sj.Shioaji(simulation=config.SHIOAJI_SIMULATION)
        api.login(
            api_key=config.SHIOAJI_API_KEY,
            secret_key=config.SHIOAJI_SECRET_KEY,
        )
        logger.info("Shioaji 登入完成 (simulation=%s)", config.SHIOAJI_SIMULATION)
        _api = api
        return _api


def logout():
    """服務關閉時釋放連線，避免佔用 5 個連線額度。"""
    global _api
    with _lock:
        if _api is None:
            return
        try:
            _api.logout()
            logger.info("Shioaji 已登出")
        except Exception as exc:
            logger.warning("Shioaji 登出失敗：%s", exc)
        finally:
            _api = None
            _contracts.clear()


def _index_contract(api, code):
    """指數合約分散在不同交易所群組下，只能逐一比對代碼。"""
    for group in api.Contracts.Indexs:
        for contract in group:
            if contract.code == code:
                return contract
    return None


def get_contract(code):
    """依代碼取得合約，結果快取起來，換頁不必重新查。

    依序找期貨的近月連續合約、指數、個股，三者的代碼不會重疊。
    """
    if code in _contracts:
        return _contracts[code]

    api = get_api()
    contract = None

    if code == config.SHIOAJI_FUTURE_CODE:
        contract = api.Contracts.Futures.TMF[code]
    elif code.startswith("IX") or code.startswith("IR"):
        contract = _index_contract(api, code)
    else:
        contract = api.Contracts.Stocks.get(code)

    if contract is None:
        raise ValueError(f"查無代號 {code}")
    _contracts[code] = contract
    return contract


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clock(ts_ns):
    """Shioaji 的時間戳為奈秒級，且已經是台北時間的數值表示。

    直接用 fromtimestamp 會再套一次本機時區而多出 8 小時，因此以 UTC 解讀。
    """
    if not ts_ns:
        return ""
    moment = dt.datetime.fromtimestamp(ts_ns / 1e9, dt.timezone.utc)
    return moment.strftime("%H:%M:%S")


def fetch_snapshots(codes):
    """一次取得多個代碼的快照，回傳以代碼為 key 的 dict。

    批次查詢只算一次額度，因此常駐的微台與指數要和個股合併成一次呼叫。
    """
    _reserve()
    api = get_api()
    contracts = [get_contract(code) for code in codes]
    rows = api.snapshots(contracts)

    # 超過每日流量時 Shioaji 會回空值而不是報錯，這裡明確辨識出來
    if not rows:
        raise RuntimeError("Shioaji 回傳空值，可能已超出每日流量上限")

    result = {}
    for row in rows:
        total_volume = _to_float(row.total_volume) or 0
        result[row.code] = {
            "code": row.code,
            "price": _to_float(row.close),
            "change": _to_float(row.change_price),
            "pct": _to_float(row.change_rate),
            "open": _to_float(row.open),
            "high": _to_float(row.high),
            "low": _to_float(row.low),
            "avg": _to_float(row.average_price),
            "volume": total_volume,
            "amount": _to_float(row.total_amount),
            # 最佳一檔。五檔要另外訂閱串流，這裡不做，避免佔用訂閱額度
            "bid": _to_float(row.buy_price),
            "ask": _to_float(row.sell_price),
            "bid_volume": _to_float(row.buy_volume),
            "ask_volume": _to_float(row.sell_volume),
            # 與昨日同時間的量能比，大於 1 代表今天量放大
            "volume_ratio": _to_float(row.volume_ratio),
            "yesterday_volume": _to_float(row.yesterday_volume),
            "time": _clock(row.ts),
        }
    return result


def fetch_kbars(code):
    """當日 1 分 K，供走勢圖使用。

    盤中 kbars 官方上限為 270 次，因此另外記次數 (見 _reserve_kbar)。
    """
    _reserve_kbar()
    _reserve()
    api = get_api()
    contract = get_contract(code)
    today = dt.date.today().isoformat()
    raw = api.kbars(contract, start=today, end=today)
    data = {**raw}

    stamps = data.get("ts") or []
    closes = data.get("Close") or []
    volumes = data.get("Volume") or []
    return [
        {
            "time": dt.datetime.fromtimestamp(
                stamps[i] / 1e9, dt.timezone.utc
            ).strftime("%H:%M"),
            "close": closes[i],
            "volume": volumes[i],
        }
        for i in range(len(stamps))
    ]


def fetch_usage():
    """查詢流量用量。屬於帳務查詢，不佔行情查詢的次數額度。"""
    api = get_api()
    usage = api.usage()
    return {
        "connections": usage.connections,
        "bytes": usage.bytes,
        "limit_bytes": usage.limit_bytes,
        "remaining_bytes": usage.remaining_bytes,
        "used_mb": round(usage.bytes / 1048576, 2),
        "limit_mb": round(usage.limit_bytes / 1048576),
        "percent": round(usage.bytes / usage.limit_bytes * 100, 2) if usage.limit_bytes else 0,
        # 這一頁自己的 K 線用量，與官方的流量分開看
        "kbar_used": _kbar_usage["count"] if _kbar_usage["date"] == dt.date.today() else 0,
        "kbar_limit": config.SINO_KBAR_DAILY_LIMIT,
        "history_used": (
            _history_usage["count"] if _history_usage["date"] == dt.date.today() else 0
        ),
        "history_limit": config.SINO_HISTORY_DAILY_LIMIT,
    }


def fetch_daily_bars(code, months):
    """一段區間的日線，由 1 分 K 聚合而成。

    Shioaji 只提供 1 分 K，因此成本與根數成正比 (實測約 60 bytes/根，
    一年約 4 MB)。聚合在後端做，送到前端的就只有每天一根，資料量小得多。

    回傳欄位刻意與大盤指數頁的日線一致 (date/open/high/low/close/turnover)，
    前端才能直接沿用既有的週線月線聚合與均線計算。
    """
    months = max(1, min(int(months), config.SINO_HISTORY_MAX_MONTHS))
    _reserve_history()
    _reserve()

    api = get_api()
    contract = get_contract(code)
    end = dt.date.today()
    # 以 31 天估一個月即可，端點本來就會截到實際有資料的範圍
    start = end - dt.timedelta(days=months * 31)
    raw = api.kbars(contract, start=start.isoformat(), end=end.isoformat())
    data = {**raw}

    stamps = data.get("ts") or []
    if not stamps:
        raise RuntimeError("Shioaji 回傳空值，可能已超出每日流量上限")

    opens = data.get("Open") or []
    highs = data.get("High") or []
    lows = data.get("Low") or []
    closes = data.get("Close") or []
    amounts = data.get("Amount") or []

    bars = []
    current = None
    for i in range(len(stamps)):
        # ts 已是台北時間的數值表示，以 UTC 解讀才不會多出 8 小時
        day = dt.datetime.fromtimestamp(stamps[i] / 1e9, dt.timezone.utc)
        date = day.strftime("%Y%m%d")
        if current is None or current["date"] != date:
            current = {
                "date": date,
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                # 成交金額換算為億元，與大盤指數頁的單位一致
                "turnover": (amounts[i] or 0) / 1e8,
            }
            bars.append(current)
            continue
        current["high"] = max(current["high"], highs[i])
        current["low"] = min(current["low"], lows[i])
        current["close"] = closes[i]
        current["turnover"] += (amounts[i] or 0) / 1e8

    for bar in bars:
        bar["turnover"] = round(bar["turnover"], 4)
    return bars


def search_contracts(keyword, limit=20):
    """依代號或名稱搜尋個股合約。

    走本機已下載的合約清單 (登入時一併取得)，不會額外送出行情查詢。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    api = get_api()
    upper = keyword.upper()
    matches = []
    # Contracts.Stocks 迭代出的是交易所群組 (TSE/OTC/OES)，合約在再下一層
    for group in api.Contracts.Stocks:
        for contract in group:
            if upper in contract.code.upper() or keyword in contract.name:
                matches.append({
                    "code": contract.code,
                    "name": contract.name,
                    "exchange": str(contract.exchange),
                })
        if len(matches) >= limit * 5:
            break

    # 代號完全相同的排最前面，其次是代號開頭相符的
    def rank(item):
        code = item["code"]
        if code == upper:
            return 0
        if code.startswith(upper):
            return 1
        return 2

    matches.sort(key=lambda item: (rank(item), item["code"]))
    return matches[:limit]
