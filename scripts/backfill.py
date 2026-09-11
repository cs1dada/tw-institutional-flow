"""回補歷史資料。

用法：
    python scripts/backfill.py 30              # 回補最近 30 個日曆日
    python scripts/backfill.py 20260810 20260910   # 回補指定日期區間
"""
import sys
import time
from datetime import date, datetime, timedelta

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect
from app.services.ingest import ingest_date


def date_range(start, end):
    """產生 start 到 end 之間的所有日期 (含頭尾)，由舊到新。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_args():
    if len(sys.argv) == 3:
        start = datetime.strptime(sys.argv[1], "%Y%m%d").date()
        end = datetime.strptime(sys.argv[2], "%Y%m%d").date()
    else:
        days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
        end = date.today()
        start = end - timedelta(days=days - 1)
    return start, end


def main():
    start, end = parse_args()
    conn = connect()
    try:
        done = {
            row[0]
            for row in conn.execute(
                "SELECT date FROM ingest_log WHERE status IN ('ok', 'no_data')"
                " GROUP BY date HAVING COUNT(*) = 2"
            )
        }
        targets = [d for d in date_range(start, end) if d.weekday() < 5]
        print(f"回補區間 {start} ~ {end}，共 {len(targets)} 個平日待處理")

        ok_days = 0
        for index, day in enumerate(targets, 1):
            date_str = day.strftime("%Y%m%d")
            if date_str in done:
                print(f"[{index}/{len(targets)}] {date_str} 已匯入，略過")
                continue
            try:
                count = ingest_date(date_str, conn=conn)
            except Exception as exc:
                print(f"[{index}/{len(targets)}] {date_str} 失敗：{exc}")
                continue
            if count:
                ok_days += 1
                print(f"[{index}/{len(targets)}] {date_str} 完成，{count} 筆")
            else:
                print(f"[{index}/{len(targets)}] {date_str} 非交易日")
            if index < len(targets):
                time.sleep(config.THROTTLE_SECONDS)
        print(f"回補結束，實際有資料的交易日 {ok_days} 天")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
