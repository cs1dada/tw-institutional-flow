"""復華投信的主動式 ETF 持股抓取。

資料來源為復華投信 ETF 專區的 assets API，回傳基金淨資產、發行單位數、
每單位淨值與資產明細。qDate 帶入日期即查詢該日的持股，回應的 dDate 等於 qDate。
假日或資料尚未公布時，回應的欄位全為 null；不帶 qDate 時網站回傳 HTML 頁面，
因此取最新一日時須由今天往回逐日查詢。
"""
import datetime
import logging
import time

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.fhtrust.com.tw/api/assets"
TIMEOUT = 30

# 查詢日即持股日，回補時直接查目標日期
QUERY_NEXT_DAY = False

# ETF 代號對應復華網站的基金編號。00409A、00998A 為海外 ETF，不列入
FUND_IDS = {
    "00991A": "ETF23",
}

# 資產明細中股票的類別名稱，其餘為「其他資產」(現金、應付買回款等)
FTYPE_STOCK = "股票"

# 取最新一日時最多往回查詢的天數
MAX_LOOKBACK_DAYS = 7

# 兩次請求之間的間隔秒數
REQUEST_INTERVAL = 2


def _to_number(value, cast):
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in ("--", "-", "None"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _normalize_date(text):
    """將 2026/10/02 轉為 20261002。"""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits if len(digits) == 8 else None


def _clean_text(text):
    """去除所有空白 (含全形空白)。"""
    return "".join(str(text or "").split())


def _stock_code(text):
    """取股票代號，去掉「2330 TT」之類的後綴與空白。"""
    parts = str(text or "").split()
    return parts[0] if parts else ""


def _query(session, fund_id, query_date):
    """查詢單一日期的資料，查無資料時回傳 None。"""
    resp = session.get(
        API_URL,
        params={"fundID": fund_id, "qDate": query_date.strftime("%Y/%m/%d")},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    for item in payload.get("result") or []:
        if item.get("dDate") and item.get("detail"):
            return item
    return None


def _query_latest(session, fund_id):
    """由今天往回逐日查詢，回傳最近一個有資料的日期。"""
    day = datetime.date.today()
    for i in range(MAX_LOOKBACK_DAYS):
        if i:
            time.sleep(REQUEST_INTERVAL)
        # 週末不會有資料，直接略過以減少請求
        if day.weekday() < 5:
            item = _query(session, fund_id, day)
            if item:
                return item
        day -= datetime.timedelta(days=1)
    return None


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則查詢該日。
    """
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("復華 %s 無對應的基金編號", etf_code)
        return None

    session = get_session()
    if query_date is None:
        item = _query_latest(session, fund_id)
    else:
        item = _query(session, fund_id, query_date)
    if not item:
        logger.warning("復華 %s 於 %s 查無持股資料", etf_code, query_date or "最近")
        return None

    date_str = _normalize_date(item.get("dDate"))
    if not date_str:
        logger.warning("復華 %s 未取得持股基準日，略過", etf_code)
        return None

    holdings = []
    for row in item.get("detail") or []:
        # 只取股票，其他資產 (現金、應付買回款等) 不列入持股
        if row.get("ftype") != FTYPE_STOCK:
            continue
        code = _stock_code(row.get("stockid"))
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": _clean_text(row.get("stockname")),
                "shares": _to_number(row.get("qshare"), int) or 0,
                "weight": _to_number(row.get("prate_addaccint"), float),
            }
        )

    if not holdings:
        logger.warning("復華 %s 於 %s 無股票持股資料", etf_code, date_str)
        return None

    logger.info("復華 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(item.get("pcf_Fundpnav"), float),
        "aum": _to_number(item.get("pcf_FundNav"), float),
        "units": _to_number(item.get("pcf_FundQissue"), int),
        "holdings": holdings,
    }
