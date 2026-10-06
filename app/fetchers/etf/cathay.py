"""國泰投信的主動式 ETF 持股抓取。

資料來源為國泰投信 ETF 專區的兩支 API：
GetETFDetailStockList 回傳股票持股明細 (回應中沒有日期)，
GetETFAssets 回傳基金淨資產、在外流通單位數與每單位淨值，其 preDate 即持股基準日。
SearchDate 帶入日期即查詢該日的持股；若帶入當日而資料尚未產生，會回傳最近一日的資料，
假日則回傳 returnCode 4005 (查無資料)。
"""
import datetime
import logging
import time

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://cwapi.cathaysite.com.tw/api/ETF/GetETFDetailStockList"
ASSETS_URL = "https://cwapi.cathaysite.com.tw/api/ETF/GetETFAssets"
TIMEOUT = 30

# 查詢日即持股日，回補時直接查目標日期
QUERY_NEXT_DAY = False

# ETF 代號對應國泰網站的基金代碼 (可由 api/ETF/GetETFList 查得)
FUND_IDS = {
    "00400A": "EA",
}

# 成功的回應代碼
RETURN_OK = "2000"

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
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return digits if len(digits) == 8 else None


def _clean_text(text):
    """去除所有空白 (含全形空白)，例如「信  驊」轉為「信驊」。"""
    return "".join(str(text or "").split())


def _stock_code(text):
    """取股票代號，去掉「2330 TT」之類的後綴與空白。"""
    parts = str(text or "").split()
    return parts[0] if parts else ""


def _get_result(session, url, fund_code, search_date):
    """呼叫 API 並回傳 result，查無資料時回傳 None。"""
    resp = session.get(
        url, params={"FundCode": fund_code, "SearchDate": search_date}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success") or payload.get("returnCode") != RETURN_OK:
        return None
    return payload.get("result")


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則查詢該日。
    """
    fund_code = FUND_IDS.get(etf_code)
    if fund_code is None:
        logger.warning("國泰 %s 無對應的基金代碼", etf_code)
        return None

    session = get_session()
    # 未指定日期時以今天查詢，API 會回傳最近一個有資料的日期
    target = query_date or datetime.date.today()
    asset = _get_result(session, ASSETS_URL, fund_code, target.strftime("%Y-%m-%d"))
    if not asset:
        logger.warning("國泰 %s 於 %s 查無淨值資料", etf_code, target)
        return None

    date_str = _normalize_date(asset.get("preDate"))
    if not date_str:
        logger.warning("國泰 %s 未取得持股基準日，略過", etf_code)
        return None

    # 持股明細沒有日期，改以淨值的基準日查詢，確保兩者為同一天
    holding_date = datetime.datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    time.sleep(REQUEST_INTERVAL)
    rows = _get_result(session, API_URL, fund_code, holding_date) or []

    holdings = []
    for row in rows:
        code = _stock_code(row.get("stockCode"))
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": _clean_text(row.get("stockName")),
                "shares": _to_number(row.get("volumn"), int) or 0,
                "weight": _to_number(row.get("weights"), float),
            }
        )

    if not holdings:
        logger.warning("國泰 %s 於 %s 無股票持股資料", etf_code, date_str)
        return None

    logger.info("國泰 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(asset.get("fundPerNav"), float),
        "aum": _to_number(asset.get("fundNav"), float),
        "units": _to_number(asset.get("fundOutstandingShares"), int),
        "holdings": holdings,
    }
