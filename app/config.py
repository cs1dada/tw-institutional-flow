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

# 大盤指數 (發行量加權股價指數)，兩支端點皆一次回傳整月
TWSE_INDEX_OHLC_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TWSE_INDEX_VALUE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
INDEX_TAIEX = "TAIEX"
INDEX_NAMES = {INDEX_TAIEX: "發行量加權股價指數"}

# 上櫃 (櫃買中心)
TPEX_INST_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TPEX_QUOTE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"

# 盤中觀察的總開關。預設關閉：MIS 是給看盤網頁用的內部介面，
# 不在證交所 OpenAPI 平台上，也沒有公布任何頻率規則，
# 實測連續掃描會讓整個 mis.twse.com.tw 對該 IP 停止回應達數十分鐘。
# 開啟後每三分鐘會對 MIS 送出 24 個請求，風險自負。
INTRADAY_ENABLED = False

# 盤中即時報價 (證交所 MIS)
# 這支端點沒有 CORS 標頭，瀏覽器無法直接呼叫，只能由後端代為抓取
MIS_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_REFERER = "https://mis.twse.com.tw/stock/fibest.jsp"
# 單次請求的檔數。實測 120 檔可過、150 檔會被拒，取 100 保留餘裕
MIS_BATCH_SIZE = 100
# 同時進行的批次數。全市場約 24 批，序列抓取要近 30 秒。
# 併發拉到 6 時 MIS 會以 RemoteDisconnected 斷線，3 條較為穩定
MIS_CONCURRENCY = 3
# 掃描一輪要 24 個請求，MIS 原本是給看盤頁查少數幾檔用的。
# 實測在半小時內送出約 200 個請求後，整個 mis.twse.com.tw 會對該 IP
# 停止回應達 20 分鐘以上 (連網頁本身都打不開)，因此間隔必須拉得夠開：
# 三分鐘一輪等於每分鐘 8 個請求，一個交易日約 2200 個請求。
# 類股輪動不是秒級事件，要看更新的當下可按畫面上的「立即更新」
INTRADAY_CACHE_SECONDS = 180
# 被來源拒絕後的退避秒數，連續失敗會逐次加倍，最多到上限值。
# 實測封鎖可持續 20 分鐘以上，上限設為 30 分鐘才足以等到解除
INTRADAY_BACKOFF_SECONDS = 60
INTRADAY_BACKOFF_MAX = 1800
# 盤中時段 (含試撮與收盤後的零股撮合緩衝)，超出此範圍不再向外抓取
INTRADAY_OPEN = "08:30"
INTRADAY_CLOSE = "14:00"

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
