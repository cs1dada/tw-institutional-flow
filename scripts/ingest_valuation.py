"""抓取題材分類個股的年度 EPS 共識 (估值趨勢矩陣用)。

資料來自 Yahoo Finance，只能取得當下的值，需每日執行才能累積歷史。
已納入 daily_job.py，這支腳本供單獨重抓或只抓指定幾檔。

用法：
    python scripts/ingest_valuation.py
    python scripts/ingest_valuation.py 2330 2454    # 只抓指定幾檔
"""
import sys

import _bootstrap

_bootstrap.setup_logging()

from app.db import connect, init_schema
from app.services.valuation import ingest_eps_estimates


def main():
    init_schema()
    conn = connect()
    try:
        stats = ingest_eps_estimates(conn, codes=sys.argv[1:] or None)
    finally:
        conn.close()
    print(f"{stats['date']} EPS 共識：{stats['saved']} / {stats['total']} 檔有分析師預估")
    if stats["foreign"]:
        foreign = " ".join(f"{code}({cur})" for code, cur in stats["foreign"].items())
        print(f"  外幣計價、已換算台幣：{foreign}")
    if stats["no_analysts"]:
        print(f"  沒有分析師人數：{stats['no_analysts']} 檔")
    if stats["missing"]:
        print(f"  沒有預估：{' '.join(stats['missing'])}")
    if stats["errors"]:
        print(f"  抓取失敗：{' '.join(stats['errors'])}")
        sys.exit(1)


if __name__ == "__main__":
    main()
