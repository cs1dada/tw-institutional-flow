"""第一金投信的主動式 ETF 持股抓取。

資料來源為第一金投信官網的 WebAPI：Get_hd 回傳持股明細，Get_BuySellA 回傳
申購買回清單 (含基金淨資產價值、每單位淨值與已發行單位數)。
兩者的回應外層皆為 {"d": "<JSON 字串>"}，需再解析一次。

查詢參數 pStrDate 對應的是清單公告日，查 D 日會取得前一營業日的持股；
空字串為最新一日，假日或無資料時 d 為 null 或空字串。
持股明細依 group 分組：1 為股票、4 為現金、5 為資產配置，只取股票。
"""
import json
import logging
import re

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.fsitc.com.tw/WebAPI.aspx/Get_hd"
BUYSELL_URL = "https://www.fsitc.com.tw/WebAPI.aspx/Get_BuySellA"
TIMEOUT = 30

# 查詢日是清單公告日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

# ETF 代號對應第一金內部的基金代號
FUND_IDS = {
    "00408A": "183",
    "00994A": "182",
}

# 持股明細中代表股票的分組
STOCK_GROUP = "1"

# 申購買回清單中的欄位名稱 (以開頭比對，後面可能帶「-台幣交易」等說明)
LABEL_AUM = "基金淨資產價值"
LABEL_NAV = "每受益權單位淨資產價值"
LABEL_UNITS = "已發行受益權單位總數"


def _to_number(value, cast):
    text = re.sub(r"[^\d.\-]", "", str(value or ""))
    if not text or text in ("-", ".", "-."):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _normalize_date(text):
    """將 2026-09-10 轉為 20260910。"""
    digits = "".join(ch for ch in str(text or "")[:10] if ch.isdigit())
    return digits if len(digits) == 8 else None


def _post(url, fund_id, date_param):
    """呼叫 WebAPI 並解開外層的 d 字串，無資料時回傳 None。"""
    session = get_session()
    resp = session.post(
        url, json={"pStrFundID": fund_id, "pStrDate": date_param}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    inner = resp.json().get("d")
    if not inner or not str(inner).strip():
        return None
    try:
        return json.loads(inner)
    except ValueError:
        logger.warning("第一金 %s 回應內容無法解析", url)
        return None


def _parse_buysell(rows, holding_date):
    """從申購買回清單擷取淨值、規模與單位數。

    清單中「YYYY-MM-DD 每基數...」的日期即淨值日，與持股日不一致時不採用，
    避免把不同日期的淨值配到持股上。
    """
    nav = aum = units = None
    nav_date = None
    for row in rows or []:
        label = str(row.get("A") or "").strip()
        value = row.get("B")
        if label.startswith(LABEL_AUM):
            aum = _to_number(value, float)
        elif label.startswith(LABEL_NAV):
            nav = _to_number(value, float)
        elif label.startswith(LABEL_UNITS):
            units = _to_number(value, int)
        else:
            match = re.match(r"(\d{4}-\d{2}-\d{2})\s", label)
            if match and nav_date is None:
                nav_date = _normalize_date(match.group(1))
    if nav_date and nav_date != holding_date:
        logger.warning("第一金 清單淨值日 %s 與持股日 %s 不一致，不採用淨值資料", nav_date, holding_date)
        return None, None, None
    return nav, aum, units


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單公告日查詢。
    """
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("第一金 %s 無對應的基金代號", etf_code)
        return None

    date_param = query_date.strftime("%Y/%m/%d") if query_date else ""
    rows = _post(API_URL, fund_id, date_param)
    if not rows:
        logger.warning("第一金 %s 於 %s 無持股資料", etf_code, date_param or "最新")
        return None

    holdings = []
    date_str = None
    for row in rows:
        if str(row.get("fundid") or fund_id) != fund_id:
            continue
        if str(row.get("group")) != STOCK_GROUP:
            continue
        code = str(row.get("A") or "").strip()
        if not code:
            continue
        if date_str is None:
            date_str = _normalize_date(row.get("sdate"))
        holdings.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("B") or "").strip(),
                "shares": _to_number(row.get("D"), int) or 0,
                "weight": _to_number(row.get("C"), float),
            }
        )

    if not holdings:
        logger.warning("第一金 %s 無股票持股資料", etf_code)
        return None
    if not date_str:
        logger.warning("第一金 %s 未取得持股日期，略過", etf_code)
        return None

    nav, aum, units = _parse_buysell(_post(BUYSELL_URL, fund_id, date_param), date_str)

    logger.info("第一金 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": nav,
        "aum": aum,
        "units": units,
        "holdings": holdings,
    }
