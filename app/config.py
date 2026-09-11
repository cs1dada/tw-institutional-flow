"""全域設定：路徑、資料來源網址與抓取行為參數。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stock.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 市場別代碼
MARKET_TWSE = "TWSE"
MARKET_TPEX = "TPEX"

# 上市 (證交所)
TWSE_INST_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_QUOTE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"

# 上櫃 (櫃買中心)
TPEX_INST_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TPEX_QUOTE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"

# 個股產業別對照 (ISIN 對照表，內含中文產業名稱)
ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp"
ISIN_MODE = {MARKET_TWSE: "2", MARKET_TPEX: "4"}
ISIN_ENCODING = "ms950"

# ETF 等非一般類股的虛擬產業名稱
INDUSTRY_ETF = "ETF"
INDUSTRY_UNKNOWN = "未分類"

# 抓取行為
REQUEST_TIMEOUT = 40
# 回補歷史時每次請求之間的間隔秒數，避免被證交所擋
THROTTLE_SECONDS = 3.0
MAX_RETRY = 3
RETRY_BACKOFF = 5.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
