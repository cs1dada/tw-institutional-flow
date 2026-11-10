"""臺灣集中保管結算所 (集保) 的股權分散表。

開放資料只提供最新一週的全市場檔案，沒有參數可以指定日期。
過去一年的週次只能從網站的查詢頁逐檔查詢，那一頁有瀏覽器檢查，
程式無法直接送出，需要時以瀏覽器另外查詢後再匯入 (見 scripts/ingest_holders.py)。
"""
import csv
import io
import logging

from app.http_client import fetch

logger = logging.getLogger(__name__)

OPENDATA_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"


def fetch_latest():
    """下載最新一週的股權分散表，回傳 {date: [(code, level, people, shares, pct), ...]}。

    檔案通常只有一個資料日，仍以日期分組，避免日後格式改變時混在一起。
    """
    text = fetch(OPENDATA_URL, as_json=False, encoding="utf-8-sig")
    result = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            item = (
                row["證券代號"].strip(),
                int(row["持股分級"]),
                int(row["人數"]),
                int(row["股數"]),
                float(row["占集保庫存數比例%"]),
            )
        except (KeyError, ValueError) as exc:
            logger.warning("股權分散表格式不符，略過一列：%s %s", row, exc)
            continue
        result.setdefault(row["資料日期"].strip(), []).append(item)
    return result
