"""大盤指數日線匯入流程。

證交所以月為單位提供指數資料，因此匯入也以月為單位進行。
重複執行會覆寫同月份的資料，當月尚未結束時每天重抓即可補上新的交易日。
"""
import logging
import time
from datetime import date

from app import config
from app.db import connect
from app.fetchers import index_quote

logger = logging.getLogger(__name__)

UPSERT_SQL = """
    INSERT INTO index_daily (
        date, index_code, open, high, low, close, volume, turnover, change
    ) VALUES (
        :date, :index_code, :open, :high, :low, :close, :volume, :turnover, :change
    )
    ON CONFLICT(date, index_code) DO UPDATE SET
        open = excluded.open,
        high = excluded.high,
        low = excluded.low,
        close = excluded.close,
        volume = excluded.volume,
        turnover = excluded.turnover,
        change = excluded.change
"""


def month_range(start, end):
    """產生 (年, 月) 序列，start 與 end 皆為 (年, 月) 且包含兩端。"""
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


def recent_months(months, today=None):
    """由今日往回推 N 個月，回傳由舊到新的 (年, 月) 序列。"""
    today = today or date.today()
    total = today.year * 12 + (today.month - 1) - (months - 1)
    start = (total // 12, total % 12 + 1)
    return list(month_range(start, (today.year, today.month)))


def ingest_index_month(year, month, conn=None, index_code=config.INDEX_TAIEX):
    """匯入單一月份的指數日線，回傳寫入筆數。"""
    own = conn is None
    conn = conn or connect()
    try:
        rows = index_quote.fetch_index_month(year, month)
        if not rows:
            return 0
        conn.executemany(
            UPSERT_SQL,
            [dict(row, index_code=index_code) for row in rows],
        )
        conn.commit()
        logger.info("加權指數 %d-%02d 寫入 %d 個交易日", year, month, len(rows))
        return len(rows)
    finally:
        if own:
            conn.close()


def ingest_index_months(months, conn=None):
    """匯入最近 N 個月的指數日線，回傳寫入總筆數。"""
    own = conn is None
    conn = conn or connect()
    try:
        return ingest_index_range(recent_months(months), conn=conn)
    finally:
        if own:
            conn.close()


def ingest_index_range(periods, conn=None):
    """依序匯入指定的 (年, 月) 清單，每次請求之間留間隔避免被擋。"""
    own = conn is None
    conn = conn or connect()
    try:
        total = 0
        for index, (year, month) in enumerate(periods):
            if index:
                time.sleep(config.THROTTLE_SECONDS)
            total += ingest_index_month(year, month, conn=conn)
        return total
    finally:
        if own:
            conn.close()
