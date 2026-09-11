"""上櫃 (櫃買中心) 資料抓取。

櫃買中心的 openapi 只提供最新一日資料，歷史回補需改用可帶日期的
zh-tw 端點，日期格式為西元 YYYY/MM/DD。
"""
import logging

from app import config
from app.fetchers.twse import to_float, to_int
from app.http_client import fetch

logger = logging.getLogger(__name__)

# 三大法人買賣明細的欄位位置
INST_CODE = 0
INST_NAME = 1
INST_FOREIGN_NET = 10        # 外資及陸資合計買賣超
INST_TRUST_NET = 13          # 投信買賣超
INST_DEALER_SELF_NET = 16    # 自營商買賣超 (自行買賣)
INST_DEALER_HEDGE_NET = 19   # 自營商買賣超 (避險)
INST_DEALER_NET = 22         # 自營商買賣超合計
INST_TOTAL_NET = 23          # 三大法人買賣超合計
INST_MIN_COLUMNS = 24

# 每日收盤行情的欄位位置
QUOTE_CODE = 0
QUOTE_CLOSE = 2
QUOTE_VOLUME = 7
QUOTE_TURNOVER = 8
QUOTE_MIN_COLUMNS = 9


def to_tpex_date(date_str):
    """將 YYYYMMDD 轉為櫃買中心使用的 YYYY/MM/DD。"""
    return f"{date_str[0:4]}/{date_str[4:6]}/{date_str[6:8]}"


def _first_table(payload):
    """取出回應中的第一張表格。"""
    tables = payload.get("tables") or []
    return tables[0] if tables else {}


def fetch_inst_trade(date_str):
    """取得指定日期的上櫃個股三大法人買賣超。date_str 格式為 YYYYMMDD。"""
    payload = fetch(
        config.TPEX_INST_URL,
        params={"type": "Daily", "sect": "EW", "date": to_tpex_date(date_str), "response": "json"},
    )
    table = _first_table(payload)
    data = table.get("data") or []
    if not data:
        logger.info("上櫃 %s 無三大法人資料", date_str)
        return []

    rows = []
    for raw in data:
        if len(raw) < INST_MIN_COLUMNS:
            continue
        foreign_net = to_int(raw[INST_FOREIGN_NET])
        trust_net = to_int(raw[INST_TRUST_NET])
        dealer_net = to_int(raw[INST_DEALER_NET])
        total_net = to_int(raw[INST_TOTAL_NET])
        if foreign_net + trust_net + dealer_net != total_net:
            logger.warning(
                "上櫃 %s %s 三大法人加總與官方合計不符：%d + %d + %d != %d",
                date_str, raw[INST_CODE], foreign_net, trust_net, dealer_net, total_net,
            )
        rows.append(
            {
                "code": raw[INST_CODE].strip(),
                "name": raw[INST_NAME].strip(),
                "market": config.MARKET_TPEX,
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_self_net": to_int(raw[INST_DEALER_SELF_NET]),
                "dealer_hedge_net": to_int(raw[INST_DEALER_HEDGE_NET]),
                "dealer_net": dealer_net,
                "total_net": total_net,
            }
        )
    logger.info("上櫃 %s 三大法人 %d 筆", date_str, len(rows))
    return rows


def fetch_quotes(date_str):
    """取得指定日期的上櫃個股收盤行情，回傳 dict[code] = {...}。"""
    payload = fetch(
        config.TPEX_QUOTE_URL,
        params={"type": "EW", "date": to_tpex_date(date_str), "response": "json"},
    )
    table = _first_table(payload)
    quotes = {}
    for raw in table.get("data") or []:
        if len(raw) < QUOTE_MIN_COLUMNS:
            continue
        quotes[raw[QUOTE_CODE].strip()] = {
            "close": to_float(raw[QUOTE_CLOSE]),
            "volume": to_int(raw[QUOTE_VOLUME]),
            "turnover": to_int(raw[QUOTE_TURNOVER]),
        }
    logger.info("上櫃 %s 收盤行情 %d 筆", date_str, len(quotes))
    return quotes
