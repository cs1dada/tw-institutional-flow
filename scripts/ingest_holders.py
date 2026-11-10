"""匯入集保股權分散表 (每週一份)。

開放資料只有最新一週，每日排程會自動下載 (見 daily_job.py)，這支腳本供手動執行。
過去的週次只能從集保網站逐檔查詢 (有瀏覽器檢查，程式無法直接送出)，
以瀏覽器查好後存成 data/holders_manual/{YYYYMMDD}.json 並提交，排程就會匯入；
也可以用 --json 直接匯入任意路徑的檔案。

用法：
    python scripts/ingest_holders.py                          # 最新一週，加上 data/holders_manual/ 的補查資料
    python scripts/ingest_holders.py --json 20261030 檔案.json  # 匯入指定的補查檔案

JSON 格式為 {代號: [[級距, 人數, 股數, 比例], ...]}，合計固定放在第 17 級。
"""
import json
import sys

import _bootstrap

_bootstrap.setup_logging()

from app.db import connect, init_schema
from app.services import holders


def import_json(conn, date, path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = [(code, int(lv), int(people), int(shares), float(pct))
            for code, levels in data.items() for lv, people, shares, pct in levels]
    count = holders.save_week(conn, date, rows)
    print(f"{date} 匯入 {count} 檔 (來源 {path})")


def main():
    conn = connect()
    init_schema(conn)
    try:
        if len(sys.argv) >= 4 and sys.argv[1] == "--json":
            import_json(conn, sys.argv[2], sys.argv[3])
            return
        for date, count in holders.ingest_latest(conn).items():
            print(f"{date} 開放資料{f'匯入 {count} 檔' if count else '已匯入過，略過'}")
        for date, count in holders.import_manual(conn).items():
            print(f"{date} 匯入補查資料 {count} 檔")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
