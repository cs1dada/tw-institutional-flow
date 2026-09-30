"""回補個股的開高低收 (K 線圖用)。

與 backfill.py 的差別在於**只抓收盤行情，不抓法人買賣超**：

- 每個交易日只要 2 個請求 (上市、上櫃各一)，backfill.py 要 4 個
- 不寫 ingest_log，不影響法人資料的匯入狀態
- 因此可以回補得比法人資料更久遠，專供 K 線圖使用

證交所與櫃買的收盤行情本來就含開高低，這些欄位是後來才加進
daily_price 的，所以既有的資料需要跑一次這支腳本補齊。

用法：
    python scripts/backfill_ohlc.py 365                # 最近 365 個日曆日
    python scripts/backfill_ohlc.py 20250101 20260918  # 指定區間
    python scripts/backfill_ohlc.py 365 --force        # 連已補過的日期也重抓
"""
import sys
import time
from datetime import date, datetime, timedelta

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect, init_schema
from app.fetchers import tpex, twse

UPSERT = """
INSERT INTO daily_price (date, code, open, high, low, close, volume, turnover)
VALUES (:date, :code, :open, :high, :low, :close, :volume, :turnover)
ON CONFLICT(date, code) DO UPDATE SET
    open = excluded.open, high = excluded.high, low = excluded.low,
    close = excluded.close, volume = excluded.volume, turnover = excluded.turnover
"""


def date_range(start, end):
    """產生 start 到 end 之間的所有日期 (含頭尾)，由舊到新。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_args():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    if len(args) == 2:
        start = datetime.strptime(args[0], "%Y%m%d").date()
        end = datetime.strptime(args[1], "%Y%m%d").date()
    else:
        days = int(args[0]) if args else 365
        end = date.today()
        start = end - timedelta(days=days - 1)
    return start, end, force


def fetch_day(date_str):
    """抓取單一交易日的上市與上櫃收盤行情，回傳可直接寫入的記錄。

    任一市場失敗不中斷，只是那個市場當天沒有資料。
    """
    records = []
    for name, quotes in (
        ("上市", _safe(twse.fetch_quotes, date_str)),
        ("上櫃", _safe(tpex.fetch_quotes, date_str)),
    ):
        for code, quote in quotes.items():
            # 沒有收盤價代表當天沒有成交，畫不出 K 棒，直接略過
            if not quote.get("close"):
                continue
            records.append({
                "date": date_str,
                "code": code,
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume", 0),
                "turnover": quote.get("turnover", 0),
            })
    return records


def _safe(func, date_str):
    try:
        return func(date_str) or {}
    except Exception as exc:
        print(f"    {func.__module__.split('.')[-1]} 取得失敗：{exc}")
        return {}


def main():
    start, end, force = parse_args()
    init_schema()
    conn = connect()
    try:
        # 已經有開高低的日期就不必重抓。以 open 是否為空判斷，
        # 因為舊資料只有收盤價
        done = set()
        if not force:
            done = {
                row[0]
                for row in conn.execute(
                    "SELECT date FROM daily_price WHERE open IS NOT NULL GROUP BY date"
                )
            }

        targets = [d for d in date_range(start, end) if d.weekday() < 5]
        print(f"回補區間 {start} ~ {end}，共 {len(targets)} 個平日待處理")
        if done:
            print(f"其中 {len(done)} 個日期已有開高低，將略過（要重抓請加 --force）")

        ok_days = 0
        total = 0
        for index, day in enumerate(targets, 1):
            date_str = day.strftime("%Y%m%d")
            prefix = f"[{index}/{len(targets)}] {date_str}"
            if date_str in done:
                print(f"{prefix} 已有資料，略過")
                continue

            records = fetch_day(date_str)
            if records:
                conn.executemany(UPSERT, records)
                conn.commit()
                ok_days += 1
                total += len(records)
                print(f"{prefix} 完成，{len(records):,} 檔")
            else:
                print(f"{prefix} 非交易日")

            # 最後一天不需要再等
            if index < len(targets):
                time.sleep(config.THROTTLE_SECONDS)

        print(f"回補結束，{ok_days} 個交易日、共 {total:,} 筆")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
