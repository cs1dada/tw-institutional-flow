"""盤中即時報價抓取 (證交所 MIS)。

MIS 是證交所給看盤網頁用的端點，上市與上櫃個股都查得到，回應內的
`userDelay` 標示官方建議的輪詢間隔為 5 秒。

兩個實測得到的限制決定了這裡的作法：

- 單次請求的檔數有上限，120 檔可過、150 檔會被拒 (rtcode 9999)，
  再多則連 JSON 都不回傳，直接吐錯誤頁，因此全市場必須分批抓。
- 回應只有「當下的快照」，沒有逐筆明細。累積成交量 `v` 是從開盤累計，
  但沒有對應的累積成交金額，金額只能以現價乘上總量估算 (見 quote_amount)。

這裡只負責把快照抓回來並轉成乾淨的 dict，聚合邏輯在 services/intraday.py。
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app import config
from app.http_client import build_session

logger = logging.getLogger(__name__)

# requests 的 Session 並非完全執行緒安全，因此每個工作執行緒各持有一個。
# 重用 Session 才能省下每批重新進行 TLS 握手的成本。
_local = threading.local()


def _session():
    session = getattr(_local, "session", None)
    if session is None:
        session = build_session()
        _local.session = session
    return session

# 一張 = 1000 股
SHARES_PER_LOT = 1000


def to_float(value):
    """MIS 對沒有數值的欄位會給 "-" 或空字串。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def channel(code, market):
    """組出 MIS 的頻道代碼，上市為 tse_、上櫃為 otc_。"""
    prefix = "tse_" if market == config.MARKET_TWSE else "otc_"
    return f"{prefix}{code}.tw"


def _mid_price(quote):
    """最佳買價與最佳賣價的中價。

    五檔以 "價_價_價_" 的字串排列，第一個即為最佳檔位。
    """
    asks = str(quote.get("a") or "").split("_")
    bids = str(quote.get("b") or "").split("_")
    ask = to_float(asks[0]) if asks else None
    bid = to_float(bids[0]) if bids else None
    if ask and bid:
        return (ask + bid) / 2
    return ask or bid


def _best_price(quote):
    """取得可用的成交價。

    盤中若快照的瞬間沒有正在成交，`z` 與 `pz` 都會是 "-"，但巢狀的
    `trade` 仍保有最近一筆成交。少了這層，成交熱絡的權值股會因為
    取不到價格而被當成平盤，整個類股的加權漲跌幅就失真了。

    順序為：當下成交價 -> 最近一筆成交 -> 五檔中價 -> 昨收。
    """
    candidates = [quote.get("z"), quote.get("pz")]
    trade = quote.get("trade")
    if isinstance(trade, dict):
        candidates.append(trade.get("z"))
    for value in candidates:
        price = to_float(value)
        if price is not None and price > 0:
            return price

    mid = _mid_price(quote)
    if mid and mid > 0:
        return mid
    prev = to_float(quote.get("y"))
    return prev if prev and prev > 0 else None


def parse_quote(raw):
    """把 MIS 的單筆回應轉成內部格式，資料不足時回傳 None。"""
    code = (raw.get("c") or "").strip()
    price = _best_price(raw)
    prev_close = to_float(raw.get("y"))
    if not code or price is None or not prev_close:
        return None

    volume = to_float(raw.get("v")) or 0          # 累積成交量 (張)
    return {
        "code": code,
        "name": (raw.get("n") or "").strip(),
        "price": price,
        "prev_close": prev_close,
        "open": to_float(raw.get("o")),
        "high": to_float(raw.get("h")),
        "low": to_float(raw.get("l")),
        "volume": int(volume),
        # 最後成交時間，用來判斷這檔是否真的有在交易
        "time": (raw.get("t") or "").strip(),
        # 累積成交量大於零就代表今天成交過，不能改用當下是否正在成交判斷
        "traded": volume > 0,
    }


def quote_amount(quote):
    """估算開盤至今的累積成交金額 (元)。

    MIS 沒有提供累積成交金額，只能用現價乘上累積張數。盤中價格會變動，
    因此這個值與真實成交金額有誤差；但全市場都用同一種算法，
    用於比較類股之間的相對規模仍然成立。
    """
    return quote["price"] * quote["volume"] * SHARES_PER_LOT


def fetch_batch(channels):
    """抓取一批頻道的即時報價，回傳原始的 msgArray。"""
    session = _session()
    resp = session.get(
        config.MIS_QUOTE_URL,
        params={"ex_ch": "|".join(channels), "json": "1", "delay": "0"},
        headers={"Referer": config.MIS_REFERER},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("rtcode") != "0000":
        raise RuntimeError(f"MIS 回應異常：{payload.get('rtcode')} {payload.get('rtmessage')}")
    return payload.get("msgArray", [])


def fetch_quotes(targets):
    """抓取多檔即時報價，targets 為 (code, market) 序列。

    全市場約 24 批，逐批序列抓取要近 30 秒，比快取時間還長，等於每次
    請求都在重掃。改以少量執行緒並行，整輪可壓到 10 秒內；併發數刻意
    壓低，避免對證交所造成不必要的壓力。

    單一批次失敗不中斷整輪，只記錄並略過，避免一批逾時就整頁沒有資料。
    回傳 (報價 dict 以代號為 key, 失敗批次數)。
    """
    channels = [channel(code, market) for code, market in targets]
    batches = [
        channels[start:start + config.MIS_BATCH_SIZE]
        for start in range(0, len(channels), config.MIS_BATCH_SIZE)
    ]
    if not batches:
        return {}, 0

    def run(batch):
        try:
            return fetch_batch(batch)
        except Exception as exc:
            logger.warning("盤中報價批次失敗 (%s 起共 %d 檔)：%s", batch[0], len(batch), exc)
            return None

    quotes = {}
    failed = 0
    workers = min(config.MIS_CONCURRENCY, len(batches))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for raws in pool.map(run, batches):
            if raws is None:
                failed += 1
                continue
            for raw in raws:
                quote = parse_quote(raw)
                if quote:
                    quotes[quote["code"]] = quote
    return quotes, failed
