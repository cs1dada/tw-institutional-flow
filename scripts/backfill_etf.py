"""回補主動式 ETF 的歷史持股。

各投信的 API 都能以日期查詢過去的持股，但日期語意不同：
野村查的是持股日本身，其餘投信查的是清單適用日 (取得前一營業日的持股)，
因此後者要補 D 日須查次一營業日。交易日以資料庫 daily_price 為準。

由新到舊逐日回補，已存在的日期自動略過；連續數個交易日都查不到時視為
已超出該檔的上市日或投信保留的範圍 (例如中信只保留近期)，停止往前查。

用法：
    python scripts/backfill_etf.py 92                        # 最近 92 個日曆日
    python scripts/backfill_etf.py 20260701 20260929         # 指定區間
    python scripts/backfill_etf.py 92 00980A 00981A          # 只補指定幾檔
"""
import sys
import time
from datetime import date, datetime, timedelta

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect, init_schema
from app.fetchers import etf
from app.services.etf_ingest import fetch_with_retry, save_holdings

# 連續查不到幾個交易日就停止往前
MAX_EMPTY_STREAK = 3


def parse_args():
    args = sys.argv[1:]
    dates = [a for a in args if not a.upper().endswith("A")]
    codes = [a.upper() for a in args if a.upper().endswith("A")]
    if len(dates) == 2:
        start = datetime.strptime(dates[0], "%Y%m%d").date()
        end = datetime.strptime(dates[1], "%Y%m%d").date()
    else:
        days = int(dates[0]) if dates else 92
        end = date.today()
        start = end - timedelta(days=days - 1)
    return start, end, codes or etf.supported_etfs()


def load_trading_days(conn):
    """資料庫中所有交易日，由舊到新。"""
    return [
        datetime.strptime(row[0], "%Y%m%d").date()
        for row in conn.execute("SELECT DISTINCT date FROM daily_price ORDER BY date")
    ]


def next_weekday(day):
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _fetch(code, query_date):
    """查詢一次持股，失敗或查無資料回傳 None。每次查詢後固定間隔，避免對投信造成負擔。"""
    try:
        data = fetch_with_retry(code, query_date)
    except Exception as exc:
        print(f"  {code} 查 {query_date} 失敗：{exc}")
        data = None
    time.sleep(config.THROTTLE_SECONDS)
    return data


def _save_new(conn, code, data, done):
    """以 API 回傳的持股日寫入，該日已存在時略過。回傳寫入的天數。

    海外持股的 ETF 基準日可能落後台股交易日，回傳日期不一定等於目標日，
    但資料本身屬於回傳的那一天，因此不會錯置。
    """
    returned = data["date"]
    if returned in done:
        return 0
    save_holdings(conn, code, data)
    done.add(returned)
    print(f"  {code} {returned} {len(data['holdings'])} 檔持股")
    return 1


def backfill_one(conn, code, targets, next_day_of):
    """回補單一 ETF，回傳 (寫入天數, 略過天數)。"""
    done = {
        row[0]
        for row in conn.execute("SELECT date FROM etf_snapshot WHERE etf_code = ?", (code,))
    }
    use_next_day = etf.query_next_day(code)
    written = skipped = empty_streak = 0

    for day in reversed(targets):
        date_str = day.strftime("%Y%m%d")
        if date_str in done:
            skipped += 1
            continue

        query_date = next_day_of[day] if use_next_day else day
        data = _fetch(code, query_date)
        if not data:
            empty_streak += 1
            if empty_streak >= MAX_EMPTY_STREAK:
                print(f"  {code} 連續 {empty_streak} 個交易日查無資料，停在 {date_str}")
                break
            continue

        empty_streak = 0
        written += _save_new(conn, code, data, done)

        # 基準日落後 (多為海外持股) 時，再往後查一個營業日才取得到目標日
        if data["date"] < date_str:
            later = next_day_of.get(query_date) or next_weekday(query_date)
            data = _fetch(code, later)
            if data:
                written += _save_new(conn, code, data, done)
            if date_str not in done:
                print(f"  {code} {date_str} 查 {query_date}、{later} 皆未取得")

    return written, skipped


def main():
    start, end, codes = parse_args()
    init_schema()
    conn = connect()
    try:
        trading_days = load_trading_days(conn)
        # 次一營業日：區間最後一天之後的交易日若尚未匯入，以下一個平日代替
        next_day_of = {
            day: trading_days[i + 1] if i + 1 < len(trading_days) else next_weekday(day)
            for i, day in enumerate(trading_days)
        }
        targets = [d for d in trading_days if start <= d <= end]
        print(f"回補區間 {start} ~ {end}，{len(targets)} 個交易日，{len(codes)} 檔 ETF")

        summary = []
        for code in codes:
            if etf.issuer_of(code) is None:
                print(f"{code} 尚未介接，略過")
                continue
            print(f"{code} ({etf.issuer_of(code)})")
            written, skipped = backfill_one(conn, code, targets, next_day_of)
            summary.append((code, written, skipped))

        print("回補結束")
        for code, written, skipped in summary:
            print(f"  {code}  新增 {written} 天，已存在 {skipped} 天")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
