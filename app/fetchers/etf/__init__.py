"""主動式 ETF 每日持股抓取。

各家投信的持股只公布在自己的官網，沒有集中來源，因此一家投信一個模組，
各自實作 `fetch_holdings(etf_code, query_date=None)`，回傳統一格式：

    {
        "etf_code": "00980A",
        "date": "20260910",      # 以該投信提供的淨值日為準
        "nav": 24.84,
        "aum": 19694912917.0,
        "units": 792730000,
        "holdings": [
            {"stock_code": "2330", "stock_name": "台灣積體電路製造",
             "shares": 753000, "weight": 9.37},
            ...
        ],
    }

模組另需定義 QUERY_NEXT_DAY：查詢日若是清單適用日 (取得前一營業日的持股) 則為 True，
回補歷史時據此決定要查哪一天。

新增投信時，實作一個模組並在 ISSUERS 註冊，再把旗下 ETF 代號加入 ETF_ISSUER。
"""
from app.fetchers.etf import (
    allianz,
    capital,
    cathay,
    ctbc,
    fhtrust,
    fsitc,
    fubon,
    kgi,
    mega,
    nomura,
    sinopac,
    taishin,
    uni,
)

# 投信代號對應的抓取模組
ISSUERS = {
    "allianz": allianz,
    "capital": capital,
    "cathay": cathay,
    "ctbc": ctbc,
    "fhtrust": fhtrust,
    "fsitc": fsitc,
    "fubon": fubon,
    "kgi": kgi,
    "mega": mega,
    "nomura": nomura,
    "sinopac": sinopac,
    "taishin": taishin,
    "uni": uni,
}

# ETF 代號對應的投信。目前只收錄已完成介接的投信。
# 後來介接的投信只收以台股為主的 ETF，海外持股的基準日跟著海外市場，不納入；
# 摩根的使用條款明文禁止爬蟲、聯博的 API 以 robots.txt 全面拒絕，因此不介接
ETF_ISSUER = {
    # 野村
    "00980A": "nomura",
    "00985A": "nomura",
    "00999A": "nomura",
    # 統一
    "00403A": "uni",
    "00411A": "uni",
    "00981A": "uni",
    "00988A": "uni",
    # 群益
    "00982A": "capital",
    "00992A": "capital",
    "00997A": "capital",
    # 中信
    "00406A": "ctbc",
    "00983A": "ctbc",
    "00995A": "ctbc",
    # 安聯
    "00402A": "allianz",
    "00984A": "allianz",
    "00993A": "allianz",
    # 國泰
    "00400A": "cathay",
    # 富邦
    "00405A": "fubon",
    # 凱基
    "00407A": "kgi",
    # 第一金
    "00408A": "fsitc",
    "00994A": "fsitc",
    # 永豐
    "00410A": "sinopac",
    # 台新
    "00987A": "taishin",
    # 復華
    "00991A": "fhtrust",
    # 兆豐
    "00996A": "mega",
}


def supported_etfs():
    """回傳目前可抓取持股的 ETF 代號清單。"""
    return sorted(ETF_ISSUER)


def fetch_holdings(etf_code, query_date=None):
    """抓取單一 ETF 的持股明細，未介接的投信回傳 None。

    query_date 為 None 時取最新一日，否則以該日查詢 (日期語意依投信而定，見 query_next_day)。
    """
    issuer = ETF_ISSUER.get(etf_code)
    if issuer is None:
        return None
    return ISSUERS[issuer].fetch_holdings(etf_code, query_date)


def query_next_day(etf_code):
    """該 ETF 的投信是否要查次一營業日，才能取得指定日期的持股。"""
    return ISSUERS[ETF_ISSUER[etf_code]].QUERY_NEXT_DAY


def issuer_of(etf_code):
    return ETF_ISSUER.get(etf_code)
