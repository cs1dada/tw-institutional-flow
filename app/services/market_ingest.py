"""大盤籌碼與總體指標的匯入流程。

籌碼 (三大法人金額、融資融券) 每個交易日要 4 個請求，回補 250 天要將近一小時，
因此每次排程只補一部分 (MARKET_BACKFILL_PER_RUN)，幾天後自然補齊。
交易日曆以 index_daily 的加權指數日期為準，不必自己判斷休市日。

融資資料要到晚間才公布，傍晚的排程常只拿到法人。兩者分開以 COALESCE 寫入，
已取得的欄位不會被之後的空值蓋掉；不齊全的日期在之後幾天的排程裡會再重抓。

融資維持率官方沒有公布，這裡以常見的估算方式計算：
    各檔融資餘額 (張) x 1000 x 當日收盤價 的總和 / 融資餘額 (元)
收盤價取自 daily_price；當日沒有成交的個股改用最近一次的收盤價。
"""
import logging
import time
from datetime import date, datetime, timedelta

from app import config
from app.db import connect
from app.fetchers import market_chip
from app.services.index_ingest import UPSERT_SQL as INDEX_UPSERT_SQL, recent_months

logger = logging.getLogger(__name__)

CHIP_UPSERT_SQL = """
    INSERT INTO market_chip (
        date, market, foreign_net, trust_net, dealer_net, total_net,
        margin_amount, margin_units, short_units, margin_value, maintenance, updated_at
    ) VALUES (
        :date, :market, :foreign_net, :trust_net, :dealer_net, :total_net,
        :margin_amount, :margin_units, :short_units, :margin_value, :maintenance, :updated_at
    )
    ON CONFLICT(date, market) DO UPDATE SET
        foreign_net = COALESCE(excluded.foreign_net, market_chip.foreign_net),
        trust_net = COALESCE(excluded.trust_net, market_chip.trust_net),
        dealer_net = COALESCE(excluded.dealer_net, market_chip.dealer_net),
        total_net = COALESCE(excluded.total_net, market_chip.total_net),
        margin_amount = COALESCE(excluded.margin_amount, market_chip.margin_amount),
        margin_units = COALESCE(excluded.margin_units, market_chip.margin_units),
        short_units = COALESCE(excluded.short_units, market_chip.short_units),
        margin_value = COALESCE(excluded.margin_value, market_chip.margin_value),
        maintenance = COALESCE(excluded.maintenance, market_chip.maintenance),
        updated_at = excluded.updated_at
"""

MACRO_UPSERT_SQL = """
    INSERT INTO macro_daily (series, date, value) VALUES (?, ?, ?)
    ON CONFLICT(series, date) DO UPDATE SET value = excluded.value
"""

CHIP_COLUMNS = (
    "foreign_net", "trust_net", "dealer_net", "total_net",
    "margin_amount", "margin_units", "short_units", "margin_value", "maintenance",
)

# 交易日過了幾天之後仍抓不齊就放棄，避免永遠缺漏的日期每天消耗回補額度
GIVE_UP_AFTER_DAYS = 3

# 櫃買指數尚無資料時回補的月數
TPEX_INDEX_BACKFILL_MONTHS = 24
# 每天重抓的月數，涵蓋跨月時尚未收齊的上個月
TPEX_INDEX_MONTHS = 2
# 台指 VIX 期交所只保留約三個月
TW_VIX_MONTHS = 4

FETCHERS = {
    config.MARKET_TWSE: (market_chip.fetch_twse_inst_summary, market_chip.fetch_twse_margin),
    config.MARKET_TPEX: (market_chip.fetch_tpex_inst_summary, market_chip.fetch_tpex_margin),
}


# ---------------------------------------------------------------------------
# 融資維持率
# ---------------------------------------------------------------------------

def load_closes(conn, date_str, codes):
    """各檔在 date_str 當天 (或之前最近一次) 的收盤價。"""
    rows = conn.execute(
        "SELECT code, close FROM daily_price WHERE date = ? AND close IS NOT NULL",
        (date_str,),
    ).fetchall()
    closes = {row["code"]: row["close"] for row in rows}
    missing = [code for code in codes if code not in closes]
    for code in missing:
        row = conn.execute(
            """
            SELECT close FROM daily_price
            WHERE code = ? AND date < ? AND close IS NOT NULL
            ORDER BY date DESC LIMIT 1
            """,
            (code, date_str),
        ).fetchone()
        if row:
            closes[code] = row["close"]
    return closes


def margin_value(conn, date_str, stocks):
    """融資股票的市值 (元)；當天沒有任何收盤價資料時回傳 None。

    daily_price 涵蓋的期間有限，太早的日期查不到收盤價，維持率就留空。
    """
    if not stocks:
        return None
    has_prices = conn.execute(
        "SELECT 1 FROM daily_price WHERE date = ? LIMIT 1", (date_str,)
    ).fetchone()
    if not has_prices:
        return None
    closes = load_closes(conn, date_str, stocks)
    unpriced = [code for code in stocks if code not in closes]
    if unpriced:
        logger.info("%s 有 %d 檔融資個股查無收盤價，不計入維持率", date_str, len(unpriced))
    return sum(units * market_chip.SHARES_PER_LOT * closes[code]
               for code, units in stocks.items() if code in closes)


# ---------------------------------------------------------------------------
# 籌碼
# ---------------------------------------------------------------------------

def _empty_row(date_str, market):
    row = {"date": date_str, "market": market}
    row.update({column: None for column in CHIP_COLUMNS})
    row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return row


def ingest_chip_date(date_str, conn=None):
    """匯入單一交易日兩個市場的法人金額與融資融券，回傳 {市場: 取得的項目}。

    查無資料時仍寫入一列空值，記下抓取時間，作為之後是否放棄重抓的依據。
    """
    own = conn is None
    conn = conn or connect()
    try:
        result = {}
        for index, (market, (fetch_inst, fetch_margin)) in enumerate(FETCHERS.items()):
            row = _empty_row(date_str, market)
            got = []
            if index:
                time.sleep(config.THROTTLE_SECONDS)
            inst = fetch_inst(date_str)
            if inst:
                row.update(inst)
                got.append("法人")

            time.sleep(config.THROTTLE_SECONDS)
            margin = fetch_margin(date_str)
            if margin:
                stocks = margin.pop("stocks", {})
                row.update(margin)
                value = margin_value(conn, date_str, stocks)
                if value and margin["margin_amount"]:
                    row["margin_value"] = value
                    row["maintenance"] = round(value / margin["margin_amount"] * 100, 2)
                got.append("融資")

            conn.execute(CHIP_UPSERT_SQL, row)
            result[market] = got
        conn.commit()
        logger.info(
            "大盤籌碼 %s：%s", date_str,
            "；".join(f"{m} {'、'.join(g) or '無資料'}" for m, g in result.items()),
        )
        return result
    finally:
        if own:
            conn.close()


def trading_dates(conn, days=config.MARKET_CHIP_DAYS):
    """最近 N 個交易日，由新到舊。以加權指數有資料的日期為交易日曆。"""
    rows = conn.execute(
        "SELECT date FROM index_daily WHERE index_code = ? ORDER BY date DESC LIMIT ?",
        (config.INDEX_TAIEX, days),
    ).fetchall()
    return [row["date"] for row in rows]


def pending_chip_dates(conn, days=config.MARKET_CHIP_DAYS, limit=config.MARKET_BACKFILL_PER_RUN,
                       today=None):
    """需要抓取的交易日，由新到舊。

    - 最近 MARKET_RECHECK_DAYS 個交易日：任一市場缺法人或融資就重抓
    - 更早的日期：完全沒抓過，或缺資料且最後一次抓取距交易日不到 GIVE_UP_AFTER_DAYS 天
    最近幾天一律納入，更早的缺漏最多 limit 天。
    """
    today = today or date.today()
    dates = trading_dates(conn, days)
    if not dates:
        return []
    rows = conn.execute(
        f"""
        SELECT date, market, foreign_net, margin_amount, updated_at
        FROM market_chip
        WHERE date >= ?
        """,
        (dates[-1],),
    ).fetchall()
    status = {}
    for row in rows:
        status[(row["date"], row["market"])] = row

    recent, older = [], []
    for position, date_str in enumerate(dates):
        is_recent = position < config.MARKET_RECHECK_DAYS
        need = False
        for market in FETCHERS:
            row = status.get((date_str, market))
            if row is None:
                need = True
                break
            if row["foreign_net"] is not None and row["margin_amount"] is not None:
                continue
            fetched = datetime.strptime(row["updated_at"][:10], "%Y-%m-%d").date()
            traded = datetime.strptime(date_str, "%Y%m%d").date()
            if is_recent or (fetched - traded).days < GIVE_UP_AFTER_DAYS:
                need = True
                break
        if need:
            (recent if is_recent else older).append(date_str)
    return recent + older[:limit]


def ingest_pending_chip(conn=None, limit=config.MARKET_BACKFILL_PER_RUN, extra_dates=()):
    """抓取缺漏的籌碼日期，回傳抓取的日期清單。extra_dates 為額外要抓的日期 (例如今天)。"""
    own = conn is None
    conn = conn or connect()
    try:
        dates = list(dict.fromkeys(list(extra_dates) + pending_chip_dates(conn, limit=limit)))
        for index, date_str in enumerate(dates):
            if index:
                time.sleep(config.THROTTLE_SECONDS)
            ingest_chip_date(date_str, conn=conn)
        return dates
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# 櫃買指數與總體指標
# ---------------------------------------------------------------------------

def ingest_tpex_index(conn, months=None):
    """匯入櫃買指數。尚無資料時回補 24 個月，之後每天只重抓最近兩個月。"""
    if months is None:
        row = conn.execute(
            "SELECT COUNT(*) FROM index_daily WHERE index_code = ?", (config.INDEX_TPEX,)
        ).fetchone()
        months = TPEX_INDEX_MONTHS if row[0] else TPEX_INDEX_BACKFILL_MONTHS
    total = 0
    for index, (year, month) in enumerate(recent_months(months)):
        if index:
            time.sleep(config.THROTTLE_SECONDS)
        rows = market_chip.fetch_tpex_index_month(year, month)
        if rows:
            conn.executemany(
                INDEX_UPSERT_SQL, [dict(row, index_code=config.INDEX_TPEX) for row in rows]
            )
            total += len(rows)
    conn.commit()
    return total


def _save_series(conn, series, rows):
    conn.executemany(MACRO_UPSERT_SQL, [(series, d, v) for d, v in rows])
    conn.commit()
    return len(rows)


def ingest_macro(conn):
    """美元兌台幣、美國 VIX (Yahoo) 與台指 VIX (期交所)，回傳 {序列: 筆數}。

    Yahoo 是非官方介面，任一序列失敗只記錄、不影響其他序列。
    """
    counts = {}
    for series, symbol in config.MACRO_YAHOO_SYMBOLS.items():
        try:
            counts[series] = _save_series(conn, series, market_chip.fetch_yahoo_daily(symbol))
        except Exception:
            logger.exception("%s (%s) 抓取失敗", series, symbol)
            counts[series] = 0

    vix_rows = []
    try:
        for index, (year, month) in enumerate(recent_months(TW_VIX_MONTHS)):
            if index:
                time.sleep(config.THROTTLE_SECONDS)
            vix_rows.extend(market_chip.fetch_tw_vix_month(year, month))
    except Exception:
        logger.exception("台指 VIX 抓取失敗")
    counts[config.MACRO_TWVIX] = _save_series(conn, config.MACRO_TWVIX, vix_rows)
    return counts
