"""臺股儀表板信用交易風險指標的匯入流程。

證交所的趨勢介面一次可取 60 個交易日，每天抓最新的 60 天就涵蓋重抓需求；
資料庫還沒補到儀表板第一天 (2026/08/03) 時，再往前多抓一段。
櫃買只有最近約 40 天的市值與成交值，信用交易成交值更只查得到最新一天，
因此上櫃的信用交易占比只能從開始抓取的那天起累積。

每天約 6 到 10 個請求，任一來源失敗只記錄，不影響其他來源。
"""
import logging
import time
from datetime import date, datetime, timedelta

from app import config
from app.fetchers import dashboard
from app.services.market_ingest import trading_dates

logger = logging.getLogger(__name__)

MARKET_ALL = "ALL"

COLUMNS = (
    "keep_rate", "below_acc_num", "call_amt", "exe_acc_num", "exe_amt",
    "market_cap", "turnover", "credit_amount", "default_amt", "default_net_amt",
)

UPSERT_SQL = f"""
    INSERT INTO market_credit (date, market, {", ".join(COLUMNS)}, updated_at)
    VALUES (:date, :market, {", ".join(f":{c}" for c in COLUMNS)}, :updated_at)
    ON CONFLICT(date, market) DO UPDATE SET
        {", ".join(f"{c} = COALESCE(excluded.{c}, market_credit.{c})" for c in COLUMNS)},
        updated_at = excluded.updated_at
"""

# 往前回補時最多再抓幾次，避免來源異常時一直重試
MAX_BACKFILL_CALLS = 3
# 上櫃單日摘要實際上只查得到最新一天，多查一天以防排程跑在資料更新前
TPEX_DAY_RECHECK = 2


def _save(conn, market, rows):
    """寫入多筆 {date, 欄位...}，未提供的欄位以 None 寫入，不會覆蓋既有值。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    for row in rows:
        record = {column: None for column in COLUMNS}
        record.update(row)
        record.update(market=market, updated_at=now)
        records.append(record)
    conn.executemany(UPSERT_SQL, records)
    return len(records)


def _previous_day(date_str):
    return (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def _earliest(conn, market, column):
    row = conn.execute(
        f"SELECT MIN(date) FROM market_credit WHERE market = ? AND {column} IS NOT NULL",
        (market,),
    ).fetchone()
    return row[0]


def _ingest_trend(conn, fetch, market, column, floor):
    """抓最新的趨勢，資料庫尚未補到 floor 時再往前補，每次最多 MAX_BACKFILL_CALLS 段。"""
    rows = fetch()
    earliest = _earliest(conn, market, column)
    candidates = [d for d in (earliest, rows[0]["date"] if rows else None) if d]
    oldest = min(candidates) if candidates else None
    for _ in range(MAX_BACKFILL_CALLS):
        if not oldest or oldest <= floor:
            break
        time.sleep(config.THROTTLE_SECONDS)
        older = fetch(_previous_day(oldest))
        if not older:
            break
        rows = older + rows
        oldest = older[0]["date"]
    return rows


def ingest_official(conn):
    """全市場擔保維持率、追繳處分與上市信用交易成交值。"""
    rows = _ingest_trend(conn, dashboard.fetch_official_trend, MARKET_ALL, "keep_rate",
                         dashboard.SITE_MIN_DATE)
    official = [
        {key: row[key] for key in ("date", "keep_rate", "below_acc_num", "call_amt",
                                   "exe_acc_num", "exe_amt")}
        for row in rows
    ]
    credit = [{"date": row["date"], "credit_amount": row["credit_amount"]} for row in rows]
    _save(conn, MARKET_ALL, official)
    _save(conn, config.MARKET_TWSE, credit)
    return len(rows)


def ingest_twse_market_cap(conn):
    """上市總市值，回補到籌碼圖涵蓋的第一天。成交值另由加權指數的資料提供，不在這裡抓。"""
    dates = trading_dates(conn)
    floor = dates[-1] if dates else dashboard.SITE_MIN_DATE
    rows = _ingest_trend(conn, dashboard.fetch_twse_market_cap_trend, config.MARKET_TWSE,
                         "market_cap", floor)
    return _save(conn, config.MARKET_TWSE, rows)


def ingest_tpex(conn, today=None):
    """上櫃總市值與成交值 (最近約 40 天)，以及最近幾個交易日的信用交易成交值。"""
    count = _save(conn, config.MARKET_TPEX, dashboard.fetch_tpex_trend())
    today = today or date.today().strftime("%Y%m%d")
    rows = conn.execute(
        """
        SELECT i.date FROM index_daily i
        LEFT JOIN market_credit c ON c.date = i.date AND c.market = ?
        WHERE i.index_code = ? AND i.date <= ? AND c.credit_amount IS NULL
        ORDER BY i.date DESC LIMIT ?
        """,
        (config.MARKET_TPEX, config.INDEX_TAIEX, today, TPEX_DAY_RECHECK),
    ).fetchall()
    for row in rows:
        time.sleep(config.THROTTLE_SECONDS)
        day = dashboard.fetch_tpex_day(row["date"])
        if day:
            count += _save(conn, config.MARKET_TPEX, [dict(day, date=row["date"])])
    return count


def ingest_defaults(conn, today=None):
    """證交所公布的投資人違約金額。資料庫沒有時從年初抓起，之後只抓最近一個月。"""
    today = today or date.today().strftime("%Y%m%d")
    latest = conn.execute(
        "SELECT MAX(date) FROM market_credit WHERE market = ? AND default_amt IS NOT NULL",
        (config.MARKET_TWSE,),
    ).fetchone()[0]
    start = _previous_day(latest)[:6] + "01" if latest else today[:4] + "0101"
    return _save(conn, config.MARKET_TWSE, dashboard.fetch_default_amounts(start, today))


def ingest_history(conn):
    """年度融資占市值與信用交易占比。"""
    count = 0
    for market, rows in dashboard.fetch_credit_history().items():
        conn.executemany(
            """
            INSERT INTO credit_history (market, year, margin_ratio, credit_ratio)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(market, year) DO UPDATE SET
                margin_ratio = excluded.margin_ratio, credit_ratio = excluded.credit_ratio
            """,
            [(market, *row) for row in rows],
        )
        count += len(rows)
    return count


STEPS = (
    ("官方維持率與追繳", ingest_official),
    ("上市市值", ingest_twse_market_cap),
    ("上櫃市值與信用交易", ingest_tpex),
    ("違約金額", ingest_defaults),
    ("年度槓桿", ingest_history),
)


def ingest_credit(conn):
    """依序執行各來源，回傳 {項目: 筆數}，失敗的項目為 None。"""
    counts = {}
    for index, (label, step) in enumerate(STEPS):
        if index:
            time.sleep(config.THROTTLE_SECONDS)
        try:
            counts[label] = step(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("信用交易指標 %s 抓取失敗", label)
            counts[label] = None
    return counts
