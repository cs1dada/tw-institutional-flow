"""大盤籌碼與總體指標的抓取。

- 三大法人買賣金額：證交所 BFI82U、櫃買 insti/summary，皆為全市場合計 (元)
- 融資融券餘額：證交所 MI_MARGN、櫃買 margin/balance，同時取回逐檔融資張數，
  供融資維持率估算
- 櫃買指數：櫃買 indexInfo/inx，一次回傳整月
- 台指 VIX：期交所每月日收盤檔
- 美元兌台幣、美國 VIX：Yahoo Finance 日線

所有函式在來源尚未公布或查無資料時回傳 None 或空容器，不丟例外，
由呼叫端決定是否之後再重抓。
"""
import logging
from datetime import datetime, timedelta, timezone

from app import config
from app.fetchers.tpex import to_tpex_date
from app.fetchers.twse import to_float, to_int
from app.http_client import fetch

logger = logging.getLogger(__name__)

SHARES_PER_LOT = 1000

# BFI82U 與櫃買彙總表的「買賣差額」欄位
INST_NET_COLUMN = 3

# MI_MARGN 合計表的「今日餘額」欄位、逐檔表的「融資今日餘額」欄位
TWSE_MARGIN_SUMMARY_BALANCE = 5
TWSE_MARGIN_CODE = 0
TWSE_MARGIN_UNITS = 6

# 櫃買融資融券表的欄位
TPEX_MARGIN_CODE = 0
TPEX_MARGIN_NAME = 1
TPEX_MARGIN_UNITS = 6
TPEX_SHORT_UNITS = 14

# 櫃買指數月表的欄位
TPEX_INDEX_DATE = 0
TPEX_INDEX_OPEN = 1
TPEX_INDEX_HIGH = 2
TPEX_INDEX_LOW = 3
TPEX_INDEX_CLOSE = 4
TPEX_INDEX_CHANGE = 5
TPEX_INDEX_MIN_COLUMNS = 6


def _clean_name(value):
    """櫃買的子項目以全形空白縮排，比對前一律去掉。"""
    return str(value).replace("　", "").strip()


def _tables(payload):
    return payload.get("tables") or []


# ---------------------------------------------------------------------------
# 三大法人買賣金額
# ---------------------------------------------------------------------------

def fetch_twse_inst_summary(date_str):
    """上市三大法人買賣金額，回傳 {foreign_net, trust_net, dealer_net, total_net} (元)。

    外資含外資自營商、自營商含自行買賣與避險，與 T86 個股資料的口徑一致。
    """
    payload = fetch(
        config.TWSE_INST_SUMMARY_URL,
        params={"type": "day", "dayDate": date_str, "response": "json"},
    )
    if payload.get("stat") != "OK" or not payload.get("data"):
        return None

    result = {"foreign_net": 0.0, "trust_net": 0.0, "dealer_net": 0.0, "total_net": None}
    for raw in payload["data"]:
        if len(raw) <= INST_NET_COLUMN:
            continue
        name = _clean_name(raw[0])
        net = float(to_int(raw[INST_NET_COLUMN]))
        if name.startswith("合計"):
            result["total_net"] = net
        elif "外資" in name:
            result["foreign_net"] += net
        elif "投信" in name:
            result["trust_net"] += net
        elif name.startswith("自營商"):
            result["dealer_net"] += net
    if result["total_net"] is None:
        return None
    return result


def fetch_tpex_inst_summary(date_str):
    """上櫃三大法人買賣金額，格式同 fetch_twse_inst_summary。

    櫃買的表同時列出合計與子項目，這裡只取合計列，避免重複加總。
    """
    payload = fetch(
        config.TPEX_INST_SUMMARY_URL,
        params={"type": "Daily", "date": to_tpex_date(date_str), "response": "json"},
    )
    tables = _tables(payload)
    if not tables or not tables[0].get("data"):
        return None

    result = {}
    for raw in tables[0]["data"]:
        if len(raw) <= INST_NET_COLUMN:
            continue
        name = _clean_name(raw[0])
        net = float(to_int(raw[INST_NET_COLUMN]))
        if name.startswith("外資及陸資合計"):
            result["foreign_net"] = net
        elif name == "投信":
            result["trust_net"] = net
        elif name.startswith("自營商合計"):
            result["dealer_net"] = net
        elif name.startswith("三大法人合計"):
            result["total_net"] = net
    if len(result) < 4:
        logger.warning("上櫃三大法人彙總表 %s 欄位不齊：%s", date_str, sorted(result))
        return None
    return result


# ---------------------------------------------------------------------------
# 融資融券
# ---------------------------------------------------------------------------

def fetch_twse_margin(date_str):
    """上市融資融券，回傳合計與逐檔融資張數。

    {margin_amount (元), margin_units (張), short_units (張), stocks: {代號: 融資張數}}
    """
    payload = fetch(
        config.TWSE_MARGIN_URL,
        params={"date": date_str, "selectType": "ALL", "response": "json"},
    )
    tables = _tables(payload)
    if payload.get("stat") != "OK" or len(tables) < 2 or not tables[0].get("data"):
        return None

    result = {"margin_amount": None, "margin_units": None, "short_units": None}
    for raw in tables[0]["data"]:
        if len(raw) <= TWSE_MARGIN_SUMMARY_BALANCE:
            continue
        name = _clean_name(raw[0])
        balance = to_int(raw[TWSE_MARGIN_SUMMARY_BALANCE])
        if name.startswith("融資金額"):
            # 單位為仟元
            result["margin_amount"] = float(balance) * 1000
        elif name.startswith("融資"):
            result["margin_units"] = balance
        elif name.startswith("融券"):
            result["short_units"] = balance
    if result["margin_amount"] is None:
        return None

    stocks = {}
    for raw in tables[1].get("data") or []:
        if len(raw) <= TWSE_MARGIN_UNITS:
            continue
        units = to_int(raw[TWSE_MARGIN_UNITS])
        if units:
            stocks[str(raw[TWSE_MARGIN_CODE]).strip()] = units
    result["stocks"] = stocks
    return result


def fetch_tpex_margin(date_str):
    """上櫃融資融券，格式同 fetch_twse_margin。

    櫃買沒有獨立的合計表，合計列放在表格的 summary：代號空白、名稱為
    「合計(張)」與「融資金(仟元)」。
    """
    payload = fetch(
        config.TPEX_MARGIN_URL,
        params={"date": to_tpex_date(date_str), "response": "json"},
    )
    tables = _tables(payload)
    if not tables or not tables[0].get("data"):
        return None

    result = {"margin_amount": None, "margin_units": None, "short_units": None}
    stocks = {}
    for raw in tables[0]["data"] + (tables[0].get("summary") or []):
        if len(raw) <= TPEX_SHORT_UNITS:
            continue
        code = str(raw[TPEX_MARGIN_CODE]).strip()
        if code:
            units = to_int(raw[TPEX_MARGIN_UNITS])
            if units:
                stocks[code] = units
            continue
        name = _clean_name(raw[TPEX_MARGIN_NAME])
        if name.startswith("融資金"):
            result["margin_amount"] = float(to_int(raw[TPEX_MARGIN_UNITS])) * 1000
        elif name.startswith("合計"):
            result["margin_units"] = to_int(raw[TPEX_MARGIN_UNITS])
            result["short_units"] = to_int(raw[TPEX_SHORT_UNITS])
    if result["margin_amount"] is None:
        return None
    result["stocks"] = stocks
    return result


# ---------------------------------------------------------------------------
# 櫃買指數
# ---------------------------------------------------------------------------

def fetch_tpex_index_month(year, month):
    """指定月份的櫃買指數日線，回傳依日期排序的 list，欄位與 index_daily 相同。"""
    payload = fetch(
        config.TPEX_INDEX_URL,
        params={"date": f"{year:04d}/{month:02d}/01", "response": "json"},
    )
    tables = _tables(payload)
    if not tables or not tables[0].get("data"):
        logger.info("櫃買指數 %d-%02d 無資料", year, month)
        return []

    rows = []
    for raw in tables[0]["data"]:
        if len(raw) < TPEX_INDEX_MIN_COLUMNS:
            continue
        date_str = str(raw[TPEX_INDEX_DATE]).strip().replace("/", "")
        if len(date_str) != 8 or not date_str.isdigit():
            continue
        rows.append({
            "date": date_str,
            "open": to_float(raw[TPEX_INDEX_OPEN]),
            "high": to_float(raw[TPEX_INDEX_HIGH]),
            "low": to_float(raw[TPEX_INDEX_LOW]),
            "close": to_float(raw[TPEX_INDEX_CLOSE]),
            # 櫃買指數表沒有成交量值
            "volume": 0,
            "turnover": 0,
            "change": to_float(raw[TPEX_INDEX_CHANGE]),
        })
    return sorted(rows, key=lambda row: row["date"])


# ---------------------------------------------------------------------------
# 總體指標
# ---------------------------------------------------------------------------

def fetch_tw_vix_month(year, month):
    """台指 VIX 指定月份的每日收盤值，回傳 [(日期, 值)]。

    檔案為 Big5 文字檔，每列為「日期 時間 指數 收盤前一分鐘平均」，
    以 Tab 分隔。期交所只保留近一年，更早的月份回傳 404 網頁，視為無資料。
    """
    url = config.TAIFEX_VIX_MONTH_URL.format(month=f"{year:04d}{month:02d}")
    text = fetch(url, as_json=False, encoding="big5")
    if text.lstrip().startswith("<"):
        return []
    rows = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 3 or len(tokens[0]) != 8 or not tokens[0].isdigit():
            continue
        value = to_float(tokens[2])
        if value is not None:
            rows.append((tokens[0], value))
    return rows


def fetch_yahoo_daily(symbol, range_=config.MACRO_YAHOO_RANGE):
    """Yahoo Finance 日收盤，回傳 [(日期, 值)]，日期為該商品交易所的當地日期。

    時間戳記是 UTC，加上回應裡的 gmtoffset 才是當地日期；
    例如美國 VIX 的日期是美國時間，對台股而言是「前一晚」。
    """
    payload = fetch(
        config.YAHOO_CHART_URL.format(symbol=symbol),
        params={"range": range_, "interval": "1d"},
    )
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    offset = timedelta(seconds=(result.get("meta") or {}).get("gmtoffset") or 0)
    stamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []

    rows = {}
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        local = datetime.fromtimestamp(stamp, tz=timezone.utc) + offset
        # 同一天有兩筆時 (盤中的即時值) 以後者為準
        rows[local.strftime("%Y%m%d")] = round(float(close), 4)
    return sorted(rows.items())
