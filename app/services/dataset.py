"""組出前端所需的完整資料。

本機的 API 端點與靜態匯出腳本都呼叫這裡的函式，
確保兩種模式拿到的資料格式完全一致，前端只需要一套處理邏輯。

與原本的 API 不同，這裡不依法人別篩選，而是把四種法人的金額一併回傳，
由前端依使用者選擇挑欄位。
"""
import logging

from app import config
from app.fetchers import etf

logger = logging.getLogger(__name__)

# 類股區塊內切分出的個股檔數，與前端的顯示上限一致
TOP_STOCKS = 10
# 個股買賣超排行的筆數
RANKING_LIMIT = 20
# 連續買賣超的觀察天數
STREAK_DAYS = 10
# 類股趨勢圖的天數
HISTORY_DAYS = 60

AMOUNT_FIELDS = ("total_amt", "foreign_amt", "trust_amt", "dealer_amt")

# 主動式 ETF 的代號規則：00 開頭、A 結尾
ACTIVE_ETF_PATTERN = "00%A"


def latest_date(conn):
    row = conn.execute("SELECT MAX(date) FROM industry_daily").fetchone()
    return row[0] if row and row[0] else None


def list_dates(conn, limit=120):
    """有資料的交易日，附各日已收錄的市場，用於標示資料是否齊全。"""
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
    items = []
    for row in rows:
        markets = sorted((row["markets"] or "").split(",")) if row["markets"] else []
        items.append({"date": row["date"], "markets": markets, "complete": len(markets) == 2})
    return items


def _industries(conn, date_str):
    """各類股的四種法人金額彙總。

    不在此附上個股組成：四種法人別的組成不同，若各存一份會大量重複，
    改為另外提供當日全部個股，由前端依需要分組。
    """
    return [
        {
            "industry": r["industry"],
            "total_amt": round(r["total_amt"] or 0),
            "foreign_amt": round(r["foreign_amt"] or 0),
            "trust_amt": round(r["trust_amt"] or 0),
            "dealer_amt": round(r["dealer_amt"] or 0),
            "buy_count": r["buy_count"],
            "sell_count": r["sell_count"],
            "stock_count": r["stock_count"],
        }
        for r in conn.execute(
            """
            SELECT industry, total_amt, foreign_amt, trust_amt, dealer_amt,
                   buy_count, sell_count, stock_count
            FROM industry_daily
            WHERE date = ?
            """,
            (date_str,),
        )
    ]


# 個股資料改以陣列輸出，欄位名只寫一次。
# 2000 多筆資料若每筆都帶欄位名，檔案會膨脹一倍以上。
STOCK_FIELDS = (
    "code", "name", "market", "industry", "is_etf", "close",
    "total_amt", "foreign_amt", "trust_amt", "dealer_amt",
)


def _stocks(conn, date_str):
    """當日全部個股的四種法人金額，以陣列形式輸出。

    前端用這份資料算出類股組成、個股排行與下鑽明細，
    因此不需要另外重複輸出那些衍生結果。
    """
    rows = conn.execute(
        """
        SELECT t.code, s.name, s.market, s.industry, s.is_etf, t.close,
               t.total_amt, t.foreign_amt, t.trust_amt, t.dealer_amt
        FROM inst_trade AS t
        JOIN stock_info AS s ON s.code = t.code
        WHERE t.date = ?
        """,
        (date_str,),
    ).fetchall()
    return [
        [
            row["code"], row["name"], row["market"], row["industry"], row["is_etf"],
            row["close"],
            # 金額以元為單位，小數沒有意義，取整可再省下可觀的空間
            round(row["total_amt"] or 0),
            round(row["foreign_amt"] or 0),
            round(row["trust_amt"] or 0),
            round(row["dealer_amt"] or 0),
        ]
        for row in rows
    ]


def _streak(conn, date_str, days=STREAK_DAYS):
    """自指定日期往前推，各類股連續同方向的天數，四種法人別各一組。"""
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM industry_daily WHERE date <= ? ORDER BY date DESC LIMIT ?",
            (date_str, days),
        )
    ]
    if not dates:
        return {field: [] for field in AMOUNT_FIELDS}

    placeholders = ",".join(["?"] * len(dates))
    rows = conn.execute(
        f"""
        SELECT industry, date, total_amt, foreign_amt, trust_amt, dealer_amt
        FROM industry_daily
        WHERE date IN ({placeholders}) AND industry <> ?
        ORDER BY industry, date DESC
        """,
        (*dates, config.INDUSTRY_ETF),
    ).fetchall()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["industry"], []).append(row)

    result = {}
    for field in AMOUNT_FIELDS:
        items = []
        for industry, records in grouped.items():
            amounts = [r[field] or 0 for r in records]
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
            items.append(
                {
                    "industry": industry,
                    "direction": "buy" if direction > 0 else "sell",
                    "streak_days": streak,
                    "total_amt": total,
                }
            )
        items.sort(key=lambda r: abs(r["total_amt"]), reverse=True)
        result[field] = items
    return result


def build_day(conn, date_str):
    """單一交易日的完整資料，API 與靜態匯出共用。"""
    industries = _industries(conn, date_str)
    if not industries:
        return None
    return {
        "date": date_str,
        "industries": industries,
        "stock_fields": list(STOCK_FIELDS),
        "stocks": _stocks(conn, date_str),
        # 連續天數需要跨日資料，前端手上只有當日資料，因此在此算好
        "streak": _streak(conn, date_str),
        "streak_days": STREAK_DAYS,
    }


# 各檔 ETF 的最新快照日期。各投信的持股基準日不一定相同，
# 因此不能用全體的最新日期一概而論。
LATEST_PER_ETF = """
    SELECT etf_code, MAX(date) AS date
    FROM etf_holding
    GROUP BY etf_code
"""


def build_etf(conn):
    """主動式 ETF 的持股、合計持股與持股變動。

    持股資料與交易日選單無關，各檔一律取自己的最新快照。
    """
    snapshots = [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT n.date, n.etf_code, s.name AS etf_name, n.issuer, n.nav, n.aum,
                   n.units, n.holding_count
            FROM etf_snapshot AS n
            JOIN ({LATEST_PER_ETF}) AS latest
                ON latest.etf_code = n.etf_code AND latest.date = n.date
            LEFT JOIN stock_info AS s ON s.code = n.etf_code
            ORDER BY n.aum DESC
            """
        )
    ]
    if not snapshots:
        return {"etfs": [], "holdings": [], "top_stocks": [], "changes": [], "dates": []}

    holdings = [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT h.date, h.etf_code, h.stock_code, h.stock_name, h.shares, h.weight, p.close
            FROM etf_holding AS h
            JOIN ({LATEST_PER_ETF}) AS latest
                ON latest.etf_code = h.etf_code AND latest.date = h.date
            LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
            ORDER BY h.etf_code, h.weight DESC
            """
        )
    ]

    top_stocks = [
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
            LIMIT 30
            """
        )
    ]

    return {
        "etfs": snapshots,
        "holdings": holdings,
        "top_stocks": top_stocks,
        "changes": _etf_changes(conn),
        "dates": sorted({row["date"] for row in snapshots}),
    }


def _etf_changes(conn, limit=80):
    """每檔 ETF 與自己的前一個快照比對出的持股變動。"""
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
        return []

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
    rows.sort(key=lambda r: abs(r["value_change"] or 0), reverse=True)
    return rows[:limit]


def build_history(conn, days=HISTORY_DAYS):
    """各類股近 N 個交易日的四種法人金額，供趨勢圖使用。"""
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM industry_daily ORDER BY date DESC LIMIT ?", (days,)
        )
    ]
    if not dates:
        return {"dates": [], "industries": {}}
    placeholders = ",".join(["?"] * len(dates))
    rows = conn.execute(
        f"""
        SELECT industry, date, total_amt, foreign_amt, trust_amt, dealer_amt
        FROM industry_daily
        WHERE date IN ({placeholders})
        ORDER BY date
        """,
        dates,
    ).fetchall()
    industries = {}
    for row in rows:
        industries.setdefault(row["industry"], []).append(
            {
                "date": row["date"],
                "total_amt": row["total_amt"],
                "foreign_amt": row["foreign_amt"],
                "trust_amt": row["trust_amt"],
                "dealer_amt": row["dealer_amt"],
            }
        )
    return {"dates": sorted(dates), "industries": industries}


def build_meta(conn):
    """日期清單與基本資訊。"""
    return {
        "dates": list_dates(conn),
        "supported_etfs": etf.supported_etfs(),
        "latest_date": latest_date(conn),
    }
