"""全域設定：路徑、資料來源網址與抓取行為參數。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stock.db"


def _load_env_file():
    """把專案根目錄的 .env 讀進環境變數，已存在的不覆寫。

    行情 API 的金鑰不寫進版控，但每次啟動都要手動設環境變數太囉嗦，
    因此支援 .env (已列入 .gitignore)。格式為每行一個 KEY=VALUE，
    井字號開頭為註解。刻意不依賴 python-dotenv，少一個相依套件。
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

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

# 個股歷史日線 (K 線圖用)。資料來自盤後匯入的 daily_price，不消耗行情 API 額度
HISTORY_DEFAULT_MONTHS = 12
HISTORY_MAX_MONTHS = 120

# ---------------------------------------------------------------------------
# 個股即時行情頁
# ---------------------------------------------------------------------------

# 富果行情 API。金鑰只從環境變數讀取，不寫進版控：
#     PowerShell   $env:FUGLE_API_KEY = "..."
#     bash         export FUGLE_API_KEY=...
# 沒有設定時整頁自動關閉，也不會對外送出任何請求。
FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "").strip()
QUOTE_ENABLED = bool(FUGLE_API_KEY)

FUGLE_BASE_URL = "https://api.fugle.tw/marketdata/v1.0/stock"
# 發行量加權股價指數在富果的代號
FUGLE_INDEX_SYMBOL = "IX0001"
# API 回傳的官方全名是「發行量加權股價指數」，畫面上改用通稱
FUGLE_INDEX_NAME = "台灣加權指數"

# 富果免費方案為每分鐘 60 次請求，這裡壓在一半，
# 留餘裕給共用同一把金鑰的其他程式 (例如終端機看盤腳本)。
FUGLE_MAX_CALLS_PER_MINUTE = 30

# 微型臺指期貨走期交所自己的看盤端點：富果的期貨行情屬於付費方案，
# 免費金鑰會收到 403，而期交所這支免費且不需認證，資料為逐筆更新。
# 與 MIS 一樣沒有 CORS 標頭，必須由後端代抓。
TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteDetail"
TAIFEX_REFERER = "https://mis.taifex.com.tw/futures/"
# 微型臺指期貨的商品代碼字首，月份碼與年碼由 near_month_symbol 推算
TAIFEX_FUTURE_PREFIX = "TMF"
# 期交所回傳的名稱是「微臺指期106」這種合約月份寫法，畫面上改用商品通稱，
# 合約則以代碼呈現 (例如 TMFJ6-F)，比「106」直觀
TAIFEX_FUTURE_NAME = "微型臺指期"

# 報價快取秒數。同一檔被多個瀏覽器分頁同時開著時共用一份，
# 不會各自向外送出請求。期交所與富果的資料都是秒級更新，
# 十秒一次足以看盤，也讓每分鐘的請求數維持在個位數。
QUOTE_CACHE_SECONDS = 10
# 分時 K 線的變化比報價慢得多，快取拉長以省下請求
QUOTE_CANDLE_CACHE_SECONDS = 60
# 分時 K 線的時間單位 (分鐘)
QUOTE_CANDLE_TIMEFRAME = "5"

# 臺指期交易時段：一般盤與盤後盤 (盤後盤跨日到隔天清晨)
FUTURE_SESSION_OPEN = "08:45"
FUTURE_SESSION_CLOSE = "13:45"
FUTURE_AFTERHOURS_OPEN = "15:00"
FUTURE_AFTERHOURS_CLOSE = "05:00"

# ---------------------------------------------------------------------------
# 永豐 Shioaji 即時行情頁
# ---------------------------------------------------------------------------

# 金鑰只從環境變數讀取，不寫進版控：
#     PowerShell   $env:SHIOAJI_API_KEY = "..."; $env:SHIOAJI_SECRET_KEY = "..."
# 兩者缺一整頁自動關閉，也不會建立任何連線。
SHIOAJI_API_KEY = os.environ.get("SHIOAJI_API_KEY", "").strip()
SHIOAJI_SECRET_KEY = os.environ.get("SHIOAJI_SECRET_KEY", "").strip()
SINO_ENABLED = bool(SHIOAJI_API_KEY and SHIOAJI_SECRET_KEY)

# 模擬環境。金鑰要通過永豐的 API 測試才會取得正式環境權限，
# 未開通時正式環境會回 "Token doesn't have production permission"。
# 模擬環境的「行情」是真實資料 (實測與其他來源一致)，只有下單是模擬的，
# 而本專案只讀行情、不下單，因此預設走模擬環境。
SHIOAJI_SIMULATION = True

# 商品代碼
SHIOAJI_INDEX_CODE = "IX0001"      # 發行量加權股價指數
SHIOAJI_FUTURE_CODE = "TMFR1"      # 微型臺指期貨「近月」連續合約，不需自行換約

# 使用限制 (https://sinotrade.github.io/zh/tutor/limit/)
#
#   每日流量      500 MB (近 30 日 0 成交的等級)，早上 8:00 重置
#   行情查詢      snapshots / ticks / kbars 合計 10 秒 50 次
#   盤中 kbars    270 次
#   訂閱數        200 檔；連線數 5 個
#
# 超過流量後行情查詢會「回傳空值」而不是報錯，是會靜默失敗的那種錯，
# 因此下面的每一項都刻意抓在官方上限之下，寧可少查也不要踩線。

# 行情查詢的滑動視窗節流，官方為 10 秒 50 次，這裡取其四成
SHIOAJI_QUERY_WINDOW_SECONDS = 10
SHIOAJI_MAX_QUERIES_PER_WINDOW = 20

# 報價快取秒數。三個標的一輪約 540 bytes，十秒一輪跑滿五小時約 1 MB，
# 佔每日流量的 0.2%，流量不是瓶頸，次數才是。
SINO_QUOTE_CACHE_SECONDS = 10

# 分時 K 線的完整重抓間隔與每日次數上限。
#
# 官方盤中 kbars 上限為 270 次，等於日盤 270 分鐘每分鐘一次。若每兩分鐘
# 重抓一次「今天全部的 1 分 K」，一檔一天就要 135 次，盯兩檔就撞上限。
#
# 因此改為：選定一檔時完整抓一次，之後用每 10 秒的報價快照自行追加最新
# 的那一根，只在間隔到了才重抓完整版做校正。這樣一檔一天只要十次上下，
# 分時圖也能跟報價一樣即時。
SINO_KBAR_REFRESH_SECONDS = 1800
SINO_KBAR_DAILY_LIMIT = 200

# 個股歷史日線 (K 線圖用)。
#
# Shioaji 的 kbars 只提供 1 分 K，日線要自己聚合，因此拉一段區間的成本
# 與根數成正比：實測約 60 bytes/根，3 個月約 1 MB、1 年約 4 MB。
# 次數不是問題 (一次查詢就拿一整段)，流量才是，所以預設只取一年，
# 更長的區間要使用者主動點選。
SINO_HISTORY_DEFAULT_MONTHS = 12
SINO_HISTORY_MAX_MONTHS = 36
# 歷史資料當天之內不會再變，快取可以拉得很長
SINO_HISTORY_CACHE_SECONDS = 1800
# 每日的歷史查詢次數上限。一次一年約 4 MB，20 次就是 80 MB，
# 佔每日流量的 16%，留給即時報價的空間仍然充裕
SINO_HISTORY_DAILY_LIMIT = 20
