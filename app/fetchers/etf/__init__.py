"""主動式 ETF 每日持股抓取。

各家投信的持股只公布在自己的官網，沒有集中來源，因此一家投信一個模組，
各自實作 `fetch_holdings(etf_code)`，回傳統一格式：

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

新增投信時，實作一個模組並在 ISSUERS 註冊，再把旗下 ETF 代號加入 ETF_ISSUER。
"""
from app.fetchers.etf import capital, nomura, uni

# 投信代號對應的抓取模組
ISSUERS = {
    "capital": capital,
    "nomura": nomura,
    "uni": uni,
}

# ETF 代號對應的投信。目前只收錄已完成介接的投信
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
}


def supported_etfs():
    """回傳目前可抓取持股的 ETF 代號清單。"""
    return sorted(ETF_ISSUER)


def fetch_holdings(etf_code):
    """抓取單一 ETF 的持股明細，未介接的投信回傳 None。"""
    issuer = ETF_ISSUER.get(etf_code)
    if issuer is None:
        return None
    return ISSUERS[issuer].fetch_holdings(etf_code)


def issuer_of(etf_code):
    return ETF_ISSUER.get(etf_code)
