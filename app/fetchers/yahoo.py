"""Yahoo Finance 估值資料 (透過 yfinance)。

證交所與櫃買只提供近四季本益比，前瞻本益比需要分析師共識 EPS，官方沒有，
因此改用 Yahoo Finance。這是非官方介面，可能限流或改版，呼叫端要能承受失敗。
"""
import logging

logger = logging.getLogger(__name__)

SUFFIX = {"TWSE": ".TW", "TPEX": ".TWO"}


def _number(value):
    """Yahoo 偶爾回傳字串 'Infinity' 或非數值，一律轉為 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def fetch_valuation(code, market):
    """取得單一個股的估值，查無報價時回傳 None。

    依市場別決定 Yahoo 代號的後綴；市場別不明時兩種後綴都試。
    網路錯誤或限流會直接拋出例外，由呼叫端決定是否重試。
    """
    import yfinance as yf

    suffixes = [SUFFIX[market]] if market in SUFFIX else [".TW", ".TWO"]
    for suffix in suffixes:
        ticker = code + suffix
        info = yf.Ticker(ticker).info or {}
        if not (info.get("regularMarketPrice") or info.get("currentPrice") or info.get("trailingPE")):
            continue
        analysts = info.get("numberOfAnalystOpinions")
        return {
            "ticker": ticker,
            "trailing_pe": _number(info.get("trailingPE")),
            "forward_pe": _number(info.get("forwardPE")),
            "forward_eps": _number(info.get("forwardEps")),
            "analysts": int(analysts) if isinstance(analysts, int) else None,
        }
    return None
