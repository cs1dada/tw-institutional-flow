"""題材分類個股的年度 EPS 共識快照。

資料來自 Yahoo Finance，只能取得當下的值，每天存一份。前瞻本益比在估值趨勢矩陣
(valuation_grid.py) 才以當日收盤計算，這裡只負責抓取與讀取預估值。
"""
import logging
import time
from datetime import date, datetime

from app.fetchers.yahoo import fetch_eps_estimates, fetch_fx_rate
from app.services.themes import classified_codes, load_themes

logger = logging.getLogger(__name__)

# 每檔之間的間隔秒數，題材股約 200 檔，全部跑完約 3 到 4 分鐘
THROTTLE_SECONDS = 0.3
# 被限流時的等待秒數與重試次數
RETRY_WAIT_SECONDS = 30
RETRIES = 2
# 連續失敗達到這個次數就放棄，多半是整個被擋
MAX_CONSECUTIVE_ERRORS = 10


def _fetch_with_retry(code, market):
    for attempt in range(RETRIES + 1):
        try:
            return fetch_eps_estimates(code, market)
        except Exception as exc:  # yfinance 的例外型別隨版本變動，統一處理
            if attempt == RETRIES:
                raise
            logger.warning("%s 抓取失敗，%d 秒後重試：%s", code, RETRY_WAIT_SECONDS, exc)
            time.sleep(RETRY_WAIT_SECONDS)
    return None, []


def purge_broken_snapshots(conn):
    """刪除分析師人數整批缺漏的快照日期，回傳被刪除的日期。

    yfinance 1.8 曾讓分析師人數整批變成空值 (2026-11-04、11-05)，那幾天的快照
    全部會判定為分析師不足。Yahoo 沒有歷史可補抓，只能整份刪除，
    日期選單就不會出現這些日期。正常的快照中缺分析師人數的只有零星幾檔。
    """
    broken = [
        row["date"]
        for row in conn.execute(
            """
            SELECT date FROM eps_estimate
            WHERE eps_avg IS NOT NULL
            GROUP BY date
            HAVING SUM(analysts IS NULL) * 2 > COUNT(*)
            """
        )
    ]
    for day in broken:
        conn.execute("DELETE FROM eps_estimate WHERE date = ?", (day,))
        logger.warning("刪除分析師人數缺漏的 EPS 快照 %s", day)
    conn.commit()
    return broken


def ingest_eps_estimates(conn, codes=None):
    """抓取題材分類個股的 EPS 共識並存入當日快照，回傳統計。"""
    purged = purge_broken_snapshots(conn)
    codes = sorted(codes or classified_codes(load_themes()))
    markets = {r["code"]: r["market"] for r in conn.execute("SELECT code, market FROM stock_info")}
    today = date.today().strftime("%Y%m%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats = {
        "date": today, "total": len(codes), "saved": 0, "missing": [], "errors": [], "foreign": {},
        "no_analysts": 0, "purged": purged,
    }
    fx_rates = {}
    consecutive = 0
    for index, code in enumerate(codes):
        if index:
            time.sleep(THROTTLE_SECONDS)
        try:
            ticker, rows = _fetch_with_retry(code, markets.get(code))
            consecutive = 0
        except Exception as exc:
            consecutive += 1
            stats["errors"].append(code)
            logger.error("%s 抓取失敗：%s", code, exc)
            if consecutive >= MAX_CONSECUTIVE_ERRORS:
                logger.error("連續 %d 檔失敗，停止抓取", consecutive)
                break
            continue
        # 外幣計價的預估換算成台幣，匯率取不到就略過該年度，不存錯誤的數字
        converted = []
        for r in rows:
            currency = r["currency"]
            if currency not in fx_rates:
                fx_rates[currency] = fetch_fx_rate(currency)
            rate = fx_rates[currency]
            if rate is None:
                continue
            if currency != "TWD":
                stats["foreign"][code] = currency
            converted.append({
                **r,
                "fx_rate": rate,
                **{k: None if r[k] is None else r[k] * rate for k in ("eps_avg", "eps_low", "eps_high")},
            })
        rows = converted
        if not rows:
            stats["missing"].append(code)
            continue
        conn.executemany(
            """
            INSERT OR REPLACE INTO eps_estimate
                (date, code, fiscal_year, ticker, currency, fx_rate,
                 eps_avg, eps_low, eps_high, analysts, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (today, code, r["fiscal_year"], ticker, r["currency"], r["fx_rate"],
                 r["eps_avg"], r["eps_low"], r["eps_high"], r["analysts"], now)
                for r in rows
            ],
        )
        stats["saved"] += 1
        if all(r["analysts"] is None for r in rows):
            stats["no_analysts"] += 1
    conn.commit()
    # yfinance 改版曾讓分析師人數整批變成空值，頁面因此全部判定為分析師不足；
    # 這種情況不會拋出例外，只能從比例看出來
    if stats["saved"] and stats["no_analysts"] > stats["saved"] / 2:
        logger.error(
            "%d / %d 檔有 EPS 卻沒有分析師人數，可能是 yfinance 或 Yahoo 回應格式改變",
            stats["no_analysts"], stats["saved"],
        )
    return stats


def latest_estimates(conn, codes, as_of=None):
    """各股在 as_of (含) 之前最近一次抓取日的年度預估。

    回傳 {代號: {"date": 抓取日, "years": {年度: {...}}}}。某檔當天抓取失敗時，
    會沿用它更早的快照。as_of 為 None 時取最新一份。
    """
    if not codes:
        return {}
    codes = list(codes)
    marks = ",".join("?" * len(codes))
    as_of = as_of or "99999999"
    rows = conn.execute(
        f"""
        SELECT e.code, e.date, e.fiscal_year, e.eps_avg, e.eps_low, e.eps_high, e.analysts
        FROM eps_estimate AS e
        JOIN (
            SELECT code, MAX(date) AS date FROM eps_estimate
            WHERE code IN ({marks}) AND date <= ? GROUP BY code
        ) AS m ON m.code = e.code AND m.date = e.date
        """,
        (*codes, as_of),
    ).fetchall()
    result = {}
    for r in rows:
        item = result.setdefault(r["code"], {"date": r["date"], "years": {}})
        item["years"][r["fiscal_year"]] = {
            "eps_avg": r["eps_avg"],
            "eps_low": r["eps_low"],
            "eps_high": r["eps_high"],
            "analysts": r["analysts"],
        }
    return result
