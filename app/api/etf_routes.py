"""主動式 ETF 相關端點。

分成兩類資料：
1. ETF 自身的三大法人買賣超 — 來自既有的 inst_trade，有完整歷史
2. ETF 的持股與持股變動 — 來自各投信官網的每日快照，只能從開始抓取之日累積
"""
from fastapi import APIRouter, HTTPException, Query

from app.api.routes import INVESTOR_LABELS, _amount_column, _resolve_date
from app.db import connect
from app.fetchers import etf

router = APIRouter(prefix="/api/etf")

# 主動式 ETF 的代號規則：00 開頭、A 結尾
ACTIVE_ETF_PATTERN = "00%A"


@router.get("/flow")
def etf_flow(date: str = None, investor: str = "all", limit: int = Query(40, ge=1, le=100)):
    """主動式 ETF 自身的三大法人買賣超排行。"""
    column = _amount_column(investor)
    conn = connect()
    try:
        target = _resolve_date(conn, date)
        rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT t.code, s.name, s.market, t.close, t.total_net,
                       t.foreign_amt, t.trust_amt, t.dealer_amt, t.total_amt,
                       t.{column} AS amount
                FROM inst_trade AS t
                JOIN stock_info AS s ON s.code = t.code
                WHERE t.date = ? AND s.code LIKE ?
                ORDER BY amount DESC
                LIMIT ?
                """,
                (target, ACTIVE_ETF_PATTERN, limit),
            )
        ]
    finally:
        conn.close()
    return {
        "date": target,
        "investor": investor,
        "investor_label": INVESTOR_LABELS[investor],
        "items": rows,
    }


@router.get("/dates")
def etf_holding_dates(limit: int = Query(60, ge=1, le=500)):
    """有持股快照的日期，由新到舊。"""
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT date, COUNT(DISTINCT etf_code) AS etf_count, SUM(holding_count) AS holdings
            FROM etf_snapshot
            GROUP BY date
            ORDER BY date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "items": [dict(r) for r in rows],
        "supported": etf.supported_etfs(),
    }


@router.get("/holdings")
def etf_holdings(date: str = None, etf_code: str = None):
    """指定日期各 ETF 的持股明細。未指定日期時取最新一日。"""
    conn = connect()
    try:
        if date is None:
            row = conn.execute("SELECT MAX(date) FROM etf_holding").fetchone()
            date = row[0] if row else None
        if not date:
            raise HTTPException(status_code=404, detail="尚無持股資料，請先執行 ingest_etf.py")

        sql = """
            SELECT h.etf_code, s.name AS etf_name, h.stock_code, h.stock_name,
                   h.shares, h.weight, p.close
            FROM etf_holding AS h
            LEFT JOIN stock_info AS s ON s.code = h.etf_code
            LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
            WHERE h.date = ?
        """
        params = [date]
        if etf_code:
            sql += " AND h.etf_code = ?"
            params.append(etf_code)
        sql += " ORDER BY h.etf_code, h.weight DESC"
        rows = [dict(r) for r in conn.execute(sql, params)]

        snapshots = [
            dict(r)
            for r in conn.execute(
                """
                SELECT n.etf_code, s.name AS etf_name, n.issuer, n.nav, n.aum,
                       n.units, n.holding_count
                FROM etf_snapshot AS n
                LEFT JOIN stock_info AS s ON s.code = n.etf_code
                WHERE n.date = ?
                ORDER BY n.aum DESC
                """,
                (date,),
            )
        ]
    finally:
        conn.close()
    return {"date": date, "etfs": snapshots, "items": rows}


@router.get("/top-stocks")
def etf_top_stocks(date: str = None, limit: int = Query(30, ge=1, le=200)):
    """已介接的主動式 ETF 合計持有最多的個股。"""
    conn = connect()
    try:
        if date is None:
            row = conn.execute("SELECT MAX(date) FROM etf_holding").fetchone()
            date = row[0] if row else None
        if not date:
            raise HTTPException(status_code=404, detail="尚無持股資料")
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT h.stock_code,
                       MAX(h.stock_name) AS stock_name,
                       COUNT(DISTINCT h.etf_code) AS etf_count,
                       SUM(h.shares) AS total_shares,
                       SUM(h.shares * COALESCE(p.close, 0)) AS market_value,
                       MAX(si.industry) AS industry
                FROM etf_holding AS h
                LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
                LEFT JOIN stock_info AS si ON si.code = h.stock_code
                WHERE h.date = ?
                GROUP BY h.stock_code
                ORDER BY market_value DESC
                LIMIT ?
                """,
                (date, limit),
            )
        ]
    finally:
        conn.close()
    return {"date": date, "items": rows}


@router.get("/changes")
def etf_changes(date: str = None, limit: int = Query(60, ge=1, le=300)):
    """持股變動：與前一個有資料的日期相比，各 ETF 加碼與減碼了哪些個股。

    需要至少兩個交易日的快照才會有結果。
    """
    conn = connect()
    try:
        dates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM etf_holding ORDER BY date DESC LIMIT 2"
                if date is None
                else "SELECT DISTINCT date FROM etf_holding WHERE date <= ? ORDER BY date DESC LIMIT 2",
                () if date is None else (date,),
            )
        ]
        if len(dates) < 2:
            return {
                "date": dates[0] if dates else None,
                "prev_date": None,
                "items": [],
                "message": "持股變動需要兩個交易日的快照，目前只有 "
                + str(len(dates))
                + " 日資料，明日起可比對",
            }

        current, previous = dates[0], dates[1]
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT COALESCE(c.etf_code, p.etf_code) AS etf_code,
                       COALESCE(c.stock_code, p.stock_code) AS stock_code,
                       COALESCE(c.stock_name, p.stock_name) AS stock_name,
                       COALESCE(c.shares, 0) AS shares,
                       COALESCE(p.shares, 0) AS prev_shares,
                       COALESCE(c.shares, 0) - COALESCE(p.shares, 0) AS share_change,
                       (COALESCE(c.shares, 0) - COALESCE(p.shares, 0)) * COALESCE(q.close, 0)
                           AS value_change,
                       CASE
                           WHEN p.stock_code IS NULL THEN 'new'
                           WHEN c.stock_code IS NULL THEN 'removed'
                           ELSE 'changed'
                       END AS change_type
                FROM (SELECT * FROM etf_holding WHERE date = ?) AS c
                FULL OUTER JOIN (SELECT * FROM etf_holding WHERE date = ?) AS p
                    ON p.etf_code = c.etf_code AND p.stock_code = c.stock_code
                LEFT JOIN daily_price AS q
                    ON q.code = COALESCE(c.stock_code, p.stock_code) AND q.date = ?
                WHERE COALESCE(c.shares, 0) <> COALESCE(p.shares, 0)
                ORDER BY ABS(value_change) DESC
                LIMIT ?
                """,
                (current, previous, current, limit),
            )
        ]
    finally:
        conn.close()
    return {"date": current, "prev_date": previous, "items": rows}
