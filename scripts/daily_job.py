"""每日排程進入點。

執行內容：
1. 個股主檔超過 7 天未更新時重新抓取 (新上市、產業重分類)
2. 匯入今日資料
3. 抓取主動式 ETF 持股快照 (各投信只提供當日資料，必須每日累積)
4. 補抓近 7 天內只收錄到單一市場的日期
   (上市約 16:00 才公布，若排程跑得早會只拿到上櫃)

用法：
    python scripts/daily_job.py
"""
import time
from datetime import date, datetime, timedelta

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect
from app.services.etf_ingest import ingest_etf_holdings
from app.services.ingest import ingest_date, update_stock_info

STOCK_INFO_MAX_AGE_DAYS = 7
RECHECK_DAYS = 7


def refresh_stock_info_if_stale(conn):
    """個股主檔過期時重新抓取。"""
    row = conn.execute("SELECT MIN(updated_at) FROM stock_info").fetchone()
    if row and row[0]:
        updated = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - updated < timedelta(days=STOCK_INFO_MAX_AGE_DAYS):
            print(f"個股主檔於 {row[0]} 更新，仍在有效期內")
            return
    print("個股主檔已過期，重新抓取")
    update_stock_info(conn=conn)


def find_incomplete_dates(conn):
    """找出近期只收錄到單一市場的日期。"""
    since = (date.today() - timedelta(days=RECHECK_DAYS)).strftime("%Y%m%d")
    rows = conn.execute(
        """
        SELECT date, COUNT(*) AS ok_markets
        FROM ingest_log
        WHERE date >= ? AND status = 'ok'
        GROUP BY date
        HAVING ok_markets < 2
        ORDER BY date
        """,
        (since,),
    ).fetchall()
    return [row["date"] for row in rows]


def main():
    conn = connect()
    try:
        refresh_stock_info_if_stale(conn)

        today = date.today().strftime("%Y%m%d")
        count = ingest_date(today, conn=conn)
        print(f"{today} 匯入 {count} 筆")

        # 主動式 ETF 持股只有當日快照，必須每天抓才能累積出變動
        etf_results = ingest_etf_holdings(conn=conn)
        etf_ok = [r for r in etf_results if r["status"] == "ok"]
        print(f"ETF 持股完成 {len(etf_ok)} / {len(etf_results)} 檔")
        for r in etf_results:
            if r["status"] != "ok":
                print(f"  {r['etf_code']} {r['status']} {r.get('message', '')}")

        pending = [d for d in find_incomplete_dates(conn) if d != today]
        for date_str in pending:
            time.sleep(config.THROTTLE_SECONDS)
            count = ingest_date(date_str, conn=conn)
            print(f"補抓 {date_str}，共 {count} 筆")
        if not pending:
            print("近期無資料不齊全的日期")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
