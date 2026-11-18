"""FRED (聖路易聯邦準備銀行) 經濟資料。

使用網頁下載圖表資料用的 CSV 端點，不需要 API 金鑰。可一次查多個序列，
偽裝成瀏覽器的 User-Agent 會被擋，見 config.FRED_USER_AGENT。
回應第一欄為日期 (YYYY-MM-DD)，之後依序為各序列的值；休市日的值是空字串。
"""
import csv
import io

from app import config
from app.http_client import fetch


def fetch_fred_daily(series_ids, start):
    """取得多個 FRED 序列自 start (date) 起的日資料，回傳 {序列代號: [(YYYYMMDD, 值)]}。"""
    text = fetch(
        config.FRED_CSV_URL,
        # 起始日要每個序列各給一個，只給一個時只有第一個序列會套用
        params={"id": ",".join(series_ids), "cosd": ",".join([start.isoformat()] * len(series_ids))},
        as_json=False,
        headers={"User-Agent": config.FRED_USER_AGENT},
    )
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        return {sid: [] for sid in series_ids}
    names = header[1:]
    result = {name: [] for name in names}
    for row in reader:
        if len(row) != len(header) or len(row[0]) != 10:
            continue
        day = row[0].replace("-", "")
        for name, raw in zip(names, row[1:]):
            raw = raw.strip()
            # 舊版 CSV 以 "." 表示缺值，新版為空字串
            if not raw or raw == ".":
                continue
            try:
                result[name].append((day, float(raw)))
            except ValueError:
                continue
    return result
