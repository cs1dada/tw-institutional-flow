"""安聯投信的主動式 ETF 持股抓取。

資料來源為安聯投信主動式 ETF 專區的交易資訊 API。
呼叫前需先取得 AntiForgery 權杖，並以 x-xsrf-token 標頭送出；
持股放在 DynamicTableData 中標題以「股票」開頭的表格。
"""
import logging

from app.http_client import get_session

logger = logging.getLogger(__name__)

TOKEN_URL = "https://etf.allianzgi.com.tw/webapi/api/AntiForgery/GetAntiForgeryToken"
API_URL = "https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundTradeInfo"
REFERER = "https://etf.allianzgi.com.tw/list-trade"
TIMEOUT = 30

# ETF 代號對應安聯內部的基金編號
FUND_NOS = {
    "00402A": "E0003",
    "00984A": "E0001",
    "00993A": "E0002",
}

# 持股表格的欄位順序：序號、股票代號、股票名稱、股數、權重
COL_CODE = 1
COL_NAME = 2
COL_SHARES = 3
COL_WEIGHT = 4
MIN_COLUMNS = 5

_token = None


def _get_token(refresh=False):
    """取得 AntiForgery 權杖，同一次執行中重複使用。"""
    global _token
    if _token and not refresh:
        return _token
    session = get_session()
    resp = session.get(TOKEN_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    _token = resp.json()["token"]
    return _token


def _to_number(value, cast):
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in ("--", "-"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _normalize_date(text):
    """將 2026-09-10T00:00:00 轉為 20260910。"""
    digits = "".join(ch for ch in str(text)[:10] if ch.isdigit())
    return digits if len(digits) == 8 else None


def _request(fund_no, token):
    session = get_session()
    return session.post(
        API_URL,
        json={"Date": None, "FundNo": fund_no},
        headers={"x-xsrf-token": token, "Referer": REFERER},
        timeout=TIMEOUT,
    )


def fetch_holdings(etf_code):
    """取得指定 ETF 的最新持股明細，無資料時回傳 None。"""
    fund_no = FUND_NOS.get(etf_code)
    if fund_no is None:
        logger.warning("安聯 %s 無對應的基金編號", etf_code)
        return None

    resp = _request(fund_no, _get_token())
    # 權杖過期時重新取得再試一次
    if resp.status_code == 400:
        resp = _request(fund_no, _get_token(refresh=True))
    resp.raise_for_status()

    entries = resp.json().get("Entries") or {}
    if not entries:
        logger.warning("安聯 %s 無交易資訊", etf_code)
        return None

    # 確認回傳的是要查的那一檔
    code = str(entries.get("CSecuritiesCode") or "").strip()
    if code and code != etf_code:
        logger.warning("安聯 %s 的基金編號 %s 實際對應 %s，略過", etf_code, fund_no, code)
        return None

    date_str = _normalize_date(entries.get("CNavDt"))
    if not date_str:
        logger.warning("安聯 %s 未取得淨值日期", etf_code)
        return None

    holdings = []
    for table in entries.get("DynamicTableData") or []:
        if not str(table.get("TableTitle") or "").startswith("股票"):
            continue
        for row in table.get("Rows") or []:
            if len(row) < MIN_COLUMNS:
                continue
            stock_code = str(row[COL_CODE]).strip()
            if not stock_code:
                continue
            holdings.append(
                {
                    "stock_code": stock_code,
                    "stock_name": str(row[COL_NAME]).strip(),
                    "shares": _to_number(row[COL_SHARES], int) or 0,
                    "weight": _to_number(row[COL_WEIGHT], float),
                }
            )

    if not holdings:
        logger.warning("安聯 %s 無股票持股", etf_code)
        return None

    logger.info("安聯 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": entries.get("CAnceNav"),
        "aum": entries.get("CAnceTotalAv"),
        "units": int(entries["CAnceTotalIssues"]) if entries.get("CAnceTotalIssues") else None,
        "holdings": holdings,
    }
