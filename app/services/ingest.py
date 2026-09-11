"""每日資料匯入流程。"""
import logging
from datetime import datetime

from app import config
from app.db import connect
from app.fetchers import isin, tpex, twse
from app.services.aggregate import rebuild_industry_daily

logger = logging.getLogger(__name__)

FETCHERS = {
    config.MARKET_TWSE: twse,
    config.MARKET_TPEX: tpex,
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def update_stock_info(conn=None):
    """更新個股主檔與產業別對照。每週執行一次即可。"""
    own = conn is None
    conn = conn or connect()
    try:
        total = 0
        for market in (config.MARKET_TWSE, config.MARKET_TPEX):
            rows = isin.fetch_stock_info(market)
            conn.executemany(
                """
                INSERT INTO stock_info (code, name, market, industry, is_etf, updated_at)
                VALUES (:code, :name, :market, :industry, :is_etf, :updated_at)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    market = excluded.market,
                    industry = excluded.industry,
                    is_etf = excluded.is_etf,
                    updated_at = excluded.updated_at
                """,
                [dict(r, updated_at=_now()) for r in rows],
            )
            total += len(rows)
        conn.commit()
        logger.info("個股主檔更新完成，共 %d 檔", total)
        return total
    finally:
        if own:
            conn.close()


def _log_ingest(conn, date_str, market, status, row_count, message=None):
    conn.execute(
        """
        INSERT INTO ingest_log (date, market, status, row_count, message, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, market) DO UPDATE SET
            status = excluded.status,
            row_count = excluded.row_count,
            message = excluded.message,
            updated_at = excluded.updated_at
        """,
        (date_str, market, status, row_count, message, _now()),
    )


def ingest_market(conn, date_str, market):
    """匯入單一市場單日資料，回傳實際寫入筆數。"""
    fetcher = FETCHERS[market]
    try:
        inst_rows = fetcher.fetch_inst_trade(date_str)
        if not inst_rows:
            _log_ingest(conn, date_str, market, "no_data", 0, "非交易日或尚未公布")
            conn.commit()
            return 0
        quotes = fetcher.fetch_quotes(date_str)
    except Exception as exc:
        logger.error("%s %s 抓取失敗：%s", market, date_str, exc)
        _log_ingest(conn, date_str, market, "error", 0, str(exc)[:500])
        conn.commit()
        raise

    # 只保留主檔中存在的證券，藉此濾除權證等非類股標的
    known = {row[0] for row in conn.execute("SELECT code FROM stock_info")}
    if not known:
        raise RuntimeError("個股主檔為空，請先執行 update_stock_info")

    price_records = []
    trade_records = []
    missing_close = 0
    for row in inst_rows:
        code = row["code"]
        if code not in known:
            continue
        quote = quotes.get(code, {})
        close = quote.get("close")
        if close is None:
            # 當日無成交 (例如全日無交易) 時無法估算金額，金額以 0 計
            missing_close += 1
        price_records.append(
            {
                "date": date_str,
                "code": code,
                "close": close,
                "volume": quote.get("volume", 0),
                "turnover": quote.get("turnover", 0),
            }
        )
        price = close or 0.0
        trade_records.append(
            {
                "date": date_str,
                "code": code,
                "market": market,
                "foreign_net": row["foreign_net"],
                "trust_net": row["trust_net"],
                "dealer_self_net": row["dealer_self_net"],
                "dealer_hedge_net": row["dealer_hedge_net"],
                "dealer_net": row["dealer_net"],
                "total_net": row["total_net"],
                "close": close,
                "foreign_amt": row["foreign_net"] * price,
                "trust_amt": row["trust_net"] * price,
                "dealer_amt": row["dealer_net"] * price,
                "total_amt": row["total_net"] * price,
            }
        )

    conn.executemany(
        """
        INSERT INTO daily_price (date, code, close, volume, turnover)
        VALUES (:date, :code, :close, :volume, :turnover)
        ON CONFLICT(date, code) DO UPDATE SET
            close = excluded.close, volume = excluded.volume, turnover = excluded.turnover
        """,
        price_records,
    )
    conn.executemany(
        """
        INSERT INTO inst_trade (
            date, code, market, foreign_net, trust_net, dealer_self_net, dealer_hedge_net,
            dealer_net, total_net, close, foreign_amt, trust_amt, dealer_amt, total_amt
        ) VALUES (
            :date, :code, :market, :foreign_net, :trust_net, :dealer_self_net, :dealer_hedge_net,
            :dealer_net, :total_net, :close, :foreign_amt, :trust_amt, :dealer_amt, :total_amt
        )
        ON CONFLICT(date, code) DO UPDATE SET
            market = excluded.market,
            foreign_net = excluded.foreign_net, trust_net = excluded.trust_net,
            dealer_self_net = excluded.dealer_self_net, dealer_hedge_net = excluded.dealer_hedge_net,
            dealer_net = excluded.dealer_net, total_net = excluded.total_net,
            close = excluded.close, foreign_amt = excluded.foreign_amt,
            trust_amt = excluded.trust_amt, dealer_amt = excluded.dealer_amt,
            total_amt = excluded.total_amt
        """,
        trade_records,
    )
    message = f"缺少收盤價 {missing_close} 檔" if missing_close else None
    _log_ingest(conn, date_str, market, "ok", len(trade_records), message)
    conn.commit()
    logger.info(
        "%s %s 寫入 %d 筆 (原始 %d 筆，濾除非類股標的 %d 筆)",
        market, date_str, len(trade_records), len(inst_rows), len(inst_rows) - len(trade_records),
    )
    return len(trade_records)


def ingest_date(date_str, conn=None):
    """匯入指定日期的上市與上櫃資料並重算類股聚合。"""
    own = conn is None
    conn = conn or connect()
    try:
        total = 0
        for market in (config.MARKET_TWSE, config.MARKET_TPEX):
            total += ingest_market(conn, date_str, market)
        if total:
            rebuild_industry_daily(conn, date_str)
        else:
            logger.info("%s 兩市場皆無資料，略過聚合", date_str)
        return total
    finally:
        if own:
            conn.close()
