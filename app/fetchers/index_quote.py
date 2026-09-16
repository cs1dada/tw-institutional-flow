"""大盤指數 (發行量加權股價指數) 日線資料抓取。

證交所把指數的開高低收與成交量值放在兩支不同的端點，且都以「月」為單位
一次回傳整月，因此這裡以月為單位抓取，回補歷史時的請求數遠少於逐日抓取。

- MI_5MINS_HIST：日期、開盤、最高、最低、收盤指數
- FMTQIK：日期、成交股數、成交金額、成交筆數、收盤指數、漲跌點數
"""
import logging

from app import config
from app.fetchers.twse import to_float, to_int
from app.http_client import fetch

logger = logging.getLogger(__name__)

# MI_5MINS_HIST 的欄位位置
OHLC_DATE = 0
OHLC_OPEN = 1
OHLC_HIGH = 2
OHLC_LOW = 3
OHLC_CLOSE = 4
OHLC_MIN_COLUMNS = 5

# FMTQIK 的欄位位置
VALUE_DATE = 0
VALUE_VOLUME = 1
VALUE_TURNOVER = 2
VALUE_TRADES = 3
VALUE_CLOSE = 4
VALUE_CHANGE = 5
VALUE_MIN_COLUMNS = 6


def to_ad_date(roc_date):
    """將民國日期 115/09/01 轉為 20260901，格式不符時回傳 None。"""
    parts = str(roc_date).strip().split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0]) + 1911
        return f"{year:04d}{int(parts[1]):02d}{int(parts[2]):02d}"
    except ValueError:
        return None


def _month_param(year, month):
    """兩支端點都以該月任一日作為查詢參數。"""
    return f"{year:04d}{month:02d}01"


def fetch_ohlc_month(year, month):
    """取得指定月份每個交易日的指數開高低收，以日期為 key。"""
    payload = fetch(
        config.TWSE_INDEX_OHLC_URL,
        params={"date": _month_param(year, month), "response": "json"},
    )
    if payload.get("stat") != "OK" or not payload.get("data"):
        logger.info("加權指數 %d-%02d 無開高低收資料 (stat=%s)", year, month, payload.get("stat"))
        return {}

    rows = {}
    for raw in payload["data"]:
        if len(raw) < OHLC_MIN_COLUMNS:
            continue
        date_str = to_ad_date(raw[OHLC_DATE])
        if not date_str:
            continue
        rows[date_str] = {
            "date": date_str,
            "open": to_float(raw[OHLC_OPEN]),
            "high": to_float(raw[OHLC_HIGH]),
            "low": to_float(raw[OHLC_LOW]),
            "close": to_float(raw[OHLC_CLOSE]),
        }
    return rows


def fetch_value_month(year, month):
    """取得指定月份每個交易日的成交量值與漲跌點數，以日期為 key。"""
    payload = fetch(
        config.TWSE_INDEX_VALUE_URL,
        params={"date": _month_param(year, month), "response": "json"},
    )
    if payload.get("stat") != "OK" or not payload.get("data"):
        logger.info("加權指數 %d-%02d 無成交量值資料 (stat=%s)", year, month, payload.get("stat"))
        return {}

    rows = {}
    for raw in payload["data"]:
        if len(raw) < VALUE_MIN_COLUMNS:
            continue
        date_str = to_ad_date(raw[VALUE_DATE])
        if not date_str:
            continue
        rows[date_str] = {
            "date": date_str,
            "volume": to_int(raw[VALUE_VOLUME]),
            "turnover": to_int(raw[VALUE_TURNOVER]),
            "trades": to_int(raw[VALUE_TRADES]),
            "close": to_float(raw[VALUE_CLOSE]),
            "change": to_float(raw[VALUE_CHANGE]),
        }
    return rows


def fetch_index_month(year, month):
    """合併同一個月的開高低收與成交量值，回傳依日期排序的 list。

    兩支端點的交易日應一致，以開高低收為主，量值缺漏時以 0 計。
    """
    ohlc = fetch_ohlc_month(year, month)
    values = fetch_value_month(year, month)
    rows = []
    for date_str in sorted(ohlc):
        row = dict(ohlc[date_str])
        extra = values.get(date_str, {})
        row["volume"] = extra.get("volume", 0)
        row["turnover"] = extra.get("turnover", 0)
        row["change"] = extra.get("change")
        rows.append(row)
    missing = sorted(set(values) - set(ohlc))
    if missing:
        logger.warning("加權指數 %d-%02d 有 %d 個交易日只有量值沒有開高低收", year, month, len(missing))
    return rows
