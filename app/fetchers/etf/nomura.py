"""野村投信的主動式 ETF 持股抓取。

資料來源為野村投信 ETF 專區的 GetFundAssets API，回傳當日持股明細與基金規模。
該 API 只提供最新一日的快照，沒有歷史，因此必須每日抓取並自行累積。
"""
import logging

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
TIMEOUT = 30

# 持股表格的欄位順序：股票代號、股票名稱、股數、權重
COL_CODE = 0
COL_NAME = 1
COL_SHARES = 2
COL_WEIGHT = 3


def _to_number(value, cast):
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in ("--", "-"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _normalize_date(text):
    """將 2026/09/10 轉為 20260910。"""
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return digits if len(digits) == 8 else None


def fetch_holdings(etf_code):
    """取得指定 ETF 的最新持股明細，無資料時回傳 None。"""
    session = get_session()
    resp = session.post(API_URL, json={"FundID": etf_code, "SearchDate": None}, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    data = (payload.get("Entries") or {}).get("Data") or {}
    asset = data.get("FundAsset") or {}
    date_str = _normalize_date(asset.get("NavDate"))
    if not date_str:
        logger.warning("野村 %s 未取得淨值日，略過", etf_code)
        return None

    holdings = []
    for table in data.get("Table") or []:
        # 只取股票表格，其餘 (現金、期貨等) 不列入持股
        if table.get("TableTitle") != "股票":
            continue
        for row in table.get("Rows") or []:
            if len(row) <= COL_WEIGHT:
                continue
            code = str(row[COL_CODE]).strip()
            if not code:
                continue
            holdings.append(
                {
                    "stock_code": code,
                    "stock_name": str(row[COL_NAME]).strip(),
                    "shares": _to_number(row[COL_SHARES], int) or 0,
                    "weight": _to_number(row[COL_WEIGHT], float),
                }
            )

    if not holdings:
        logger.warning("野村 %s 無股票持股資料", etf_code)
        return None

    logger.info("野村 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(asset.get("Nav"), float),
        "aum": _to_number(asset.get("Aum"), float),
        "units": _to_number(asset.get("Units"), int),
        "holdings": holdings,
    }
