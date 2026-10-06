"""兆豐投信的主動式 ETF 持股抓取。

資料來源為兆豐投信 ETF 專區的申購買回清單頁面，為 ASP.NET WebForms，須以 postback 操作：
先 GET 頁面取得 __VIEWSTATE 等隱藏欄位，再 POST 選擇基金 (button1)，
最後以上一步回應的隱藏欄位 POST 查詢日期 (button2)。直接帶 ?id= 參數無效，
會顯示預設的基金，因此每次都要確認回應頁面的「股票代號：」確實是要查的那一檔。
查詢日期 qdt 對應的是清單適用日，查 D 日會取得前一營業日的持股；
持股基準日以「YYYY/MM/DD 每基數實際申購總價金」那一列的日期為準。
"""
import html
import logging
import re

from app.http_client import build_session

logger = logging.getLogger(__name__)

API_URL = "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx"
TIMEOUT = 30

# 查詢日是清單適用日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

# ETF 代號對應兆豐網站內部的基金編號 (fund_id)
FUND_IDS = {
    "00996A": "23",
}

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"

_HIDDEN_RE = re.compile(r"<input[^>]*type=\"hidden\"[^>]*>", re.I)
_ATTR_RE = re.compile(r"(name|value)=\"([^\"]*)\"")
_ETF_CODE_RE = re.compile(r"股票代號[：:]\s*(\w+)")
_LIST_DATE_RE = re.compile(r"class=\"announcement-title\">\s*(\d{4}/\d{2}/\d{2})")
_BASE_DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})\s*每基數實際申購總價金")
_STOCK_BLOCK_RE = re.compile(
    r"<h2 class=\"titel-stock\">\s*股票\s*</h2>.*?<tbody[^>]*>(.*?)</tbody>", re.S
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def _to_number(value, cast):
    text = str(value or "").replace(",", "").replace("%", "").replace("TWD$", "").strip()
    if not text or text in ("--", "-"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def _hidden_fields(page):
    """取出頁面上所有隱藏欄位 (__VIEWSTATE、__EVENTVALIDATION 等)。"""
    fields = {}
    for tag in _HIDDEN_RE.findall(page):
        attrs = dict(_ATTR_RE.findall(tag))
        if attrs.get("name"):
            fields[attrs["name"]] = html.unescape(attrs.get("value", ""))
    return fields


def _post(session, page, fund_id, button, qdt):
    data = _hidden_fields(page)
    data.update(
        {
            FIELD_PREFIX + "category_id": "",
            FIELD_PREFIX + "fund_id": fund_id,
            FIELD_PREFIX + button: "查 詢",
            FIELD_PREFIX + "qdt": qdt,
        }
    )
    resp = session.post(API_URL, data=data, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def _field(page, title):
    """取得清單公告中，標題為 title 的那一項數值。"""
    match = re.search(
        r"<div class=\"ann-title\">\s*" + re.escape(title)
        + r"\s*</div>\s*<div class=\"ann-content\">(.*?)</div>",
        page,
        re.S,
    )
    return _clean(match.group(1)) if match else None


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單適用日查詢。
    """
    fund_id = FUND_IDS.get(etf_code)
    if fund_id is None:
        logger.warning("兆豐 %s 無對應的基金編號", etf_code)
        return None

    # 以獨立 session 處理 ASP.NET 的 cookie 與 postback 狀態
    session = build_session()
    resp = session.get(API_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    # 先切換到指定基金，回應即為最新一日的清單
    page = _post(session, resp.text, fund_id, "button1", "")
    if query_date:
        qdt = query_date.strftime("%Y/%m/%d")
        page = _post(session, page, fund_id, "button2", qdt)
    else:
        qdt = None

    # 確認回傳的是要查的那一檔，避免把預設基金的持股當成該檔
    code_match = _ETF_CODE_RE.search(page)
    actual_code = code_match.group(1) if code_match else None
    if actual_code != etf_code:
        logger.warning("兆豐 %s 的基金編號 %s 實際對應 %s，略過", etf_code, fund_id, actual_code)
        return None

    # 查詢日無清單時，確認頁面顯示的清單日與查詢日一致
    list_match = _LIST_DATE_RE.search(page)
    list_date = list_match.group(1) if list_match else None
    if qdt and list_date != qdt:
        logger.warning("兆豐 %s 查詢 %s 回傳清單日 %s，略過", etf_code, qdt, list_date)
        return None

    block = _STOCK_BLOCK_RE.search(page)
    if not block:
        logger.warning("兆豐 %s 無股票區塊", etf_code)
        return None

    holdings = []
    for row in _ROW_RE.findall(block.group(1)):
        cells = [_clean(cell) for cell in _CELL_RE.findall(row)]
        if len(cells) < 4:
            continue
        code = cells[0].split(" ")[0].strip()
        if not code:
            continue
        holdings.append(
            {
                "stock_code": code,
                "stock_name": cells[1],
                "shares": _to_number(cells[2], int) or 0,
                "weight": _to_number(cells[3], float),
            }
        )

    if not holdings:
        logger.warning("兆豐 %s 無股票持股資料", etf_code)
        return None

    base_match = _BASE_DATE_RE.search(page)
    if not base_match:
        logger.warning("兆豐 %s 未取得持股基準日", etf_code)
        return None
    date_str = "".join(base_match.groups())

    logger.info("兆豐 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(_field(page, "每受益權單位淨資產價值(元)"), float),
        "aum": _to_number(_field(page, "基金淨資產價值(元)"), float),
        "units": _to_number(_field(page, "已發行受益權單位總數"), int),
        "holdings": holdings,
    }
