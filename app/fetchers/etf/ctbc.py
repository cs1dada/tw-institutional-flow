"""中國信託投信的主動式 ETF 持股抓取。

資料來源為中信 ETF 專區的申購買回清單 API。
該 API 需要先向 AuthToken 取得動態權杖，再以基金內部代號 (FID) 查詢；
回傳的 Detail 依資產類別分組，其中 Code 為 STOCK 的才是股票持股。
"""
import logging
import urllib.parse
from datetime import date

from app.http_client import get_session

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.ctbcinvestments.com.tw/API/home/AuthToken?token=www.ctbcinvestments.com"
BUYBACK_URL = "https://www.ctbcinvestments.com.tw/API/etf/Buyback"
TIMEOUT = 30

# ETF 代號對應中信內部的基金代號
FUND_IDS = {
    "00406A": "E0038",
    "00983A": "E0034",
    "00995A": "E0036",
}

_token = None


def _get_token(refresh=False):
    """取得 API 權杖，同一次執行中重複使用。"""
    global _token
    if _token and not refresh:
        return _token
    session = get_session()
    resp = session.post(AUTH_URL, json={}, timeout=TIMEOUT)
    resp.raise_for_status()
    _token = resp.json()["Data"]["token"]
    return _token


def _to_number(value, cast):
    text = str(value).replace(",", "").strip()
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


def fetch_holdings(etf_code):
    """取得指定 ETF 的最新持股明細，無資料時回傳 None。"""
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("中信 %s 無對應的基金代號", etf_code)
        return None

    session = get_session()
    token = _get_token()
    url = BUYBACK_URL + "?token=" + urllib.parse.quote(token, safe="")
    body = {"token": token, "FID": fund_id, "StartDate": date.today().strftime("%Y-%m-%d")}
    resp = session.post(url, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    # 權杖過期時重新取得再試一次
    if payload.get("ResultCode") != 0:
        token = _get_token(refresh=True)
        url = BUYBACK_URL + "?token=" + urllib.parse.quote(token, safe="")
        body["token"] = token
        resp = session.post(url, json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()

    data = payload.get("Data") or {}
    info_rows = data.get("Data") or []
    if not info_rows:
        logger.warning("中信 %s 無清單資料", etf_code)
        return None
    info = info_rows[0]

    # 確認回傳的是要查的那一檔
    etf_id = str(info.get("ETF_ID") or "").strip()
    if etf_id and etf_id != etf_code:
        logger.warning("中信 %s 的基金代號 %s 實際對應 %s，略過", etf_code, fund_id, etf_id)
        return None

    stock_group = None
    for group in data.get("Detail") or []:
        if group.get("Code") == "STOCK":
            stock_group = group
            break
    if not stock_group or not stock_group.get("Data"):
        logger.warning("中信 %s 無股票部位", etf_code)
        return None

    date_str = _normalize_date(info.get("NAV_DATE") or info.get("淨值日期"))
    if not date_str:
        logger.warning("中信 %s 未取得淨值日期", etf_code)
        return None

    holdings = []
    for row in stock_group["Data"]:
        code = str(row.get("code_") or "").strip()
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("name_") or "").strip(),
                "shares": _to_number(row.get("qty_"), int) or 0,
                "weight": _to_number(row.get("weights_"), float),
            }
        )

    if not holdings:
        return None

    logger.info("中信 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(info.get("每受益權單位淨資產價值"), float),
        "aum": _to_number(info.get("基金淨資產價值"), float),
        "units": _to_number(info.get("已發行受益權單位總數"), int),
        "holdings": holdings,
    }
