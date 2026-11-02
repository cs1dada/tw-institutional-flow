"""題材分類個股的估值快照。

前瞻本益比來自 Yahoo Finance 的分析師共識，只能取得當下的值，每天存一份。
分析師人數太少時數字常常離譜 (例如 1 位分析師給出 600 多倍)，網頁上依
MIN_ANALYSTS 決定是否顯示，資料庫則全部保留。
"""
import logging
import time
from datetime import date, datetime

from app.fetchers.yahoo import fetch_valuation

logger = logging.getLogger(__name__)

# 每檔之間的間隔秒數，題材股約 200 檔，全部跑完約 2 到 3 分鐘
THROTTLE_SECONDS = 0.3
# 被限流時的等待秒數與重試次數
RETRY_WAIT_SECONDS = 30
RETRIES = 2
# 連續失敗達到這個次數就放棄，多半是整個被擋
MAX_CONSECUTIVE_ERRORS = 10
# 分析師少於這個人數時，網頁不顯示前瞻本益比
MIN_ANALYSTS = 3


def _fetch_with_retry(code, market):
    for attempt in range(RETRIES + 1):
        try:
            return fetch_valuation(code, market)
        except Exception as exc:  # yfinance 的例外型別隨版本變動，統一處理
            if attempt == RETRIES:
                raise
            logger.warning("%s 抓取失敗，%d 秒後重試：%s", code, RETRY_WAIT_SECONDS, exc)
            time.sleep(RETRY_WAIT_SECONDS)
    return None


def ingest_theme_valuations(conn, codes=None):
    """抓取題材分類個股的估值並存入當日快照，回傳統計。"""
    # themes 會匯入本模組取用 latest_valuations，這裡延後匯入以免循環
    from app.services.themes import classified_codes, load_themes

    codes = sorted(codes or classified_codes(load_themes()))
    markets = {r["code"]: r["market"] for r in conn.execute("SELECT code, market FROM stock_info")}
    today = date.today().strftime("%Y%m%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats = {"date": today, "total": len(codes), "saved": 0, "forward_pe": 0, "missing": [], "errors": []}
    consecutive = 0
    for index, code in enumerate(codes):
        if index:
            time.sleep(THROTTLE_SECONDS)
        try:
            row = _fetch_with_retry(code, markets.get(code))
            consecutive = 0
        except Exception as exc:
            consecutive += 1
            stats["errors"].append(code)
            logger.error("%s 抓取失敗：%s", code, exc)
            if consecutive >= MAX_CONSECUTIVE_ERRORS:
                logger.error("連續 %d 檔失敗，停止抓取", consecutive)
                break
            continue
        if row is None:
            stats["missing"].append(code)
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO stock_valuation
                (date, code, ticker, trailing_pe, forward_pe, forward_eps, analysts, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (today, code, row["ticker"], row["trailing_pe"], row["forward_pe"],
             row["forward_eps"], row["analysts"], now),
        )
        stats["saved"] += 1
        if row["forward_pe"] is not None:
            stats["forward_pe"] += 1
    conn.commit()
    return stats


def latest_valuations(conn, codes):
    """各股最近一次的估值，回傳 {代號: {...}}。"""
    if not codes:
        return {}
    codes = list(codes)
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""
        SELECT v.code, v.date, v.trailing_pe, v.forward_pe, v.forward_eps, v.analysts
        FROM stock_valuation AS v
        JOIN (
            SELECT code, MAX(date) AS date FROM stock_valuation
            WHERE code IN ({marks}) GROUP BY code
        ) AS m ON m.code = v.code AND m.date = v.date
        """,
        codes,
    ).fetchall()
    return {
        r["code"]: {
            "date": r["date"],
            "trailing_pe": None if r["trailing_pe"] is None else round(r["trailing_pe"], 1),
            "forward_pe": None if r["forward_pe"] is None else round(r["forward_pe"], 1),
            "forward_eps": None if r["forward_eps"] is None else round(r["forward_eps"], 2),
            "analysts": r["analysts"],
        }
        for r in rows
    }
