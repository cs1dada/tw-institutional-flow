"""統一投信的主動式 ETF 持股抓取。

資料來源為統一投信 ETF 專區的申購買回清單 (PCF) API，
內含當日成分股明細、基金淨資產與已發行單位數。
API 以統一內部的基金代碼查詢，因此需要 ETF 代號對照表。
"""
import logging
from datetime import date

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
TIMEOUT = 30

# ETF 代號對應統一投信內部的基金代碼
FUND_CODES = {
    "00403A": "63YTW",
    "00411A": "64YTW",
    "00981A": "49YTW",
    "00988A": "61YTW",
}

# PCF 項目代碼
PCF_NET_ASSET = "NAV"        # 基金淨資產價值(元)
PCF_OUT_UNIT = "OUT_UNIT"    # 已發行受益權單位總數


def _roc_today():
    """今天的民國日期，格式為 115/09/11。"""
    today = date.today()
    return f"{today.year - 1911}/{today.month:02d}/{today.day:02d}"


def _normalize_date(text):
    """將 2026-09-10T00:00:00 轉為 20260910。"""
    digits = "".join(ch for ch in str(text)[:10] if ch.isdigit())
    return digits if len(digits) == 8 else None


def _pcf_amount(rows, code):
    for row in rows or []:
        if row.get("PCFCode") == code:
            return row.get("Amount")
    return None


def fetch_holdings(etf_code):
    """取得指定 ETF 的最新持股明細，無資料時回傳 None。"""
    fund_code = FUND_CODES.get(etf_code)
    if fund_code is None:
        logger.warning("統一 %s 無對應的基金代碼", etf_code)
        return None

    session = get_session()
    resp = session.post(
        API_URL,
        json={"fundCode": fund_code, "date": _roc_today(), "specificDate": False},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    # 確認回傳的確實是要查的那一檔，避免對照表過期時抓錯基金
    stock_no = (payload.get("fund") or {}).get("sStockNo", "").strip()
    if stock_no and stock_no != etf_code:
        logger.warning("統一 %s 的基金代碼 %s 實際對應 %s，略過", etf_code, fund_code, stock_no)
        return None

    stock_asset = None
    for asset in payload.get("asset") or []:
        if asset.get("AssetCode") == "ST":
            stock_asset = asset
            break
    if not stock_asset:
        logger.warning("統一 %s 無股票部位", etf_code)
        return None

    details = stock_asset.get("Details") or []
    if not details:
        return None

    date_str = _normalize_date(details[0].get("TranDate"))
    if not date_str:
        logger.warning("統一 %s 未取得持股日期", etf_code)
        return None

    holdings = []
    for row in details:
        code = str(row.get("DetailCode") or "").strip()
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("DetailName") or "").strip(),
                "shares": int(row.get("Share") or 0),
                "weight": row.get("NavRate"),
            }
        )

    if not holdings:
        return None

    pcf_rows = payload.get("pcf") or []
    aum = _pcf_amount(pcf_rows, PCF_NET_ASSET)
    units = _pcf_amount(pcf_rows, PCF_OUT_UNIT)
    nav = round(aum / units, 4) if aum and units else None

    logger.info("統一 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": nav,
        "aum": aum,
        "units": int(units) if units else None,
        "holdings": holdings,
    }
