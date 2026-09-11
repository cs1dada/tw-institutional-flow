"""從證交所 ISIN 對照表取得個股的中文產業別。

上市與上櫃共用同一套產業分類名稱，因此兩個市場的資料可以合併統計。
CFI Code 用來判斷證券類型，權證 (RW)、受益證券 (CB)、債券 (DA) 等
不屬於類股統計範圍，於此階段直接排除。
"""
import logging
import re

from app import config
from app.http_client import fetch

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>", re.S)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
# 有價證券代號及名稱的格式為「1101 台泥」
CODE_NAME_RE = re.compile(r"^([0-9A-Z]{4,6})\s+(.+)$")
# 特別股代號為母股代號加上一碼英文字母，例如 1101B 對應 1101
PREFERRED_CODE_RE = re.compile(r"^(\d{4})[A-Z]$")

# CFI Code 前兩碼對應的證券類型
CFI_TYPES = {
    "ES": "stock",      # 普通股
    "CE": "etf",        # ETF
    "CM": "etn",        # ETN
    "EP": "preferred",  # 特別股
    "EF": "preferred",  # 特別股 (金融)
    "ED": "dr",         # 台灣存託憑證
}

INDUSTRY_BY_TYPE = {
    "etf": config.INDUSTRY_ETF,
    "etn": config.INDUSTRY_ETF,
    "dr": "存託憑證",
}


def _clean(text):
    """去除 HTML 標籤、全形空白與前後空白。"""
    return TAG_RE.sub("", text).replace("\u3000", " ").replace("&nbsp;", " ").strip()


def _parse_rows(html, market):
    """解析 ISIN 對照表 HTML，回傳原始列資料。"""
    rows = []
    for row_html in TR_RE.findall(html):
        cells = [_clean(td) for td in TD_RE.findall(row_html)]
        if len(cells) < 6:
            continue
        matched = CODE_NAME_RE.match(cells[0])
        if not matched:
            continue
        sec_type = CFI_TYPES.get(cells[5][:2].upper())
        if sec_type is None:
            continue
        rows.append(
            {
                "code": matched.group(1),
                "name": matched.group(2).strip(),
                "market": market,
                "industry": cells[4].strip(),
                "sec_type": sec_type,
            }
        )
    return rows


def fetch_stock_info(market):
    """取得指定市場的個股主檔清單。

    回傳 list[dict]，欄位為 code / name / market / industry / is_etf。
    """
    html = fetch(
        config.ISIN_URL,
        params={"strMode": config.ISIN_MODE[market]},
        as_json=False,
        encoding=config.ISIN_ENCODING,
    )
    rows = _parse_rows(html, market)
    # 先建立普通股的產業別對照，供特別股回頭補值使用
    industry_of_common = {
        r["code"]: r["industry"] for r in rows if r["sec_type"] == "stock" and r["industry"]
    }

    results = []
    for row in rows:
        industry = row["industry"]
        if not industry:
            if row["sec_type"] == "preferred":
                # 特別股沿用母股的產業別，例如 1101B 台泥乙特歸入水泥工業
                parent = PREFERRED_CODE_RE.match(row["code"])
                industry = industry_of_common.get(parent.group(1), "") if parent else ""
            if not industry:
                industry = INDUSTRY_BY_TYPE.get(row["sec_type"], config.INDUSTRY_UNKNOWN)
        results.append(
            {
                "code": row["code"],
                "name": row["name"],
                "market": market,
                "industry": industry,
                "is_etf": 1 if row["sec_type"] in ("etf", "etn") else 0,
            }
        )
    logger.info("%s 個股主檔取得 %d 筆", market, len(results))
    return results
