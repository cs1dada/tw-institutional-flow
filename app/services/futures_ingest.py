"""期貨盤後資料的匯入流程：每日行情 (含未沖銷契約數) 與三大法人未平倉。

兩者都來自期交所的 CSV 下載，免費、不需認證，每天只要幾個請求：
- 每日行情單次最多一個月，因此按月切段
- 法人未平倉單次可查一整年

每次從資料庫最新一天往前重抓 RECHECK_DAYS 天，涵蓋排程跑早時尚未公布、
或期交所事後更正的日子；資料表是空的 (例如線上排程的新資料庫) 就自動回補
BACKFILL_DAYS 天，不必另外手動執行回補腳本。
"""
import logging
import time
from datetime import date, datetime, timedelta

from app import config
from app.fetchers import taifex

logger = logging.getLogger(__name__)

# 每日行情要抓的商品：臺股期貨 (大盤頁的全市場未平倉) 與微型臺指 (期貨 K 線圖)
DAILY_COMMODITIES = ("TX", "TMF")
# 法人未平倉要抓的契約：臺股期貨。期交所這支下載用的代碼是 TXF，與每日行情的 TX 不同
INST_COMMODITIES = ("TXF",)
# 每次往前重抓的日曆天數
RECHECK_DAYS = 7
# 資料表沒有資料時回補的日曆天數，與大盤籌碼的 250 個交易日相當
BACKFILL_DAYS = 365

DAILY_UPSERT_SQL = """
INSERT INTO future_daily (
    date, commodity, contract_month, session,
    open, high, low, close, settlement, volume, open_interest
) VALUES (
    :date, :commodity, :contract_month, :session,
    :open, :high, :low, :close, :settlement, :volume, :open_interest
)
ON CONFLICT(date, commodity, contract_month, session) DO UPDATE SET
    open = excluded.open, high = excluded.high, low = excluded.low,
    close = excluded.close, settlement = excluded.settlement,
    volume = excluded.volume, open_interest = excluded.open_interest
"""

INST_UPSERT_SQL = """
INSERT INTO future_inst (
    date, commodity, identity, net_trade, long_oi, short_oi, net_oi, net_oi_amount
) VALUES (
    :date, :commodity, :identity, :net_trade, :long_oi, :short_oi, :net_oi, :net_oi_amount
)
ON CONFLICT(date, commodity, identity) DO UPDATE SET
    net_trade = excluded.net_trade, long_oi = excluded.long_oi,
    short_oi = excluded.short_oi, net_oi = excluded.net_oi,
    net_oi_amount = excluded.net_oi_amount
"""


def chunks(start, end, max_days):
    """把區間切成不超過 max_days 天的小段。"""
    current = start
    while current <= end:
        stop = min(current + timedelta(days=max_days - 1), end)
        yield current, stop
        current = stop + timedelta(days=1)


def _start_date(conn, table, commodity, today):
    """從最新一天往前 RECHECK_DAYS 天重抓；沒有資料時回補 BACKFILL_DAYS 天。"""
    row = conn.execute(
        f"SELECT MAX(date) FROM {table} WHERE commodity = ?", (commodity,)
    ).fetchone()
    if not row or not row[0]:
        return today - timedelta(days=BACKFILL_DAYS - 1)
    latest = datetime.strptime(row[0], "%Y%m%d").date()
    return max(latest - timedelta(days=RECHECK_DAYS), today - timedelta(days=BACKFILL_DAYS - 1))


def _ingest(conn, table, commodities, fetch, max_days, upsert_sql, today):
    counts = {}
    first = True
    for commodity in commodities:
        start = _start_date(conn, table, commodity, today)
        total = 0
        for seg_start, seg_end in chunks(start, today, max_days):
            if not first:
                time.sleep(config.THROTTLE_SECONDS)
            first = False
            rows = fetch(commodity, seg_start, seg_end)
            if rows:
                conn.executemany(upsert_sql, rows)
                conn.commit()
            total += len({row["date"] for row in rows})
        counts[commodity] = total
    return counts


def ingest_future_daily(conn, commodities=DAILY_COMMODITIES, today=None):
    """期貨每日行情，回傳 {商品: 取得的交易日數}。"""
    return _ingest(
        conn, "future_daily", commodities, taifex.fetch_daily_bars,
        taifex.DAILY_MAX_DAYS, DAILY_UPSERT_SQL, today or date.today(),
    )


def _fetch_inst_until_published(today):
    """包裝法人未平倉的抓取：結束日是今天、但當天尚未公布時改查到前一天。

    期交所這支下載在結束日的資料還沒公布時會整段拒絕 (回傳 HTML 錯誤頁)，
    排程跑早或早上手動補資料時，區間只要含今天就會連前幾天都抓不到。
    結束日是週末或其他已過去的休市日則不受影響，因此只需處理「今天」。
    """
    def fetch(commodity, start, end):
        try:
            return taifex.fetch_inst_futures(commodity, start, end)
        except RuntimeError:
            if end != today:
                raise
            if start >= today:
                logger.info("法人期貨未平倉 %s 尚未公布", today)
                return []
            logger.info("法人期貨未平倉 %s 尚未公布，改查至前一天", today)
            time.sleep(config.THROTTLE_SECONDS)
            return taifex.fetch_inst_futures(commodity, start, today - timedelta(days=1))
    return fetch


def ingest_future_inst(conn, commodities=INST_COMMODITIES, today=None):
    """三大法人期貨未平倉，回傳 {契約: 取得的交易日數}。"""
    today = today or date.today()
    return _ingest(
        conn, "future_inst", commodities, _fetch_inst_until_published(today),
        taifex.INST_MAX_DAYS, INST_UPSERT_SQL, today,
    )
