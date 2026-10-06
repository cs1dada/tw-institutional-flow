"""永豐投信的主動式 ETF 持股抓取。

資料來源為永豐投信 ETF 專區的申購買回清單 (PCF) 頁面，以 POST 表單查詢並回傳 HTML。
表單參數 hDate 對應的是清單適用日，因此查 D 日會取得前一營業日的持股；
頁面中的「資料日期」才是持股的基準日，因此採用該日期。
查無清單 (假日、上市前) 時頁面只有一段「無此PCF資料」的 alert 腳本。
"""
import html
import logging
import re

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://sitc.sinopac.com/SinopacEtfs/Etfs/Pcf/{fund_id}"
TIMEOUT = 30

# 查詢日是清單適用日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

# ETF 代號對應永豐網站的基金編號 (目前與證券代號相同)
FUND_IDS = {
    "00410A": "00410A",
}

# 持股表格的欄位順序：證券代碼、證券名稱、股數、權重
COL_CODE = 0
COL_NAME = 1
COL_SHARES = 2
COL_WEIGHT = 3

_RE_DATA_DATE = re.compile(r"資料日期：\s*(\d{4}/\d{2}/\d{2})")
_RE_STOCK_SECTION = re.compile(r'<div class="cash_title-s">\s*股票\s*</div>(.*?)</table>', re.S)
_RE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_RE_TAG = re.compile(r"<[^>]+>")


def _to_number(value, cast):
    text = str(value).replace(",", "").replace("NT$", "").replace("%", "").strip()
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


def _cell_text(raw):
    """去除標籤與 HTML 實體，回傳儲存格純文字。"""
    text = html.unescape(_RE_TAG.sub("", raw)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_rows(table_html):
    rows = []
    for row in _RE_ROW.findall(table_html):
        rows.append([_cell_text(cell) for cell in _RE_CELL.findall(row)])
    return rows


def _asset_value(page, label):
    """從基金資產表格取得指定項目的數值文字。"""
    match = re.search(
        r"<td[^>]*>\s*" + re.escape(label) + r"\s*</td>\s*<td[^>]*>(.*?)</td>", page, re.S
    )
    return _cell_text(match.group(1)) if match else None


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單適用日查詢。
    """
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("永豐 %s 無對應的基金編號", etf_code)
        return None

    session = get_session()
    form = {"fundId": fund_id, "op": "1"}
    if query_date:
        form["hDate"] = query_date.strftime("%Y-%m-%d")
    resp = session.post(API_URL.format(fund_id=fund_id), data=form, timeout=TIMEOUT)
    resp.raise_for_status()
    page = resp.text

    date_match = _RE_DATA_DATE.search(page)
    date_str = _normalize_date(date_match.group(1)) if date_match else None
    if not date_str:
        logger.warning("永豐 %s 查無申購買回清單", etf_code)
        return None

    section = _RE_STOCK_SECTION.search(page)
    holdings = []
    if section:
        for cells in _parse_rows(section.group(1)):
            # 標題列使用 th，_parse_rows 也會收進來，以股數是否為數字排除
            if len(cells) <= COL_WEIGHT:
                continue
            code = cells[COL_CODE].replace(" ", "").split(".")[0]
            shares = _to_number(cells[COL_SHARES], int)
            if not code or shares is None:
                continue
            holdings.append(
                {
                    "stock_code": code,
                    "stock_name": cells[COL_NAME],
                    "shares": shares,
                    "weight": _to_number(cells[COL_WEIGHT], float),
                }
            )

    if not holdings:
        logger.warning("永豐 %s 無股票持股資料", etf_code)
        return None

    logger.info("永豐 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(_asset_value(page, "基金每單位淨值(元)") or "", float),
        "aum": _to_number(_asset_value(page, "基金淨資產價值(元)") or "", float),
        "units": _to_number(_asset_value(page, "基金在外流通單位數") or "", int),
        "holdings": holdings,
    }
