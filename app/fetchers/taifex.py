"""期交所 MIS 抓取 (微型臺指期貨即時報價)。

富果的期貨行情屬於付費方案，免費金鑰實測回 403，因此期貨改用期交所
自己的看盤端點：免費、不需認證，而且是逐筆更新 (連續查詢可看到時戳
每兩秒就前進)。與證交所 MIS 一樣沒有 CORS 標頭，必須由後端代抓。

期交所沒有公布任何頻率規則，回應標頭也不帶速率限制資訊。這裡只查
單一商品，一輪一個請求，與開著官方看盤頁的使用者行為相當；真正的
節制來自 services/quote.py 的快取。
"""
import logging
from datetime import date, datetime, timedelta

import requests

from app import config

logger = logging.getLogger(__name__)

# 期交所的月份碼，1 月為 A 依序到 12 月為 L
MONTH_CODES = "ABCDEFGHIJKL"

_session = None


def _get_session():
    global _session
    if _session is None:
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Origin": "https://mis.taifex.com.tw",
            "Referer": config.TAIFEX_REFERER,
            "User-Agent": config.USER_AGENT,
        })
        _session = session
    return _session


def _settlement_day(year, month):
    """臺指期的最後交易日：該月第三個星期三。"""
    first = date(year, month, 1)
    # weekday() 星期三為 2
    first_wed = first + timedelta(days=(2 - first.weekday()) % 7)
    return first_wed + timedelta(days=14)


def near_month_symbol(today=None):
    """目前的近月合約代碼，每月換約不需要改程式。

    結算日當天仍可交易到收盤，因此要「超過」結算日才換到次月。
    """
    today = today or date.today()
    year, month = today.year, today.month
    if today > _settlement_day(year, month):
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return f"{config.TAIFEX_FUTURE_PREFIX}{MONTH_CODES[month - 1]}{year % 10}-F"


def in_session(now=None):
    """是否在臺指期的交易時段 (含跨日的盤後盤)。"""
    now = now or datetime.now()
    clock = now.strftime("%H:%M")
    if config.FUTURE_SESSION_OPEN <= clock <= config.FUTURE_SESSION_CLOSE:
        return True
    # 盤後盤跨日，拆成「15:00 之後」或「05:00 之前」兩段
    return clock >= config.FUTURE_AFTERHOURS_OPEN or clock <= config.FUTURE_AFTERHOURS_CLOSE


def to_float(value):
    """期交所對沒有數值的欄位會給空字串。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _levels(quote, side):
    """五檔。期交所以 CBidPrice1..5 這種扁平欄位排列。"""
    prefix = "CBid" if side == "bid" else "CAsk"
    rows = []
    for i in range(1, 6):
        price = to_float(quote.get(f"{prefix}Price{i}"))
        size = to_float(quote.get(f"{prefix}Size{i}"))
        if price:
            rows.append({"price": price, "size": int(size or 0)})
    return rows


def fetch_future(symbol=None):
    """微台近月即時報價。"""
    symbol = symbol or near_month_symbol()
    resp = _get_session().post(
        config.TAIFEX_QUOTE_URL,
        json={"SymbolID": [symbol]},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("RtCode") != "0":
        raise RuntimeError(
            f"期交所回應異常：{payload.get('RtCode')} {payload.get('RtMsg')}"
        )
    quotes = (payload.get("RtData") or {}).get("QuoteList") or []
    if not quotes:
        raise RuntimeError(f"查無合約 {symbol}")
    raw = quotes[0]

    price = to_float(raw.get("CLastPrice"))
    ref = to_float(raw.get("CRefPrice"))
    # 開盤前沒有成交價，改用試撮價，否則畫面會一直是空的
    trial = not price
    if trial:
        price = to_float(raw.get("CTestPrice"))
    change = (price - ref) if (price is not None and ref) else None

    return {
        "code": symbol,
        "name": config.TAIFEX_FUTURE_NAME,
        "price": price,
        "prev_close": ref,
        "change": change,
        "pct": (change / ref * 100) if (change is not None and ref) else None,
        "open": to_float(raw.get("COpenPrice")),
        "high": to_float(raw.get("CHighPrice")),
        "low": to_float(raw.get("CLowPrice")),
        "volume": to_float(raw.get("CTotalVolume")),
        "bids": _levels(raw, "bid"),
        "asks": _levels(raw, "ask"),
        # 尚未開盤時顯示的是試撮價，需要在畫面上標示清楚
        "trial": trial,
        "time": _clock(raw.get("CTime")),
    }


def _clock(text):
    """期交所的時間為 HHMMSS 字串。"""
    text = (text or "").strip()
    if len(text) != 6:
        return ""
    return f"{text[:2]}:{text[2:4]}:{text[4:]}"


# ---------------------------------------------------------------------------
# 每日行情 (盤後)
# ---------------------------------------------------------------------------
#
# 期交所的「每日交易行情下載」提供 CSV，一次最多一個月 (實測 31 天可過、
# 62 天會回「日期時間錯誤」的 HTML)。免費、不需認證，與上面的 MIS 即時行情
# 是兩回事：這裡拿的是盤後定案的開高低收，用來補進資料庫供 K 線圖使用。

DAILY_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
DAILY_REFERER = "https://www.taifex.com.tw/cht/3/dlFutDailyMarketView"
# 回傳的 CSV 為 ms950 編碼
DAILY_ENCODING = "ms950"
# 單次查詢的天數上限
DAILY_MAX_DAYS = 31

# CSV 的欄位位置
CSV_DATE = 0
CSV_COMMODITY = 1
CSV_CONTRACT = 2
CSV_OPEN = 3
CSV_HIGH = 4
CSV_LOW = 5
CSV_CLOSE = 6
CSV_VOLUME = 9
CSV_SETTLEMENT = 10
CSV_OPEN_INTEREST = 11
CSV_SESSION = 17
CSV_MIN_COLUMNS = 18

# 交易時段的中文對照
SESSION_REGULAR = "regular"
SESSION_AFTERHOURS = "afterhours"


def _csv_number(value):
    """CSV 對沒有數值的欄位會給 "-"，千分位也要去掉。"""
    text = (value or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_daily_bars(commodity, start, end):
    """下載一段期間的期貨每日行情。

    start 與 end 為 date 物件，區間不得超過 DAILY_MAX_DAYS。
    回傳的每一列都是可直接寫入 future_daily 的 dict。
    """
    import csv
    import io

    if (end - start).days >= DAILY_MAX_DAYS:
        raise ValueError(f"單次查詢不得超過 {DAILY_MAX_DAYS} 天")

    resp = _get_session().post(
        DAILY_URL,
        data={
            "down_type": "1",
            "commodity_id": commodity,
            "queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": end.strftime("%Y/%m/%d"),
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": DAILY_REFERER,
        },
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    # 區間或參數有問題時會回一頁含 alert 的 HTML，而不是 CSV
    body = resp.content.decode(DAILY_ENCODING, errors="replace")
    if body.lstrip().upper().startswith("<!DOCTYPE"):
        raise RuntimeError("期交所拒絕這次查詢 (多半是日期區間過長)")

    rows = []
    for raw in csv.reader(io.StringIO(body)):
        if len(raw) < CSV_MIN_COLUMNS or not raw[CSV_DATE].strip():
            continue
        date_text = raw[CSV_DATE].strip()
        # 略過標題列
        if not date_text[:4].isdigit():
            continue

        contract = raw[CSV_CONTRACT].strip()
        # 「202609/202610」這種是價差契約 (calendar spread)，不是單月合約，
        # 報價是兩個月份的價差，混進來會讓 K 線圖失真
        if "/" in contract:
            continue

        close = _csv_number(raw[CSV_CLOSE])
        if close is None:
            # 當天該契約沒有成交，畫不出 K 棒
            continue

        session_text = raw[CSV_SESSION].strip()
        rows.append({
            "date": date_text.replace("/", ""),
            "commodity": raw[CSV_COMMODITY].strip(),
            "contract_month": contract,
            "session": SESSION_AFTERHOURS if "盤後" in session_text else SESSION_REGULAR,
            "open": _csv_number(raw[CSV_OPEN]),
            "high": _csv_number(raw[CSV_HIGH]),
            "low": _csv_number(raw[CSV_LOW]),
            "close": close,
            "settlement": _csv_number(raw[CSV_SETTLEMENT]),
            "volume": int(_csv_number(raw[CSV_VOLUME]) or 0),
            "open_interest": (
                int(_csv_number(raw[CSV_OPEN_INTEREST]))
                if _csv_number(raw[CSV_OPEN_INTEREST]) is not None
                else None
            ),
        })
    return rows
