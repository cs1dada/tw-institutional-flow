"""Yahoo Finance 分析師共識 EPS 預估 (透過 yfinance)。

證交所與櫃買只提供近四季本益比，前瞻本益比需要分析師共識 EPS，官方沒有，
因此改用 Yahoo Finance。這是非官方介面，可能限流或改版，呼叫端要能承受失敗。

Yahoo 只提供今年 (0y) 與明年 (+1y) 兩個會計年度的預估。年度取自原始資料的
endDate；yfinance 的 DataFrame 沒有這個欄位，所以讀它內部保存的原始回應，
讀不到時改用 info 的 nextFiscalYearEnd 推算。

部分個股 (多為 KY 股) 的預估以美元等外幣計價，原始資料的 earningsCurrency 會標示，
換算成台幣由呼叫端以 fetch_fx_rate 處理。
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SUFFIX = {"TWSE": ".TW", "TPEX": ".TWO"}
YEAR_PERIODS = {"0y": 0, "+1y": 1}


def _number(value):
    """Yahoo 原始值可能是 {'raw': 1.2}、數字或缺值，一律轉為 float 或 None。"""
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _from_raw_trend(ticker_obj):
    """從 yfinance 保存的原始 earningsTrend 取年度預估，格式不符時回傳 None。"""
    trend = getattr(getattr(ticker_obj, "_analysis", None), "_earnings_trend", None)
    if not isinstance(trend, list):
        return None
    rows = []
    for item in trend:
        if item.get("period") not in YEAR_PERIODS or not item.get("endDate"):
            continue
        est = item.get("earningsEstimate") or {}
        analysts = _number(est.get("numberOfAnalysts"))
        rows.append({
            "currency": est.get("earningsCurrency") or "TWD",
            "fiscal_year": int(str(item["endDate"])[:4]),
            "eps_avg": _number(est.get("avg")),
            "eps_low": _number(est.get("low")),
            "eps_high": _number(est.get("high")),
            "analysts": int(analysts) if analysts is not None else None,
        })
    return rows


def _from_dataframe(ticker_obj, frame):
    """備援：DataFrame 加上 info 的 nextFiscalYearEnd 推算年度。"""
    end = (ticker_obj.info or {}).get("nextFiscalYearEnd")
    if not isinstance(end, (int, float)):
        return []
    base_year = datetime.fromtimestamp(end, tz=timezone.utc).year
    rows = []
    for period, offset in YEAR_PERIODS.items():
        if period not in frame.index:
            continue
        row = frame.loc[period]
        analysts = _number(row.get("numberOfAnalysts"))
        currency = row.get("currency")
        rows.append({
            "currency": currency if isinstance(currency, str) and currency else "TWD",
            "fiscal_year": base_year + offset,
            "eps_avg": _number(row.get("avg")),
            "eps_low": _number(row.get("low")),
            "eps_high": _number(row.get("high")),
            "analysts": int(analysts) if analysts is not None else None,
        })
    return rows


def fetch_fx_rate(currency):
    """1 單位外幣兌台幣的最新匯率，取不到時回傳 None。"""
    import yfinance as yf

    if currency == "TWD":
        return 1.0
    try:
        rate = yf.Ticker(f"{currency}TWD=X").fast_info["last_price"]
    except Exception as exc:
        logger.warning("%s 兌台幣匯率取得失敗：%s", currency, exc)
        return None
    return _number(rate)


def fetch_eps_estimates(code, market):
    """取得單一個股今年與明年的 EPS 共識，回傳 (Yahoo 代號, [年度預估...])。

    沒有分析師追蹤時回傳空 list。網路錯誤或限流會直接拋出例外，由呼叫端決定是否重試。
    """
    import yfinance as yf

    ticker = code + SUFFIX.get(market, ".TW")
    ticker_obj = yf.Ticker(ticker)
    frame = ticker_obj.earnings_estimate
    if frame is None or frame.empty:
        return ticker, []
    rows = _from_raw_trend(ticker_obj)
    if rows is None:
        logger.info("%s 讀不到原始 earningsTrend，改用 nextFiscalYearEnd 推算年度", ticker)
        rows = _from_dataframe(ticker_obj, frame)
    return ticker, [r for r in rows if r["eps_avg"] is not None]
