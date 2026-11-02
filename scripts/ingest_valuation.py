"""抓取題材分類個股的估值 (前瞻本益比)。

資料來自 Yahoo Finance，只能取得當下的值，需每日執行才能累積歷史。

用法：
    python scripts/ingest_valuation.py
    python scripts/ingest_valuation.py 2330 2454    # 只抓指定幾檔
"""
import sys

import _bootstrap

_bootstrap.setup_logging()

from app.db import connect, init_schema
from app.services.valuation import ingest_theme_valuations


def main():
    init_schema()
    conn = connect()
    try:
        stats = ingest_theme_valuations(conn, codes=sys.argv[1:] or None)
    finally:
        conn.close()
    print(
        f"{stats['date']} 估值：{stats['saved']} / {stats['total']} 檔有報價，"
        f"{stats['forward_pe']} 檔有前瞻本益比"
    )
    if stats["missing"]:
        print(f"  查無報價：{' '.join(stats['missing'])}")
    if stats["errors"]:
        print(f"  抓取失敗：{' '.join(stats['errors'])}")
        sys.exit(1)


if __name__ == "__main__":
    main()
