"""匯入大盤指數 (加權指數) 日線。

證交所以月為單位提供資料，因此參數也以月為單位。

用法：
    python scripts/ingest_index.py                  # 只更新當月
    python scripts/ingest_index.py 60               # 回補最近 60 個月
    python scripts/ingest_index.py 202101 202609    # 指定起訖年月
"""
import sys
from datetime import date

import _bootstrap

_bootstrap.setup_logging()

from app.db import init_schema
from app.services.index_ingest import ingest_index_range, month_range, recent_months


def parse_period(text):
    """將 YYYYMM 轉為 (年, 月)。"""
    if len(text) != 6 or not text.isdigit():
        raise SystemExit(f"年月格式應為 YYYYMM：{text}")
    return int(text[:4]), int(text[4:])


def main():
    init_schema()
    args = sys.argv[1:]
    if len(args) >= 2:
        periods = list(month_range(parse_period(args[0]), parse_period(args[1])))
    elif len(args) == 1:
        periods = recent_months(int(args[0]))
    else:
        today = date.today()
        periods = [(today.year, today.month)]

    total = ingest_index_range(periods)
    first, last = periods[0], periods[-1]
    print(
        f"加權指數匯入完成：{first[0]}-{first[1]:02d} ~ {last[0]}-{last[1]:02d}，"
        f"共 {total} 個交易日"
    )


if __name__ == "__main__":
    main()
