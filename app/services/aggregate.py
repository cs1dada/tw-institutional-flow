"""類股資金流向聚合計算。"""
import logging

from app import config

logger = logging.getLogger(__name__)

AGGREGATE_SQL = """
INSERT INTO industry_daily (
    date, industry, foreign_amt, trust_amt, dealer_amt, total_amt,
    buy_count, sell_count, stock_count
)
SELECT
    t.date,
    s.industry,
    SUM(t.foreign_amt),
    SUM(t.trust_amt),
    SUM(t.dealer_amt),
    SUM(t.total_amt),
    SUM(CASE WHEN t.total_net > 0 THEN 1 ELSE 0 END),
    SUM(CASE WHEN t.total_net < 0 THEN 1 ELSE 0 END),
    COUNT(*)
FROM inst_trade AS t
JOIN stock_info AS s ON s.code = t.code
WHERE t.date = ?
GROUP BY t.date, s.industry
"""


def rebuild_industry_daily(conn, date_str):
    """重算指定日期的類股聚合資料 (先刪後建，可安全重跑)。"""
    conn.execute("DELETE FROM industry_daily WHERE date = ?", (date_str,))
    conn.execute(AGGREGATE_SQL, (date_str,))
    count = conn.execute(
        "SELECT COUNT(*) FROM industry_daily WHERE date = ?", (date_str,)
    ).fetchone()[0]
    conn.commit()
    logger.info("%s 類股聚合完成，共 %d 個類別", date_str, count)
    return count
