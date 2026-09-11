"""上市 (證交所) 資料抓取。"""
import logging

from app import config
from app.http_client import fetch

logger = logging.getLogger(__name__)

# T86 三大法人買賣超日報的欄位位置
T86_CODE = 0
T86_NAME = 1
T86_FOREIGN_EX_DEALER_NET = 4    # 外陸資買賣超 (不含外資自營商)
T86_FOREIGN_DEALER_NET = 7       # 外資自營商買賣超
T86_TRUST_NET = 10               # 投信買賣超
T86_DEALER_NET = 11              # 自營商買賣超合計
T86_DEALER_SELF_NET = 14         # 自營商買賣超 (自行買賣)
T86_DEALER_HEDGE_NET = 17        # 自營商買賣超 (避險)
T86_TOTAL_NET = 18               # 三大法人買賣超合計
T86_MIN_COLUMNS = 19

# MI_INDEX 每日收盤行情的欄位位置
QUOTE_CODE = 0
QUOTE_VOLUME = 2
QUOTE_TURNOVER = 4
QUOTE_CLOSE = 8
QUOTE_MIN_COLUMNS = 9


def to_int(value):
    """將帶千分位的字串轉為整數，無法解析時回傳 0。"""
    text = str(value).replace(",", "").replace(" ", "").strip()
    if not text or text in ("--", "---"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def to_float(value):
    """將帶千分位的字串轉為浮點數，無法解析時回傳 None。"""
    text = str(value).replace(",", "").replace(" ", "").strip()
    if not text or text in ("--", "---"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_inst_trade(date_str):
    """取得指定日期的上市個股三大法人買賣超。

    date_str 格式為 YYYYMMDD。非交易日回傳空 list。
    """
    payload = fetch(
        config.TWSE_INST_URL,
        params={"date": date_str, "selectType": "ALL", "response": "json"},
    )
    if payload.get("stat") != "OK" or not payload.get("data"):
        logger.info("上市 %s 無三大法人資料 (stat=%s)", date_str, payload.get("stat"))
        return []

    rows = []
    for raw in payload["data"]:
        if len(raw) < T86_MIN_COLUMNS:
            continue
        foreign_net = to_int(raw[T86_FOREIGN_EX_DEALER_NET]) + to_int(raw[T86_FOREIGN_DEALER_NET])
        trust_net = to_int(raw[T86_TRUST_NET])
        dealer_net = to_int(raw[T86_DEALER_NET])
        total_net = to_int(raw[T86_TOTAL_NET])
        if foreign_net + trust_net + dealer_net != total_net:
            # 欄位位置若被證交所調整，此處會先示警而非寫入錯誤資料
            logger.warning(
                "上市 %s %s 三大法人加總與官方合計不符：%d + %d + %d != %d",
                date_str, raw[T86_CODE], foreign_net, trust_net, dealer_net, total_net,
            )
        rows.append(
            {
                "code": raw[T86_CODE].strip(),
                "name": raw[T86_NAME].strip(),
                "market": config.MARKET_TWSE,
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_self_net": to_int(raw[T86_DEALER_SELF_NET]),
                "dealer_hedge_net": to_int(raw[T86_DEALER_HEDGE_NET]),
                "dealer_net": dealer_net,
                "total_net": total_net,
            }
        )
    logger.info("上市 %s 三大法人 %d 筆", date_str, len(rows))
    return rows


def fetch_quotes(date_str):
    """取得指定日期的上市個股收盤行情，回傳 dict[code] = {...}。"""
    payload = fetch(
        config.TWSE_QUOTE_URL,
        params={"date": date_str, "type": "ALLBUT0999", "response": "json"},
    )
    if payload.get("stat") != "OK":
        logger.info("上市 %s 無收盤行情 (stat=%s)", date_str, payload.get("stat"))
        return {}

    quotes = {}
    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        if not fields or fields[0] != "證券代號" or "收盤價" not in fields:
            continue
        for raw in table.get("data", []):
            if len(raw) < QUOTE_MIN_COLUMNS:
                continue
            code = raw[QUOTE_CODE].strip()
            quotes[code] = {
                "close": to_float(raw[QUOTE_CLOSE]),
                "volume": to_int(raw[QUOTE_VOLUME]),
                "turnover": to_int(raw[QUOTE_TURNOVER]),
            }
    logger.info("上市 %s 收盤行情 %d 筆", date_str, len(quotes))
    return quotes
