"""台新投信的主動式 ETF 持股抓取。

資料來源為台新投信 ETF 專區的申購買回清單頁面 (伺服器端產生的 HTML)。
查詢參數 DataDate 對應的是清單適用日，查 D 日會取得前一營業日的持股；
頁面沒有直接標示持股基準日，以「YYYY/M/D每基數實際申購總價金」那一列的日期為準。
股票與期貨分屬不同區塊，只取「股票」區塊；非交易日同樣回 HTTP 200，但沒有股票列。
"""
import html
import logging
import re

from app.http_client import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.tsit.com.tw/ETF/Home/Pcf/{etf_code}"
TIMEOUT = 30

# 查詢日是清單適用日，要取得 D 日的持股須查次一營業日
QUERY_NEXT_DAY = True

# 目前介接的 ETF (00986A 為海外 ETF，不在此列)
FUND_IDS = {
    "00987A": "00987A",
}

# 股票區塊：卡片標題為「股票」，其後第一個 tbody 即持股明細
_STOCK_BLOCK_RE = re.compile(r"</svg>\s*股票\s*</div>.*?<tbody>(.*?)</tbody>", re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_BASE_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s*每基數實際申購總價金")


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def _to_number(value, cast):
    text = str(value).replace(",", "").replace("%", "").replace("TWD", "").strip()
    if not text or text in ("--", "-"):
        return None
    # 會計格式的負數以括號表示
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return cast(float(text))
    except ValueError:
        return None


def _field(page, title):
    """取得基金資訊表格中，標題為 title 的那一列數值。"""
    match = re.search(
        r"<th>\s*" + re.escape(title) + r"\s*</th>\s*<td>(.*?)</td>", page, re.S
    )
    return _clean(match.group(1)) if match else None


def _base_date(page):
    """取得持股基準日 (即實際申購總價金所屬日期)，轉為 YYYYMMDD。"""
    match = _BASE_DATE_RE.search(page)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}{month:02d}{day:02d}"


def fetch_holdings(etf_code, query_date=None):
    """取得指定 ETF 的持股明細，無資料時回傳 None。

    query_date 為 None 時取最新一日，否則以該日為清單適用日查詢。
    """
    if etf_code not in FUND_IDS:
        logger.warning("台新 %s 不在介接清單中", etf_code)
        return None

    params = {"FundType": "ALL"}
    if query_date:
        params["DataDate"] = query_date.strftime("%Y-%m-%d")
    session = get_session()
    resp = session.get(
        API_URL.format(etf_code=FUND_IDS[etf_code]), params=params, timeout=TIMEOUT
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    page = resp.text

    # 確認頁面標題是要查的那一檔
    if f"({etf_code})" not in page:
        logger.warning("台新 %s 回傳頁面不是該檔 ETF，略過", etf_code)
        return None

    block = _STOCK_BLOCK_RE.search(page)
    if not block:
        logger.warning("台新 %s 無股票區塊", etf_code)
        return None

    holdings = []
    for row in _ROW_RE.findall(block.group(1)):
        cells = [_clean(cell) for cell in _CELL_RE.findall(row)]
        # 合計列只有兩欄 (colspan)，持股列為代號、名稱、股數、權重四欄
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
        logger.warning("台新 %s 無股票持股資料", etf_code)
        return None

    date_str = _base_date(page)
    if not date_str:
        logger.warning("台新 %s 未取得持股基準日", etf_code)
        return None

    logger.info("台新 %s 於 %s 取得 %d 檔持股", etf_code, date_str, len(holdings))
    return {
        "etf_code": etf_code,
        "date": date_str,
        "nav": _to_number(_field(page, "每受益權單位淨資產價值(元)"), float),
        "aum": _to_number(_field(page, "基金淨資產價值(元)"), float),
        "units": _to_number(_field(page, "已發行受益權單位總數"), int),
        "holdings": holdings,
    }
