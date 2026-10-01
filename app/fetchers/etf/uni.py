"""統一投信的主動式 ETF 持股抓取。

資料來源為統一投信 ETF 專區的申購買回清單 (PCF) API，
內含當日成分股明細、基金淨資產與已發行單位數。
API 以統一內部的基金代碼查詢，因此需要 ETF 代號對照表。
指定日期 (specificDate) 查詢時，date 對應的是清單適用日，會取得前一營業日的持股。
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
TIMEOUT = 30

# 查詢日是清單適用日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

TAIPEI = timezone(timedelta(hours=8))

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


def _roc_date(day):
    """民國日期，格式為 115/09/11。"""
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def _normalize_date(text):
    """將 2026-09-10T00:00:00 或 /Date(1788105600000)/ 轉為 20260910。

    指定日期查詢時回傳的是 .NET 的毫秒時間戳，以台北時間換算日期。
    """
    match = re.fullmatch(r"/Date\((\d+)\)/", str(text))
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, TAIPEI).strftime("%Y%m%d")
    digits = "".join(ch for ch in str(text)[:10] if ch.isdigit())
    return digits if len(digits) == 8 else None


def _pcf_amount(rows, code):
    for row in rows or []:
        if row.get("PCFCode") == code:
            return row.get("Amount")
    return None


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單適用日查詢。
    """
    fund_code = FUND_CODES.get(etf_code)
    if fund_code is None:
        logger.warning("統一 %s 無對應的基金代碼", etf_code)
        return None

    session = get_session()
    resp = session.post(
        API_URL,
        json={
            "fundCode": fund_code,
            "date": _roc_date(query_date or date.today()),
            "specificDate": query_date is not None,
        },
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
