"""在本機代抓被封鎖海外 IP 的 ETF 持股，存成 JSON 供 GitHub Actions 匯入。

GitHub Actions 抓 config.MANUAL_ETFS 列出的 ETF 一律回 403，因此由本機執行：
1. 抓取這幾檔最新一日的持股寫入本機資料庫
2. 把資料庫中的持股全部匯出到 data/etf_manual/ (內容沒變的檔案不重寫)
3. 加上 --push 時提交並推送，推送會觸發每日排程重新匯出網站

過去的日期先用 backfill_etf.py 回補到本機資料庫，再執行本腳本即可一併匯出。

用法：
    python scripts/sync_manual_etf.py           # 只抓取與匯出，不提交
    python scripts/sync_manual_etf.py --push    # 有新檔案時提交並推送
"""
import subprocess
import sys
from datetime import date

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect, init_schema
from app.services.etf_ingest import ingest_etf_holdings
from app.services.etf_manual import export_manual


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=config.BASE_DIR, check=True, capture_output=True, text=True
    )


def push():
    """提交 data/etf_manual/ 的變動並推送，沒有變動時不提交。"""
    rel = config.MANUAL_ETF_DIR.relative_to(config.BASE_DIR).as_posix()
    git("add", rel)
    staged = subprocess.run(
        ["git", "diff", "--staged", "--quiet", "--", rel], cwd=config.BASE_DIR
    )
    if staged.returncode == 0:
        print("沒有新的持股檔案，略過提交")
        return
    # 只提交這個目錄，避免把工作目錄中其他已暫存的變動一起帶上去
    git("commit", "-m", f"chore: 本機代抓 ETF 持股 {date.today():%Y-%m-%d}", "--", rel)
    git("pull", "--rebase", "--autostash")
    git("push")
    print("已提交並推送")


def main():
    init_schema()
    conn = connect()
    try:
        for r in ingest_etf_holdings(conn=conn, codes=list(config.MANUAL_ETFS)):
            if r["status"] == "ok":
                print(f"{r['etf_code']}  {r['date']}  {r['holding_count']} 檔持股")
            else:
                print(f"{r['etf_code']}  {r['status']}  {r.get('message', '')}")
        written = export_manual(conn)
        print(f"匯出 {written} 個檔案到 {config.MANUAL_ETF_DIR}")
    finally:
        conn.close()

    if "--push" in sys.argv[1:]:
        push()


if __name__ == "__main__":
    main()
