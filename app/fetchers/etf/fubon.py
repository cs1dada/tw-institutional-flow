"""富邦投信的主動式 ETF 持股抓取。

資料來源為富邦 ETF 專區的基金資產頁面 (ASP.NET 伺服器端頁面)。
直接 GET 取得最新一日；查詢歷史需先 GET 取得 __VIEWSTATE 等隱藏欄位，
再帶查詢日期與查詢按鈕欄位 POST 回同一網址。
查詢日即持股日，頁面中的「資料日期」為持股基準日，因此採用該日期。

注意：查詢非營業日 (例如週六) 時，網站會往前退到最近一個營業日的持股，
而不是回傳查無資料，因此回傳的 date 可能早於 query_date。
回補程式以回傳的 date 為準，且已存在的日期會略過，不影響正確性。
基金成立前的日期只會回傳警語頁面，此時回傳 None。
"""
import html
import logging
import re

from app.http_client import build_session

logger = logging.getLogger(__name__)

API_URL = "https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx"
TIMEOUT = 30

# 查詢日即持股日，回補時直接查目標日期
QUERY_NEXT_DAY = False

# ASP.NET 表單控制項的名稱前綴
FIELD_PREFIX = "ctl00$ctl00$mainContent$subMainContent$"

# 持股表格的欄位順序：股票代碼、股票名稱、股數、金額、權重
COL_CODE = 0
COL_NAME = 1
COL_SHARES = 2
COL_AMOUNT = 3
COL_WEIGHT = 4

_RE_INPUT = re.compile(r"<input\b[^>]*>", re.I)
_RE_ATTR = re.compile(r'(\w+)="([^"]*)"')
_RE_DATA_DATE = re.compile(r"資料日期：\s*(\d{4}/\d{2}/\d{2})")
_RE_STOCK_SECTION = re.compile(r"<h6[^>]*>\s*股票\s*</h6>(.*?)</table>", re.S)
_RE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RE_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_RE_TAG = re.compile(r"<[^>]+>")


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


def _cell_text(raw):
    """去除標籤與 HTML 實體，回傳儲存格純文字。"""
    text = html.unescape(_RE_TAG.sub("", raw)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _form_fields(page):
    """收集頁面表單欄位，排除送出按鈕 (查詢時再另外帶入查詢按鈕)。"""
    fields = {}
    for tag in _RE_INPUT.findall(page):
        attrs = {key.lower(): html.unescape(value) for key, value in _RE_ATTR.findall(tag)}
        name = attrs.get("name")
        if not name or attrs.get("type", "").lower() == "submit":
            continue
        fields[name] = attrs.get("value", "")
    return fields


def _search_button_value(page):
    match = re.search(
        r'<input[^>]*name="' + re.escape(FIELD_PREFIX + "btnSearch") + r'"[^>]*value="([^"]*)"',
        page,
    )
    return html.unescape(match.group(1)) if match else "查 詢"


def _asset_value(page, label):
    """從基金資產區塊取得指定項目 (以標題開頭比對) 的數值文字。"""
    match = re.search(
        r"<p>\s*" + re.escape(label) + r"[^<]*</p>\s*<p>(.*?)</p>", page, re.S
    )
    return _cell_text(match.group(1)) if match else ""


def _load_page(etf_code, query_date):
    """取得基金資產頁面 HTML。指定日期時先 GET 取隱藏欄位再 POST 查詢。"""
    session = build_session()
    url = API_URL + "?stkId=" + etf_code
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    if query_date is None:
        return resp.text

    search_date = query_date.strftime("%Y/%m/%d")
    form = _form_fields(resp.text)
    form["as_fid"] = ""
    form[FIELD_PREFIX + "sDate"] = search_date
    form[FIELD_PREFIX + "hidSearchsDate"] = search_date
    form[FIELD_PREFIX + "btnSearch"] = _search_button_value(resp.text)
    resp = session.post(url, data=form, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則查詢該日；
    非營業日會得到前一營業日的持股 (見模組說明)。
    """
    page = _load_page(etf_code, query_date)

    date_match = _RE_DATA_DATE.search(page)
    date_str = _normalize_date(date_match.group(1)) if date_match else None
    section = _RE_STOCK_SECTION.search(page)
    if not date_str or not section:
        logger.warning("富邦 %s 查無持股資料", etf_code)
        return None

    holdings = []
    for row in _RE_ROW.findall(section.group(1)):
        cells = [_cell_text(cell) for cell in _RE_CELL.findall(row)]
        if len(cells) <= COL_WEIGHT:
            continue
        code = cells[COL_CODE].replace(" ", "").split(".")[0]
        shares = _to_number(cells[COL_SHARES], int)
        # 標題列與「股票合計」列的股數不是數字，一併排除
        if not code or shares is None:
            continue
        holdings.append(
            {
                "stock_code": code,
                # 名稱後的 * 為網站註記符號，不屬於股票名稱
                "stock_name": cells[COL_NAME].rstrip("*").strip(),
                "shares": shares,
                "weight": _to_number(cells[COL_WEIGHT], float),
            }
        )

    if not holdings:
        logger.warning("富邦 %s 無股票持股資料", etf_code)
        return None

    logger.info("富邦 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(_asset_value(page, "基金每單位淨值"), float),
        "aum": _to_number(_asset_value(page, "基金淨資產"), float),
        "units": _to_number(_asset_value(page, "基金在外流通單位數"), int),
        "holdings": holdings,
    }
