"""抓取主動式 ETF 的每日持股。

各投信只提供最新一日快照，需每日執行以累積歷史。

用法：
    python scripts/ingest_etf.py
    python scripts/ingest_etf.py 00980A 00985A    # 只抓指定幾檔
"""
import sys

import _bootstrap

_bootstrap.setup_logging()

from app.services.etf_ingest import ingest_etf_holdings


def main():
    codes = sys.argv[1:] or None
    results = ingest_etf_holdings(codes=codes)
    ok = [r for r in results if r["status"] == "ok"]
    print(f"完成 {len(ok)} / {len(results)} 檔")
    for r in results:
        if r["status"] == "ok":
            print(f"  {r['etf_code']}  {r['date']}  {r['holding_count']} 檔持股")
        else:
            print(f"  {r['etf_code']}  {r['status']}  {r.get('message', '')}")


if __name__ == "__main__":
    main()
