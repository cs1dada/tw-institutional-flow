"""本機代抓的主動式 ETF 持股：匯出成 JSON 與匯入資料庫。

部分投信的網站封鎖海外 IP，GitHub Actions 無法直接抓取 (見 config.MANUAL_ETFS)。
改由本機抓取後，把每一日的持股存成 data/etf_manual/{ETF 代號}/{YYYYMMDD}.json
並納入版控，排程執行時再匯入資料庫。

JSON 的格式與 fetchers.etf.fetch_holdings 的回傳值相同，可直接交給 save_holdings。
"""
import json
import logging

from app import config
from app.services.etf_ingest import save_holdings

logger = logging.getLogger(__name__)


def _snapshot_dates(conn, code):
    return {
        row[0]
        for row in conn.execute("SELECT date FROM etf_snapshot WHERE etf_code = ?", (code,))
    }


def _load_day(conn, code, date):
    """從資料庫讀出單一 ETF 某一日的持股，格式同 fetch_holdings。"""
    snap = conn.execute(
        "SELECT nav, aum, units FROM etf_snapshot WHERE etf_code = ? AND date = ?",
        (code, date),
    ).fetchone()
    holdings = [
        {"stock_code": r[0], "stock_name": r[1], "shares": r[2], "weight": r[3]}
        for r in conn.execute(
            """
            SELECT stock_code, stock_name, shares, weight FROM etf_holding
            WHERE etf_code = ? AND date = ? ORDER BY stock_code
            """,
            (code, date),
        )
    ]
    return {
        "etf_code": code,
        "date": date,
        "nav": snap[0],
        "aum": snap[1],
        "units": snap[2],
        "holdings": holdings,
    }


def export_manual(conn, codes=None):
    """把資料庫中的持股匯出成 JSON，內容沒變的檔案不重寫。回傳新增或更新的檔案數。"""
    written = 0
    for code in codes or config.MANUAL_ETFS:
        out_dir = config.MANUAL_ETF_DIR / code
        out_dir.mkdir(parents=True, exist_ok=True)
        for date in sorted(_snapshot_dates(conn, code)):
            data = _load_day(conn, code, date)
            if not data["holdings"]:
                continue
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
            path = out_dir / f"{date}.json"
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            path.write_text(text, encoding="utf-8", newline="\n")
            written += 1
    return written


def import_manual(conn):
    """把 JSON 中資料庫還沒有的日期匯入，回傳各 ETF 匯入的天數。

    已存在的日期一律略過：過去的持股不會再變，而且本機執行時資料庫本身就是來源。
    """
    result = {}
    if not config.MANUAL_ETF_DIR.exists():
        return result
    for etf_dir in sorted(p for p in config.MANUAL_ETF_DIR.iterdir() if p.is_dir()):
        code = etf_dir.name
        done = _snapshot_dates(conn, code)
        count = 0
        for path in sorted(etf_dir.glob("*.json")):
            if path.stem in done:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            save_holdings(conn, code, data)
            count += 1
        if count:
            logger.info("%s 由本機代抓檔案匯入 %d 天", code, count)
        result[code] = count
    return result
