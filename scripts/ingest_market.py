"""匯入大盤籌碼 (三大法人金額、融資融券與維持率)、櫃買指數、匯率與 VIX。

籌碼每個交易日要 4 個請求，交易日曆取自加權指數，因此要先跑過 ingest_index.py。
每日排程 (daily_job.py) 已會呼叫這裡的流程，每次補一部分缺漏；
這支腳本供手動一次回補較多天，或重抓指定日期。

用法：
    python scripts/ingest_market.py                 # 補最近缺漏的日期，最多 20 天
    python scripts/ingest_market.py 250             # 最多補 250 天 (約一小時)
    python scripts/ingest_market.py --date 20261104 # 重抓指定日期
"""
import sys

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect, init_schema
from app.services.market_ingest import (
    ingest_chip_date,
    ingest_macro,
    ingest_pending_chip,
    ingest_tpex_index,
)


def main():
    init_schema()
    args = sys.argv[1:]
    conn = connect()
    try:
        if len(args) == 2 and args[0] == "--date":
            ingest_chip_date(args[1], conn=conn)
            return

        limit = int(args[0]) if args else config.MARKET_BACKFILL_PER_RUN
        print(f"櫃買指數更新 {ingest_tpex_index(conn)} 個交易日")
        counts = ingest_macro(conn)
        print("總體指標：" + "、".join(f"{k} {v} 筆" for k, v in counts.items()))
        dates = ingest_pending_chip(conn=conn, limit=limit)
        print(f"大盤籌碼抓取 {len(dates)} 個交易日")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
