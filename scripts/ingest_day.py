"""匯入指定日期的三大法人資料。

用法：
    python scripts/ingest_day.py 20260909
    python scripts/ingest_day.py            # 不帶參數則匯入今日
"""
import sys
from datetime import date

import _bootstrap

_bootstrap.setup_logging()

from app.services.ingest import ingest_date


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y%m%d")
    total = ingest_date(date_str)
    print(f"{date_str} 匯入完成，共 {total} 筆")


if __name__ == "__main__":
    main()
