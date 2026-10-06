"""凱基投信的主動式 ETF 持股抓取。

資料來源為凱基投信官網的申購買回清單 (RedemptionVC)，回傳 HTML 片段，
包含基金淨資產價值、已發行單位數、每單位淨值，以及依資產類別分段的持股表格。
查詢參數 queryDate 對應的是清單公告日，淨值與持股為前一營業日的資料；
頁面沒有獨立的持股日期欄位，以「(YYYY/MM/DD)每受益權單位淨資產價值」的淨值日作為持股日。
假日或無資料時會回傳 HTTP 500 的錯誤頁。
"""
import html
import logging
import re

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.kgifund.com.tw/Fund/RedemptionVC"
TIMEOUT = 30

# 查詢日是清單公告日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

# ETF 代號對應凱基內部的基金代號
FUND_IDS = {
    "00407A": "J024",
}

# 查無資料時網站回傳的 HTTP 狀態碼
NO_DATA_STATUS = (404, 500)

# 清單欄位名稱
LABEL_AUM = "基金淨資產價值"
LABEL_NAV = "每受益權單位淨資產價值"
LABEL_UNITS = "已發行受益權單位總數"

# 持股表格的欄位順序：股票代號、股票名稱、股數、權重
COL_CODE = 0
COL_NAME = 1
COL_SHARES = 2
COL_WEIGHT = 3

_ITEM_RE = re.compile(r"<li[^>]*>\s*<span>(.*?)</span>\s*<span>(.*?)</span>", re.S)
_SECTION_RE = re.compile(r'<h4[^>]*redemption-rest__sub-title[^>]*>(.*?)</h4>(.*?)(?=<h4|\Z)', re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _to_number(value, cast):
    text = re.sub(r"[^\d.\-]", "", str(value or ""))
    if not text or text in ("-", ".", "-."):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _normalize_date(text):
    """將 2026/09/10 轉為 20260910。"""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits if len(digits) == 8 else None


def _parse_summary(page):
    """擷取清單上方的淨值、規模、單位數與淨值日。"""
    nav = aum = units = None
    nav_date = None
    for raw_label, raw_value in _ITEM_RE.findall(page):
        label = _clean(raw_label)
        value = _clean(raw_value)
        match = re.match(r"\((\d{4}/\d{2}/\d{2})\)", label)
        if match:
            label = label[match.end():]
        if label.startswith(LABEL_NAV):
            nav = _to_number(value, float)
            if match:
                nav_date = _normalize_date(match.group(1))
        elif label.startswith(LABEL_AUM):
            aum = _to_number(value, float)
        elif label.startswith(LABEL_UNITS):
            units = _to_number(value, int)
    return nav, aum, units, nav_date


def _parse_stocks(page):
    """只解析標題為「股票」的表格，其餘 (現金、期貨等) 不列入持股。"""
    holdings = []
    for raw_title, body in _SECTION_RE.findall(page):
        if _clean(raw_title) != "股票":
            continue
        for row in _ROW_RE.findall(body):
            cells = [_clean(cell) for cell in _CELL_RE.findall(row)]
            if len(cells) <= COL_WEIGHT:
                continue
            code = cells[COL_CODE].strip()
            if not code:
                continue
            holdings.append(
                {
                    "stock_code": code,
                    "stock_name": cells[COL_NAME],
                    "shares": _to_number(cells[COL_SHARES], int) or 0,
                    "weight": _to_number(cells[COL_WEIGHT], float),
                }
            )
    return holdings


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單公告日查詢。
    """
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("凱基 %s 無對應的基金代號", etf_code)
        return None

    session = get_session()
    date_param = query_date.strftime("%Y/%m/%d") if query_date else ""
    resp = session.post(
        API_URL,
        data={"fundID": fund_id, "queryDate": date_param},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=TIMEOUT,
    )
    # 假日或無清單時網站回傳錯誤頁，視為查無資料
    if resp.status_code in NO_DATA_STATUS:
        logger.warning("凱基 %s 於 %s 無清單資料 (HTTP %d)", etf_code, date_param or "最新", resp.status_code)
        return None
    resp.raise_for_status()
    page = resp.text

    nav, aum, units, date_str = _parse_summary(page)
    if not date_str:
        logger.warning("凱基 %s 未取得淨值日，略過", etf_code)
        return None

    holdings = _parse_stocks(page)
    if not holdings:
        logger.warning("凱基 %s 無股票持股資料", etf_code)
        return None

    logger.info("凱基 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": nav,
        "aum": aum,
        "units": units,
        "holdings": holdings,
    }
