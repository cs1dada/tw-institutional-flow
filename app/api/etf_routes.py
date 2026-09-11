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


# 各檔 ETF 的最新快照日期。各投信的持股基準日不一定相同
# (海外股票 ETF 通常晚一日)，因此不能用全體的最新日期一概而論。
LATEST_PER_ETF = """
    SELECT etf_code, MAX(date) AS date
    FROM etf_holding
    GROUP BY etf_code
"""


@router.get("/holdings")
def etf_holdings(date: str = None, etf_code: str = None):
    """各 ETF 的持股明細。未指定日期時，每檔取自己的最新快照。"""
    conn = connect()
    try:
        params = []
        if date:
            scope = "SELECT etf_code, ? AS date FROM (SELECT DISTINCT etf_code FROM etf_holding)"
            params.append(date)
        else:
            scope = LATEST_PER_ETF

        sql = f"""
            SELECT h.date, h.etf_code, s.name AS etf_name, h.stock_code, h.stock_name,
                   h.shares, h.weight, p.close
            FROM etf_holding AS h
            JOIN ({scope}) AS latest
                ON latest.etf_code = h.etf_code AND latest.date = h.date
            LEFT JOIN stock_info AS s ON s.code = h.etf_code
            LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
        """
        if etf_code:
            sql += " WHERE h.etf_code = ?"
            params.append(etf_code)
        sql += " ORDER BY h.etf_code, h.weight DESC"
        rows = [dict(r) for r in conn.execute(sql, params)]

        snap_params = [date] if date else []
        snapshots = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT n.date, n.etf_code, s.name AS etf_name, n.issuer, n.nav, n.aum,
                       n.units, n.holding_count
                FROM etf_snapshot AS n
                JOIN ({scope}) AS latest
                    ON latest.etf_code = n.etf_code AND latest.date = n.date
                LEFT JOIN stock_info AS s ON s.code = n.etf_code
                ORDER BY n.aum DESC
                """,
                snap_params,
            )
        ]
    finally:
        conn.close()
    if not snapshots:
        raise HTTPException(status_code=404, detail="尚無持股資料，請先執行 ingest_etf.py")
    dates = sorted({row["date"] for row in snapshots})
    return {"date": dates[-1], "dates": dates, "etfs": snapshots, "items": rows}


@router.get("/top-stocks")
def etf_top_stocks(limit: int = Query(30, ge=1, le=200)):
    """已介接的主動式 ETF 合計持有最多的個股，各檔以自己的最新快照計算。"""
    conn = connect()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT h.stock_code,
                       MAX(h.stock_name) AS stock_name,
                       COUNT(DISTINCT h.etf_code) AS etf_count,
                       SUM(h.shares) AS total_shares,
                       SUM(h.shares * COALESCE(p.close, 0)) AS market_value,
                       MAX(si.industry) AS industry
                FROM etf_holding AS h
                JOIN ({LATEST_PER_ETF}) AS latest
                    ON latest.etf_code = h.etf_code AND latest.date = h.date
                LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
                LEFT JOIN stock_info AS si ON si.code = h.stock_code
                GROUP BY h.stock_code
                ORDER BY market_value DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]
        dates = [
            r[0]
            for r in conn.execute("SELECT DISTINCT MAX(date) FROM etf_holding GROUP BY etf_code")
        ]
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="尚無持股資料")
    return {"date": max(dates), "dates": sorted(set(dates)), "items": rows}


@router.get("/changes")
def etf_changes(limit: int = Query(80, ge=1, le=300)):
    """持股變動：每檔 ETF 與自己的前一個快照相比，加碼與減碼了哪些個股。

    各投信的持股基準日不同，因此不能用全體的最近兩日比對，
    必須每檔 ETF 各自取自己的最新與次新快照。
    """
    conn = connect()
    try:
        pairs = conn.execute(
            """
            WITH ranked AS (
                SELECT etf_code, date,
                       DENSE_RANK() OVER (PARTITION BY etf_code ORDER BY date DESC) AS rk
                FROM (SELECT DISTINCT etf_code, date FROM etf_holding)
            )
            SELECT c.etf_code, c.date AS curr_date, p.date AS prev_date
            FROM ranked AS c
            JOIN ranked AS p ON p.etf_code = c.etf_code AND p.rk = 2
            WHERE c.rk = 1
            """
        ).fetchall()

        if not pairs:
            ready = conn.execute("SELECT COUNT(DISTINCT date) FROM etf_holding").fetchone()[0]
            return {
                "items": [],
                "pairs": [],
                "message": "持股變動需要每檔 ETF 各有兩個快照，目前只有 "
                + str(ready)
                + " 個日期的資料，明日再執行一次即可比對",
            }

        rows = []
        for pair in pairs:
            for row in conn.execute(
                """
                SELECT ? AS etf_code,
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
                FROM (SELECT * FROM etf_holding WHERE etf_code = ? AND date = ?) AS c
                FULL OUTER JOIN
                     (SELECT * FROM etf_holding WHERE etf_code = ? AND date = ?) AS p
                    ON p.stock_code = c.stock_code
                LEFT JOIN daily_price AS q
                    ON q.code = COALESCE(c.stock_code, p.stock_code) AND q.date = ?
                WHERE COALESCE(c.shares, 0) <> COALESCE(p.shares, 0)
                """,
                (
                    pair["etf_code"],
                    pair["etf_code"], pair["curr_date"],
                    pair["etf_code"], pair["prev_date"],
                    pair["curr_date"],
                ),
            ):
                rows.append(dict(row))
    finally:
        conn.close()

    rows.sort(key=lambda r: abs(r["value_change"] or 0), reverse=True)
    return {
        "pairs": [dict(p) for p in pairs],
        "date": max(p["curr_date"] for p in pairs),
        "prev_date": min(p["prev_date"] for p in pairs),
        "items": rows[:limit],
    }
