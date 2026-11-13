"""把集保股權分散的歷史 CSV 轉成 data/holders_manual/ 的補查檔案。

集保開放資料只有最新一週，過去的週次要另外取得。這支腳本讀取整理好的 CSV
(欄位：資料日期,證券代號,證券名稱,市場別,類別,序,持股分級,人數,股數,占集保庫存數比例%)，
只保留題材分類的個股，每週輸出一個 {YYYYMMDD}.json，之後由 ingest_holders.py 匯入。

CSV 與補查檔案的差異：

- 合計的序不固定：有差異數調整時第 16 級是調整、第 17 級是合計；
  沒有調整時第 16 級就是合計。補查檔案的合計固定放在第 17 級，沒有調整時省略第 16 級
- 差異數調整的人數是空白，轉為 0

已存在的週檔會合併：保留檔案中原有的個股，只補上沒有的個股。
資料庫已有開放資料的週次 (預設為最新一週) 可以用 --skip 略過。

用法：
    python scripts/convert_tdcc_csv.py tdcc_shareholding_1y/tdcc_shareholding_1y.csv --skip 20261106
"""
import argparse
import csv
import json
from collections import defaultdict

import _bootstrap

_bootstrap.setup_logging()

from app.services.holders import MANUAL_DIR
from app.services.themes import classified_codes, load_themes

TOTAL_LABEL = "合計"
TOTAL_LEVEL = 17
ADJUST_LEVEL = 16
LAST_HOLDING_LEVEL = 15


def number(text, cast):
    text = text.strip().replace(",", "")
    return cast(text) if text else cast(0)


def convert_row(row):
    """CSV 的一列轉為 [級距, 人數, 股數, 比例]，合計一律改為第 17 級"""
    level = int(row["序"])
    if row["持股分級"].strip() == TOTAL_LABEL:
        level = TOTAL_LEVEL
    return [
        level,
        number(row["人數"], int),
        number(row["股數"], int),
        number(row["占集保庫存數比例%"], float),
    ]


def read_csv(path, codes):
    """回傳 {date: {code: [[級距, 人數, 股數, 比例], ...]}}，只保留 codes 中的個股"""
    weeks = defaultdict(lambda: defaultdict(list))
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = row["證券代號"].strip()
            if code in codes:
                weeks[row["資料日期"].strip()][code].append(convert_row(row))
    for stocks in weeks.values():
        for levels in stocks.values():
            levels.sort(key=lambda lv: lv[0])
    return weeks


def check(date, stocks):
    """每檔都要有 1~15 級與合計，比例加總接近 100%，回傳有問題的代號"""
    bad = []
    for code, levels in stocks.items():
        found = {lv[0] for lv in levels}
        holding = sum(lv[3] for lv in levels if lv[0] <= LAST_HOLDING_LEVEL)
        if not set(range(1, LAST_HOLDING_LEVEL + 1)) <= found or TOTAL_LEVEL not in found or abs(holding - 100) > 0.5:
            bad.append(code)
    if bad:
        print(f"  {date} 格式異常 {len(bad)} 檔，略過：{', '.join(bad[:10])}")
    return bad


def write_week(path, stocks):
    """與既有補查檔案相同的排版：一檔一行，方便版控比對"""
    lines = [f"{json.dumps(code)}:{json.dumps(levels, separators=(',', ':'))}" for code, levels in sorted(stocks.items())]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n" + ",\n".join(lines) + "\n}\n")


def main():
    parser = argparse.ArgumentParser(description="集保股權分散歷史 CSV 轉為補查檔案")
    parser.add_argument("csv", help="CSV 檔案路徑")
    parser.add_argument("--skip", nargs="*", default=[], help="略過的資料日 (已有開放資料的週次)")
    args = parser.parse_args()

    codes = classified_codes(load_themes())
    weeks = read_csv(args.csv, codes)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    covered = set()
    for date in sorted(weeks):
        if date in args.skip:
            print(f"{date} 略過")
            continue
        stocks = weeks[date]
        for code in check(date, stocks):
            del stocks[code]
        path = MANUAL_DIR / f"{date}.json"
        merged = dict(stocks)
        kept = 0
        if path.exists():
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
            # 既有檔案的個股優先，不覆蓋
            merged.update(existing)
            kept = len(existing)
        write_week(path, merged)
        covered |= set(merged)
        note = f"，保留既有 {kept} 檔" if kept else ""
        print(f"{date} {len(merged)} 檔{note}")

    print(f"共 {len(weeks) - len(set(args.skip) & set(weeks))} 週，題材股 {len(codes)} 檔中有資料 {len(covered)} 檔")
    missing = sorted(codes - covered)
    if missing:
        print(f"CSV 中沒有資料的題材股 {len(missing)} 檔：{', '.join(missing)}")


if __name__ == "__main__":
    main()
