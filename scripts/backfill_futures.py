"""回補期貨每日行情 (期貨 K 線圖用)。

資料來自期交所的「每日交易行情下載」，免費且不需認證，
與 Shioaji 的行情額度完全無關。

期交所單次查詢最多一個月，因此這支腳本按月推進：回補三年只要 36 個請求，
比證交所那邊的一天一請求有效率得多。

用法：
    python scripts/backfill_futures.py 1095            # 最近 1095 個日曆日
    python scripts/backfill_futures.py 20230101 20260918
    python scripts/backfill_futures.py 1095 --force    # 連已補過的月份也重抓
    python scripts/backfill_futures.py 1095 TMF TX     # 指定商品 (預設 TMF)
"""
import sys
import time
from datetime import date, datetime, timedelta

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect, init_schema
from app.fetchers import taifex

DEFAULT_COMMODITIES = ["TMF"]

UPSERT = """
INSERT INTO future_daily (
    date, commodity, contract_month, session,
    open, high, low, close, settlement, volume, open_interest
) VALUES (
    :date, :commodity, :contract_month, :session,
    :open, :high, :low, :close, :settlement, :volume, :open_interest
)
ON CONFLICT(date, commodity, contract_month, session) DO UPDATE SET
    open = excluded.open, high = excluded.high, low = excluded.low,
    close = excluded.close, settlement = excluded.settlement,
    volume = excluded.volume, open_interest = excluded.open_interest
"""


def parse_args():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv

    # 純數字或八位日期之外的參數視為商品代碼
    commodities = [a for a in args if not a.isdigit()]
    numbers = [a for a in args if a.isdigit()]

    if len(numbers) == 2 and all(len(n) == 8 for n in numbers):
        start = datetime.strptime(numbers[0], "%Y%m%d").date()
        end = datetime.strptime(numbers[1], "%Y%m%d").date()
    else:
        days = int(numbers[0]) if numbers else 1095
        end = date.today()
        start = end - timedelta(days=days - 1)

    return start, end, commodities or DEFAULT_COMMODITIES, force


def chunks(start, end):
    """把區間切成不超過期交所上限的小段。"""
    step = taifex.DAILY_MAX_DAYS - 1
    current = start
    while current <= end:
        stop = min(current + timedelta(days=step - 1), end)
        yield current, stop
        current = stop + timedelta(days=1)


def main():
    start, end, commodities, force = parse_args()
    init_schema()
    conn = connect()
    try:
        segments = list(chunks(start, end))
        print(f"回補區間 {start} ~ {end}，商品 {', '.join(commodities)}")
        print(f"期交所單次上限 {taifex.DAILY_MAX_DAYS} 天，共 {len(segments)} 段 × {len(commodities)} 個商品")

        total = 0
        for commodity in commodities:
            # 已有資料的日期就不必重抓
            done = set()
            if not force:
                done = {
                    row[0]
                    for row in conn.execute(
                        "SELECT date FROM future_daily WHERE commodity = ? GROUP BY date",
                        (commodity,),
                    )
                }

            for index, (seg_start, seg_end) in enumerate(segments, 1):
                prefix = f"[{commodity} {index}/{len(segments)}] {seg_start} ~ {seg_end}"

                # 整段都補過就跳過，不必發請求
                if not force and _segment_done(seg_start, seg_end, done):
                    print(f"{prefix} 已有資料，略過")
                    continue

                try:
                    rows = taifex.fetch_daily_bars(commodity, seg_start, seg_end)
                except Exception as exc:
                    print(f"{prefix} 失敗：{exc}")
                    continue

                if rows:
                    conn.executemany(UPSERT, rows)
                    conn.commit()
                    total += len(rows)
                    days = len({r["date"] for r in rows})
                    print(f"{prefix} 完成，{days} 個交易日、{len(rows):,} 列")
                else:
                    print(f"{prefix} 無資料")

                if index < len(segments):
                    time.sleep(config.THROTTLE_SECONDS)

        print(f"回補結束，共寫入 {total:,} 列")
    finally:
        conn.close()


def _segment_done(seg_start, seg_end, done):
    """這一段的所有平日是否都已經有資料。

    期交所的休市日不在 done 裡，因此只要有任何一個平日缺就重抓整段；
    寧可多抓一次，也不要留下缺口。
    """
    day = seg_start
    while day <= seg_end:
        if day.weekday() < 5 and day.strftime("%Y%m%d") not in done:
            return False
        day += timedelta(days=1)
    return True


if __name__ == "__main__":
    main()
