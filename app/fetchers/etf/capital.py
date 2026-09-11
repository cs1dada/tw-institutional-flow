"""群益投信的主動式 ETF 持股抓取。

資料來源為群益投信 ETF 專區的申購買回清單 API。
回應中的 date1 是清單適用日 (次一營業日)，date2 才是持股的基準日，
與野村、統一的定義一致，因此採用 date2。
"""
import logging

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.capitalfund.com.tw/CFWeb/api/etf/buyback"
TIMEOUT = 30

# ETF 代號對應群益網站的基金編號
FUND_IDS = {
    "00982A": "399",
    "00992A": "500",
    "00997A": "502",
}


def _normalize_date(text):
    """將 2026-09-10 轉為 20260910。"""
    digits = "".join(ch for ch in str(text)[:10] if ch.isdigit())
    return digits if len(digits) == 8 else None


def fetch_holdings(etf_code):
    """取得指定 ETF 的最新持股明細，無資料時回傳 None。"""
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("群益 %s 無對應的基金編號", etf_code)
        return None

    session = get_session()
    resp = session.post(API_URL, json={"fundId": fund_id, "date": None}, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    data = payload.get("data") or {}
    pcf = data.get("pcf") or {}
    stocks = data.get("stocks") or []
    if not stocks:
        logger.warning("群益 %s 無股票持股", etf_code)
        return None

    date_str = _normalize_date(pcf.get("date2"))
    if not date_str:
        logger.warning("群益 %s 未取得持股基準日", etf_code)
        return None

    holdings = []
    for row in stocks:
        code = str(row.get("stocNo") or "").strip()
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("stocName") or "").strip(),
                "shares": int(row.get("share") or 0),
                "weight": row.get("weightRound") or row.get("weight"),
            }
        )

    if not holdings:
        return None

    logger.info("群益 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": pcf.get("pUnit"),
        "aum": pcf.get("nav"),
        "units": int(pcf["totUnit"]) if pcf.get("totUnit") else None,
        "holdings": holdings,
    }
