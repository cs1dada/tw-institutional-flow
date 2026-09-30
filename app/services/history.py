"""個股歷史日線 (K 線圖用)。

資料來自盤後匯入的 daily_price，是本機資料庫，因此不消耗任何行情 API
的額度，讀取也是毫秒級。開高低是後來才加進 daily_price 的欄位，
舊資料要先跑 scripts/backfill_ohlc.py 補齊。

回傳格式刻意與大盤指數的日線一致 (date/open/high/low/close/turnover)，
前端可直接沿用既有的週線月線聚合與均線計算。
"""
import logging
from datetime import date, timedelta

from app import config

logger = logging.getLogger(__name__)

FIELDS = ["date", "open", "high", "low", "close", "turnover"]

# 期貨代碼與期交所商品代碼的對照。
# R1 是 Shioaji「近月連續」合約的寫法，這裡一律以近月呈現，
# 因此兩種寫法指向同一組資料。
# 指數代碼與 index_daily 的對照。
# IX0001 是富果與 Shioaji 對加權指數的代碼，資料庫裡存的是 TAIEX。
INDEX_CODES = {
    "IX0001": config.INDEX_TAIEX,
    "TAIEX": config.INDEX_TAIEX,
}

FUTURE_COMMODITIES = {
    "TMFR1": "TMF",
    "TMF": "TMF",
    "TXFR1": "TX",
    "TX": "TX",
    "MXFR1": "MTX",
    "MTX": "MTX",
}


def build_history(conn, code, months=None):
    """指定個股最近 N 個月的日線。

    只回傳開高低齊全的交易日：缺任一個就畫不出 K 棒，與其畫出殘缺的
    K 棒，不如讓呼叫端知道這段期間沒有資料、改走別的來源。
    """
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("請輸入股票代號")

    months = int(months or config.HISTORY_DEFAULT_MONTHS)
    months = max(1, min(months, config.HISTORY_MAX_MONTHS))
    # 以 31 天估一個月即可，查詢本來就會截到實際有資料的範圍
    since = (date.today() - timedelta(days=months * 31)).strftime("%Y%m%d")

    commodity = FUTURE_COMMODITIES.get(code)
    if commodity:
        return _future_history(conn, code, commodity, months, since)

    index_code = INDEX_CODES.get(code)
    if index_code:
        return _index_history(conn, code, index_code, months, since)

    rows = conn.execute(
        """
        SELECT date, open, high, low, close, turnover
        FROM daily_price
        WHERE code = ? AND date >= ?
          AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL
          AND close IS NOT NULL
        ORDER BY date
        """,
        (code, since),
    ).fetchall()

    info = conn.execute(
        "SELECT name, market FROM stock_info WHERE code = ?", (code,)
    ).fetchone()

    items = [
        [
            row["date"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            # 資料庫存的是元，畫面與指數頁一致以億元為單位
            round((row["turnover"] or 0) / 1e8, 4),
        ]
        for row in rows
    ]

    return {
        "code": code,
        "name": info["name"] if info else None,
        "market": info["market"] if info else None,
        "months": months,
        "fields": FIELDS,
        "items": items,
        # 呼叫端據此判斷資料庫的涵蓋範圍夠不夠，不夠就改走行情 API
        "earliest": items[0][0] if items else None,
        "latest": items[-1][0] if items else None,
        "source": "db",
        # 個股的成交統計是金額，期貨則是口數，圖表的副圖標示要跟著換
        "turnover_label": "成交金額（億）",
        "turnover_unit": "億",
    }


def _index_history(conn, code, index_code, months, since):
    """大盤指數的日線，來自 index_daily。

    這張表本來就是給大盤指數 K 線圖用的，資料可回溯到 2016 年，
    比個股的 daily_price 還久，因此指數的 K 線完全不需要動用行情 API。
    """
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, turnover
        FROM index_daily
        WHERE index_code = ? AND date >= ?
          AND open IS NOT NULL AND high IS NOT NULL
          AND low IS NOT NULL AND close IS NOT NULL
        ORDER BY date
        """,
        (index_code, since),
    ).fetchall()

    items = [
        [
            row["date"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            # 這裡的成交金額是全市場合計，資料庫存元，畫面以億元為單位
            round((row["turnover"] or 0) / 1e8, 4),
        ]
        for row in rows
    ]

    return {
        "code": code,
        "name": config.INDEX_NAMES.get(index_code, index_code),
        "market": "INDEX",
        "months": months,
        "fields": FIELDS,
        "items": items,
        "earliest": items[0][0] if items else None,
        "latest": items[-1][0] if items else None,
        "source": "db",
        "turnover_label": "成交金額（億）",
        "turnover_unit": "億",
    }


FUTURE_NAMES = {
    "TMF": "微型臺指期貨",
    "TX": "臺股期貨",
    "MTX": "小型臺指期貨",
}


def _future_history(conn, code, commodity, months, since):
    """期貨的近月日線。

    同一個交易日會有多個到期月份，取月份最小的那個即為近月：已結算的
    契約不會再出現在當日資料裡，所以不必另外推算結算日。
    只取一般交易時段，盤後盤 (夜盤) 另成一段行情，混在一起會讓 K 棒失真。
    """
    rows = conn.execute(
        """
        SELECT date, contract_month, open, high, low, close, volume
        FROM future_daily f
        WHERE commodity = ? AND session = 'regular' AND date >= ?
          AND open IS NOT NULL AND high IS NOT NULL
          AND low IS NOT NULL AND close IS NOT NULL
          AND contract_month = (
              SELECT MIN(contract_month) FROM future_daily
              WHERE date = f.date AND commodity = f.commodity AND session = 'regular'
          )
        ORDER BY date
        """,
        (commodity, since),
    ).fetchall()

    items = [
        [
            row["date"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            # 期交所的每日行情沒有成交金額，只有成交口數
            row["volume"] or 0,
        ]
        for row in rows
    ]

    return {
        "code": code,
        "name": FUTURE_NAMES.get(commodity, commodity),
        "market": "TAIFEX",
        "months": months,
        "fields": FIELDS,
        "items": items,
        "earliest": items[0][0] if items else None,
        "latest": items[-1][0] if items else None,
        "source": "db",
        "turnover_label": "成交量（口）",
        "turnover_unit": "口",
    }
