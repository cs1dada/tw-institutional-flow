"""臺股儀表板 (證交所與櫃買中心 2026/09/23 上線) 背後的 JSON 介面。

儀表板網頁本身也是呼叫這些介面，沒有正式文件，欄位意義以網頁上的說明為準：

- 證交所 BFIJ3U_TREND：全市場擔保維持率、追繳戶數與金額、處分戶數與金額，
  以及上市的信用交易成交值。一次最多 60 個交易日，資料自 2026/08/03 起
- 證交所 MI_MARGN_TREND：上市融資餘額與總市值，一次最多 60 個交易日
- 證交所 BFIGTU：證券商申報的投資人違約金額，可指定日期區間
- 證交所 MI_MARGN_HISTORY、櫃買 marginHistory：2000 年起的年度融資占市值與信用交易占比
- 櫃買 marginTrend：上櫃總市值與成交值，只有最近約 40 個交易日
- 櫃買 margin：上櫃單日摘要，含信用交易成交值。雖然可帶日期，實際上幾乎只查得到最新一天，
  查不到的日期會直接回傳最新一天，呼叫端要比對日期

全市場擔保維持率是官方以投資人整戶 (融資、融券合併) 計算的數字，
和本站以融資市值除以融資餘額估算的民間版不同，通常比較高。

所有函式在查無資料時回傳空容器或 None，不丟例外。
"""
import logging

from app.fetchers.twse import to_float
from app.http_client import fetch

logger = logging.getLogger(__name__)

TWSE_DASHBOARD = "https://www.twse.com.tw/rwd/zh"
OFFICIAL_TREND_URL = f"{TWSE_DASHBOARD}/marginTrading/BFIJ3U_TREND"
TWSE_MARGIN_TREND_URL = f"{TWSE_DASHBOARD}/marginTrading/MI_MARGN_TREND"
TWSE_MARGIN_HISTORY_URL = f"{TWSE_DASHBOARD}/marginTrading/MI_MARGN_HISTORY"
TWSE_DEFAULT_URL = f"{TWSE_DASHBOARD}/announcement/BFIGTU"

TPEX_DASHBOARD = "https://www.tpex.org.tw/www/dashboardOtc"
TPEX_MARGIN_URL = f"{TPEX_DASHBOARD}/margin"
TPEX_MARGIN_TREND_URL = f"{TPEX_DASHBOARD}/marginTrend"
TPEX_MARGIN_HISTORY_URL = f"{TPEX_DASHBOARD}/marginHistory"

# 儀表板資料的第一天
SITE_MIN_DATE = "20260803"
# 證交所趨勢介面一次可取的最多交易日數
TREND_MAX_DAYS = 60
# 櫃買趨勢介面實際能回傳的天數有限，要多少給多少
TPEX_TREND_DAYS = 120

YI = 1e8


def _twse_trend(url, date_str=None, days=TREND_MAX_DAYS):
    params = {"response": "json", "days": days}
    if date_str:
        params["date"] = date_str
    payload = fetch(url, params=params)
    if payload.get("stat") != "OK":
        return []
    return payload.get("data") or []


def fetch_official_trend(date_str=None, days=TREND_MAX_DAYS):
    """全市場擔保維持率與追繳處分，以及上市信用交易成交值，截至 date_str (預設最新)。

    回傳 [{date, keep_rate (%), below_acc_num (戶), call_amt (元), exe_acc_num (戶),
    exe_amt (元), credit_amount (元，上市)}]，由舊到新。
    """
    return [
        {
            "date": row["date"],
            "keep_rate": row.get("keepRate"),
            "below_acc_num": row.get("belowAccNum"),
            "call_amt": row.get("callAmt"),
            "exe_acc_num": row.get("exeAccNum"),
            "exe_amt": row.get("exeAmt"),
            "credit_amount": row.get("crdAmt"),
        }
        for row in _twse_trend(OFFICIAL_TREND_URL, date_str, days)
        if row.get("date")
    ]


def fetch_twse_market_cap_trend(date_str=None, days=TREND_MAX_DAYS):
    """上市總市值，回傳 [{date, market_cap (元)}]。來源單位為億元。"""
    return [
        {"date": row["date"], "market_cap": row["marketValue"] * YI}
        for row in _twse_trend(TWSE_MARGIN_TREND_URL, date_str, days)
        if row.get("date") and row.get("marketValue")
    ]


def fetch_tpex_trend(days=TPEX_TREND_DAYS):
    """上櫃總市值與成交值，回傳 [{date, market_cap (元), turnover (元)}]。來源單位為億元。"""
    payload = fetch(TPEX_MARGIN_TREND_URL, params={"lang": "zh-tw", "days": days})
    if payload.get("stat") != "ok":
        return []
    return [
        {
            "date": row["date"],
            "market_cap": row["marketCap"] * YI if row.get("marketCap") else None,
            "turnover": row["totalAmount"] * YI if row.get("totalAmount") else None,
        }
        for row in payload.get("trend") or []
        if row.get("date")
    ]


def fetch_tpex_day(date_str):
    """上櫃單日摘要，回傳 {market_cap, turnover, credit_amount} (元)。

    查不到的日期會回傳最新一天的資料，日期不符就視為查無資料。
    """
    payload = fetch(TPEX_MARGIN_URL, params={"lang": "zh-tw", "date": date_str})
    if payload.get("stat") != "ok" or payload.get("date") != date_str:
        return None

    def yi(name):
        value = payload.get(name)
        return value * YI if value else None

    return {
        "market_cap": yi("marketCap"),
        "turnover": yi("totalAmount"),
        "credit_amount": yi("creditAmount"),
    }


def fetch_default_amounts(start, end):
    """證券商申報的投資人違約金額，回傳 [{date, default_amt, default_net_amt}] (元)。

    default_amt 為買進、賣出合計，default_net_amt 為買賣相抵後的金額。
    """
    payload = fetch(
        TWSE_DEFAULT_URL,
        params={"startDate": start, "endDate": end, "response": "json"},
    )
    tables = payload.get("tables") or []
    if payload.get("stat") != "OK" or not tables:
        return []
    rows = []
    for raw in tables[0].get("data") or []:
        if len(raw) < 3 or not raw[0]:
            continue
        year, month, day = str(raw[0]).split("/")
        rows.append({
            "date": f"{int(year) + 1911}{month}{day}",
            "default_amt": to_float(raw[1]),
            "default_net_amt": to_float(raw[2]),
        })
    return rows


def fetch_credit_history():
    """年度融資占市值與信用交易占比 (%)，回傳 {市場: [[年, 融資占市值, 信用交易占比]]}。

    當年度的數字是截至上個月底。
    """
    result = {}
    payload = fetch(TWSE_MARGIN_HISTORY_URL, params={"response": "json"})
    if payload.get("stat") == "OK":
        result["TWSE"] = [
            [str(row["year"]), row.get("marginRatio"), row.get("creditRatio")]
            for row in payload.get("data") or []
            if row.get("year")
        ]
    payload = fetch(TPEX_MARGIN_HISTORY_URL, params={"lang": "zh-tw"})
    if payload.get("stat") == "ok":
        result["TPEX"] = [
            [str(row["date"])[:4], row.get("marginRatio"), row.get("creditRatio")]
            for row in payload.get("trend") or []
            if row.get("date")
        ]
    return result
