"""主動式 ETF 持股的每日匯入。

各投信的 API 只提供最新一日快照，沒有歷史，因此每日抓取並累積；
「今天買了什麼」是由相鄰兩日的持股快照相減得出。
"""
import logging
from datetime import datetime

from app.db import connect
from app.fetchers import etf

logger = logging.getLogger(__name__)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ingest_etf_holdings(conn=None, codes=None):
    """抓取並寫入所有已介接 ETF 的持股，回傳各檔的處理結果。"""
    own = conn is None
    conn = conn or connect()
    targets = codes or etf.supported_etfs()
    results = []
    try:
        for code in targets:
            try:
                data = etf.fetch_holdings(code)
            except Exception as exc:
                logger.error("%s 抓取失敗：%s", code, exc)
                results.append({"etf_code": code, "status": "error", "message": str(exc)[:200]})
                continue

            if not data or not data.get("holdings"):
                results.append({"etf_code": code, "status": "no_data"})
                continue

            date_str = data["date"]
            holdings = data["holdings"]

            # 同一日重跑時先清掉舊資料，避免成分股減少時留下已賣出的部位
            conn.execute(
                "DELETE FROM etf_holding WHERE date = ? AND etf_code = ?", (date_str, code)
            )
            conn.executemany(
                """
                INSERT INTO etf_holding (date, etf_code, stock_code, stock_name, shares, weight)
                VALUES (:date, :etf_code, :stock_code, :stock_name, :shares, :weight)
                """,
                [dict(h, date=date_str, etf_code=code) for h in holdings],
            )
            conn.execute(
                """
                INSERT INTO etf_snapshot (
                    date, etf_code, issuer, nav, aum, units, holding_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, etf_code) DO UPDATE SET
                    issuer = excluded.issuer, nav = excluded.nav, aum = excluded.aum,
                    units = excluded.units, holding_count = excluded.holding_count,
                    updated_at = excluded.updated_at
                """,
                (
                    date_str,
                    code,
                    etf.issuer_of(code),
                    data.get("nav"),
                    data.get("aum"),
                    data.get("units"),
                    len(holdings),
                    _now(),
                ),
            )
            conn.commit()
            results.append(
                {
                    "etf_code": code,
                    "status": "ok",
                    "date": date_str,
                    "holding_count": len(holdings),
                }
            )
            logger.info("%s %s 寫入 %d 檔持股", code, date_str, len(holdings))
        return results
    finally:
        if own:
            conn.close()
