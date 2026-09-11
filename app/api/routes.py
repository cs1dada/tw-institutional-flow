"""REST API 端點。"""
from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db import connect
from app.services import dataset

router = APIRouter(prefix="/api")

# 法人別對應的金額欄位，以白名單方式限制可用欄位
INVESTOR_COLUMNS = {
    "all": "total_amt",
    "foreign": "foreign_amt",
    "trust": "trust_amt",
    "dealer": "dealer_amt",
}
INVESTOR_LABELS = {
    "all": "三大法人",
    "foreign": "外資",
    "trust": "投信",
    "dealer": "自營商",
}


def _amount_column(investor):
    column = INVESTOR_COLUMNS.get(investor)
    if column is None:
        raise HTTPException(status_code=400, detail=f"不支援的法人別：{investor}")
    return column


def _latest_date(conn):
    row = conn.execute("SELECT MAX(date) FROM industry_daily").fetchone()
    return row[0] if row and row[0] else None


def _resolve_date(conn, date_str):
    """未指定日期時取最新一個交易日。"""
    resolved = date_str or _latest_date(conn)
    if not resolved:
        raise HTTPException(status_code=404, detail="資料庫尚無任何資料，請先執行匯入")
    return resolved


@router.get("/dates")
def list_dates(limit: int = Query(120, ge=1, le=1000)):
    """回傳有資料的交易日清單，由新到舊。

    上市與上櫃的公布時間不同 (上市約 16:00、上櫃約 15:30)，
    因此一併回傳當日已收錄的市場，讓前端能標示資料尚未齊全的日期。
    """
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT d.date,
                   (SELECT GROUP_CONCAT(market) FROM ingest_log AS l
                    WHERE l.date = d.date AND l.status = 'ok') AS markets
            FROM (SELECT DISTINCT date FROM industry_daily) AS d
            ORDER BY d.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        markets = sorted((row["markets"] or "").split(",")) if row["markets"] else []
        items.append(
            {
                "date": row["date"],
                "markets": markets,
                "complete": len(markets) == 2,
            }
        )
    return {"dates": [item["date"] for item in items], "items": items}


@router.get("/industries/flow")
def industry_flow(date: str = None, investor: str = "all", include_etf: bool = False):
    """指定日期各類股的資金流向，依金額由大到小排序。"""
    column = _amount_column(investor)
    conn = connect()
    try:
        target = _resolve_date(conn, date)
        sql = f"""
            SELECT industry, {column} AS amount, total_amt, foreign_amt, trust_amt,
                   dealer_amt, buy_count, sell_count, stock_count
            FROM industry_daily
            WHERE date = ?
        """
        params = [target]
        if not include_etf:
            sql += " AND industry <> ?"
            params.append(config.INDUSTRY_ETF)
        sql += " ORDER BY amount DESC"
        rows = [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
    return {
        "date": target,
        "investor": investor,
        "investor_label": INVESTOR_LABELS[investor],
        "items": rows,
    }


@router.get("/industries/history")
def industry_history(industry: str, days: int = Query(20, ge=1, le=250)):
    """單一類股近 N 個交易日的資金流向，由舊到新。"""
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT date, foreign_amt, trust_amt, dealer_amt, total_amt,
                   buy_count, sell_count, stock_count
            FROM industry_daily
            WHERE industry = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (industry, days),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"查無類股：{industry}")
    return {"industry": industry, "items": [dict(r) for r in reversed(rows)]}


@router.get("/industries/stocks")
def industry_stocks(
    industry: str,
    date: str = None,
    investor: str = "all",
    limit: int = Query(100, ge=1, le=500),
):
    """指定類股當日的個股買賣超明細。"""
    column = _amount_column(investor)
    conn = connect()
    try:
        target = _resolve_date(conn, date)
        rows = conn.execute(
            f"""
            SELECT t.code, s.name, s.market, t.close, t.total_net,
                   t.foreign_amt, t.trust_amt, t.dealer_amt, t.total_amt,
                   t.{column} AS amount
            FROM inst_trade AS t
            JOIN stock_info AS s ON s.code = t.code
            WHERE t.date = ? AND s.industry = ?
            ORDER BY amount DESC
            LIMIT ?
            """,
            (target, industry, limit),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"查無 {industry} 的個股資料")
    return {"date": target, "industry": industry, "items": [dict(r) for r in rows]}


@router.get("/stocks/ranking")
def stock_ranking(
    date: str = None,
    investor: str = "all",
    side: str = "buy",
    limit: int = Query(50, ge=1, le=200),
    include_etf: bool = False,
):
    """個股買超或賣超排行。side 可為 buy 或 sell。"""
    column = _amount_column(investor)
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail=f"不支援的方向：{side}")
    order = "DESC" if side == "buy" else "ASC"
    conn = connect()
    try:
        target = _resolve_date(conn, date)
        sql = f"""
            SELECT t.code, s.name, s.market, s.industry, t.close, t.total_net,
                   t.foreign_amt, t.trust_amt, t.dealer_amt, t.total_amt,
                   t.{column} AS amount
            FROM inst_trade AS t
            JOIN stock_info AS s ON s.code = t.code
            WHERE t.date = ?
        """
        params = [target]
        if not include_etf:
            sql += " AND s.is_etf = 0"
        sql += f" ORDER BY amount {order} LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
    return {"date": target, "investor": investor, "side": side, "items": rows}


@router.get("/industries/streak")
def industry_streak(
    days: int = Query(5, ge=2, le=60),
    investor: str = "all",
    include_etf: bool = False,
):
    """近 N 個交易日中，各類股連續買超或連續賣超的天數排行。"""
    column = _amount_column(investor)
    conn = connect()
    try:
        dates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM industry_daily ORDER BY date DESC LIMIT ?", (days,)
            )
        ]
        if not dates:
            raise HTTPException(status_code=404, detail="資料庫尚無任何資料")
        placeholders = ",".join(["?"] * len(dates))
        sql = f"""
            SELECT industry, date, {column} AS amount
            FROM industry_daily
            WHERE date IN ({placeholders})
        """
        params = list(dates)
        if not include_etf:
            sql += " AND industry <> ?"
            params.append(config.INDUSTRY_ETF)
        sql += " ORDER BY industry, date DESC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # 由最新一日往回數，計算連續同方向的天數
    by_industry = {}
    for row in rows:
        by_industry.setdefault(row["industry"], []).append(row["amount"])

    results = []
    for industry, amounts in by_industry.items():
        if not amounts or amounts[0] == 0:
            continue
        direction = 1 if amounts[0] > 0 else -1
        streak = 0
        total = 0.0
        for amount in amounts:
            if (amount > 0 and direction > 0) or (amount < 0 and direction < 0):
                streak += 1
                total += amount
            else:
                break
        results.append(
            {
                "industry": industry,
                "direction": "buy" if direction > 0 else "sell",
                "streak_days": streak,
                "total_amt": total,
            }
        )
    # 依期間累計金額的絕對值由大到小排序，資金規模最大的排在最前
    results.sort(key=lambda r: abs(r["total_amt"]), reverse=True)
    return {"days": days, "investor": investor, "dates": dates, "items": results}


@router.get("/industries/composition")
def industry_composition(
    date: str = None,
    investor: str = "all",
    top: int = Query(5, ge=1, le=20),
    include_etf: bool = False,
):
    """各類股的資金流向，並附上該類股內金額最大的前幾檔個股。

    子項只取與類股同方向的個股 (類股買超就取買超個股)，其餘合併為一項，
    讓 treemap 能在類股區塊內呈現資金集中在哪幾檔。
    """
    column = _amount_column(investor)
    conn = connect()
    try:
        target = _resolve_date(conn, date)
        sql = f"""
            SELECT industry, {column} AS amount, total_amt, foreign_amt, trust_amt,
                   dealer_amt, buy_count, sell_count, stock_count
            FROM industry_daily
            WHERE date = ?
        """
        params = [target]
        if not include_etf:
            sql += " AND industry <> ?"
            params.append(config.INDUSTRY_ETF)
        industries = [dict(r) for r in conn.execute(sql, params)]

        stock_sql = f"""
            SELECT s.industry, t.code, s.name, s.market, t.close, t.{column} AS amount
            FROM inst_trade AS t
            JOIN stock_info AS s ON s.code = t.code
            WHERE t.date = ?
        """
        stock_params = [target]
        if not include_etf:
            stock_sql += " AND s.is_etf = 0"
        stock_sql += " ORDER BY ABS(amount) DESC"
        stocks = conn.execute(stock_sql, stock_params).fetchall()
    finally:
        conn.close()

    by_industry = {}
    for row in stocks:
        by_industry.setdefault(row["industry"], []).append(dict(row))

    items = []
    for entry in industries:
        amount = entry["amount"] or 0
        if amount == 0:
            continue
        # 只取與類股同方向的個股，反方向的個股在類股淨額中已被抵消
        same_direction = [
            row
            for row in by_industry.get(entry["industry"], [])
            if (row["amount"] > 0) == (amount > 0) and row["amount"] != 0
        ]
        leaders = same_direction[:top]
        rest = same_direction[top:]
        children = [
            {
                "code": row["code"],
                "name": row["name"],
                "market": row["market"],
                "close": row["close"],
                "amount": row["amount"],
                "is_other": False,
            }
            for row in leaders
        ]
        if rest:
            children.append(
                {
                    "code": None,
                    "name": f"其他 {len(rest)} 檔",
                    "market": None,
                    "close": None,
                    "amount": sum(row["amount"] for row in rest),
                    "count": len(rest),
                    "is_other": True,
                }
            )
        entry["children"] = children
        entry["same_direction_count"] = len(same_direction)
        items.append(entry)

    items.sort(key=lambda r: r["amount"], reverse=True)
    return {
        "date": target,
        "investor": investor,
        "investor_label": INVESTOR_LABELS[investor],
        "top": top,
        "items": items,
    }


# 以下端點回傳「未經法人別篩選的完整資料」，與靜態匯出的 JSON 格式相同，
# 前端依 mode 決定要打這些端點或讀 JSON 檔，之後的篩選一律在前端進行。


@router.get("/meta")
def api_meta():
    """交易日清單與基本資訊。"""
    conn = connect()
    try:
        return dataset.build_meta(conn)
    finally:
        conn.close()


@router.get("/day/{date}")
def api_day(date: str):
    """單一交易日的完整資料。"""
    conn = connect()
    try:
        payload = dataset.build_day(conn, date)
    finally:
        conn.close()
    if payload is None:
        raise HTTPException(status_code=404, detail=f"查無 {date} 的資料")
    return payload


@router.get("/history")
def api_history(days: int = Query(dataset.HISTORY_DAYS, ge=1, le=250)):
    """各類股近 N 個交易日的趨勢。"""
    conn = connect()
    try:
        return dataset.build_history(conn, days)
    finally:
        conn.close()


@router.get("/etf-data")
def api_etf_data():
    """主動式 ETF 的持股、合計持股與持股變動。"""
    conn = connect()
    try:
        return dataset.build_etf(conn)
    finally:
        conn.close()
