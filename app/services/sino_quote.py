"""永豐 Shioaji 即時行情的組裝與快取。

與富果那一頁的結構相同，差別在於資料全部來自 Shioaji，而且微台、
加權指數與個股可以**合併成一次批次查詢** —— Shioaji 的 snapshots
接受多個合約，一次呼叫只算一次額度，實測 50 檔只要 0.05 秒、9 KB。

因此這裡不像富果那頁要分開兩個來源各抓一次，一輪就是一次查詢。
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from app import config
from app.fetchers import sinotrade

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache = {"payload": None, "fetched_at": 0.0, "code": None}
_kbars = {}


def _fresh(entry, ttl):
    return (
        entry
        and entry.get("payload") is not None
        and time.time() - entry["fetched_at"] < ttl
    )


def _now_text():
    return datetime.now().strftime("%H:%M:%S")


def build_quote(code=None, force=False):
    """微台、加權指數與 (可選的) 個股，一次批次查詢取回。

    個股代碼變動時一定要重新查，否則會拿到上一檔的快取。
    """
    code = (code or "").strip().upper() or None

    with _lock:
        same_target = _cache["code"] == code
        if not force and same_target and _fresh(_cache, config.SINO_QUOTE_CACHE_SECONDS):
            return _cache["payload"]

        codes = [config.SHIOAJI_FUTURE_CODE, config.SHIOAJI_INDEX_CODE]
        # 點上方常駐卡片時，選定的就是微台或指數本身，不必再送一次
        if code and code not in codes:
            codes.append(code)

        try:
            snapshots = sinotrade.fetch_snapshots(codes)
        except Exception as exc:
            logger.warning("Shioaji 快照取得失敗：%s", exc)
            # 沿用上一份並標記，讓畫面不會整個空掉
            if _cache["payload"] is None or not same_target:
                raise
            payload = dict(_cache["payload"])
            payload["stale"] = True
            payload["error"] = str(exc)
            return payload

        future = snapshots.get(config.SHIOAJI_FUTURE_CODE)
        index = snapshots.get(config.SHIOAJI_INDEX_CODE)
        stock = snapshots.get(code) if code else None

        basis = None
        if future and index and future.get("price") and index.get("price"):
            # 期貨減現貨，正值為正價差
            basis = round(future["price"] - index["price"], 2)

        payload = {
            "future": future,
            "index": index,
            "stock": stock,
            "stock_name": _stock_name(code) if code else None,
            "basis": basis,
            "candles": _build_kbars(code, stock) if code else [],
            "updated_at": _now_text(),
            "stale": False,
            "error": None,
        }
        _cache.update({"payload": payload, "fetched_at": time.time(), "code": code})
        return payload


def _stock_name(code):
    """合約名稱來自登入時下載的合約清單，不佔查詢額度。"""
    try:
        return sinotrade.get_contract(code).name
    except Exception:
        return None


def _build_kbars(code, snapshot=None):
    """當日分時。

    kbars 有每日 270 次的硬上限，而且每次都回傳「今天全部的 1 分 K」——
    每兩分鐘重抓一次等於一直把整份資料重印，一檔一天就要 135 次。

    因此改成：第一次完整抓一份，之後用每 10 秒的報價快照自行追加最新的
    那一根，只在 SINO_KBAR_REFRESH_SECONDS 到了才重抓完整版做校正
    (自行追加的成交量是用累積量相減推出來的，久了會有誤差)。

    呼叫端已持有 _lock，這裡不再自行上鎖。
    """
    entry = _kbars.get(code)
    today = datetime.now().strftime("%Y%m%d")
    stale = (
        entry is None
        or entry.get("date") != today
        or time.time() - entry["fetched_at"] >= config.SINO_KBAR_REFRESH_SECONDS
        # 切到別檔再切回來時，這一檔的分時停在切走的那一刻，中間少掉的
        # K 棒補不回來，只能重抓一份完整的
        or _has_gap(entry, snapshot)
    )

    if stale:
        try:
            rows = sinotrade.fetch_kbars(code)
        except Exception as exc:
            # 走勢圖不是主要資訊，取不到就沿用舊的，不影響報價顯示
            logger.warning("Shioaji K 線取得失敗 (%s)：%s", code, exc)
            return entry["payload"] if entry else []

        _kbars[code] = {
            "payload": rows,
            "fetched_at": time.time(),
            "date": today,
            # 追加新的一根時要用累積量相減，這裡記下基準
            "prev_total": snapshot.get("volume") if snapshot else None,
            # 判斷斷層用：上次更新時看到的報價時間
            "last_clock": snapshot.get("time") if snapshot else None,
        }
        return rows

    if snapshot:
        _merge_snapshot(entry, snapshot)
    return entry["payload"]


def _has_gap(entry, snapshot):
    """從上次更新到現在，這一檔的分時是否斷了一段。

    切換到別檔期間這一檔不會被更新，缺掉的 K 棒沒辦法用報價補回來
    (報價只有當下這一點)，因此偵測到斷層就重抓完整版。

    比較的是「上次看到的報價時間」與「這次的報價時間」，不是 K 線的
    最後一根 —— 收盤後個股的報價時間會停在盤後零股 (約 14:30)，而一般
    交易的 K 線停在 13:30，兩者永遠差一截，用 K 線比會每次都誤判成斷層。
    報價時間停住時這個差值為零，正是我們要的行為。
    """
    clock = (snapshot or {}).get("time") or ""
    last_clock = entry.get("last_clock")
    if len(clock) < 5 or not last_clock:
        return False

    try:
        last = datetime.strptime(last_clock[:5], "%H:%M")
        now = datetime.strptime(clock[:5], "%H:%M")
    except ValueError:
        return True

    gap = (now - last).total_seconds()
    # 收盤後報價時間不動，gap 為 0；負值代表跨日或時間回捲，重抓最保險
    return gap > 120 or gap < 0


def _merge_snapshot(entry, snapshot):
    """把一筆報價快照併進分時序列。

    kbars 的時間標籤是「該分鐘結束的時刻」(第一根為 09:01，代表 09:00 那
    一分鐘)，因此快照要對齊到它所屬分鐘的下一分鐘。

    成交量沒辦法直接拿到，只能用累積成交量相減推出這一根的量；
    定期重抓完整版就是為了把這裡累積的誤差抹掉。
    """
    rows = entry["payload"]
    clock = (snapshot.get("time") or "").strip()
    price = snapshot.get("price")
    if len(clock) < 5 or price is None:
        return

    entry["last_clock"] = clock
    moment = datetime.strptime(clock[:5], "%H:%M") + timedelta(minutes=1)
    label = moment.strftime("%H:%M")

    total = snapshot.get("volume")
    prev_total = entry.get("prev_total")

    if rows and rows[-1]["time"] == label:
        # 同一分鐘內就只更新收盤價與這一根的量
        rows[-1]["close"] = price
        if total is not None and prev_total is not None:
            rows[-1]["volume"] = max(total - prev_total, 0)
        return

    # 收盤後快照的時間會停住，label 不會再往前，因此不會無止境長出新的 K 棒
    if rows and label <= rows[-1]["time"]:
        rows[-1]["close"] = price
        return

    entry["prev_total"] = total
    rows.append({"time": label, "close": price, "volume": 0})


_history = {}


def build_history(code, months=None):
    """個股歷史日線。

    欄位與大盤指數頁的日線一致，前端可直接沿用既有的週線月線聚合、
    均線計算與區間裁切，不必為個股再寫一套。

    歷史資料當天之內不會再變，因此快取拉得很長；一次要拉一整年的
    1 分 K 來聚合，成本比當日分時高一個數量級，另有每日次數上限把關。
    """
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("請輸入股票代號")
    months = int(months or config.SINO_HISTORY_DEFAULT_MONTHS)

    key = (code, months)
    with _lock:
        entry = _history.get(key)
        if _fresh(entry, config.SINO_HISTORY_CACHE_SECONDS):
            return entry["payload"]

        bars = sinotrade.fetch_daily_bars(code, months)
        payload = {
            "code": code,
            "name": _stock_name(code),
            "months": months,
            # 與 IndexPayload 相同的扁平格式，欄位名只寫一次
            "fields": ["date", "open", "high", "low", "close", "turnover"],
            "items": [
                [b["date"], b["open"], b["high"], b["low"], b["close"], b["turnover"]]
                for b in bars
            ],
            "updated_at": _now_text(),
        }
        _history[key] = {"payload": payload, "fetched_at": time.time()}
        return payload


def build_usage():
    """流量與次數用量，讓畫面上看得到還剩多少。"""
    return sinotrade.fetch_usage()


def search(keyword, limit=20):
    return sinotrade.search_contracts(keyword, limit=limit)
