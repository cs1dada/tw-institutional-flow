"""SQLite 連線管理與資料表結構。"""
import sqlite3

from app import config

SCHEMA = """
-- 個股主檔：代號、名稱、市場別與產業別
CREATE TABLE IF NOT EXISTS stock_info (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    market          TEXT NOT NULL,
    industry        TEXT NOT NULL,
    is_etf          INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_info_industry ON stock_info(industry);

-- 每日收盤行情
CREATE TABLE IF NOT EXISTS daily_price (
    date            TEXT NOT NULL,
    code            TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          INTEGER,
    turnover        INTEGER,
    PRIMARY KEY (date, code)
);

-- 個股三大法人買賣超 (股數為原始資料，金額為以收盤價估算)
CREATE TABLE IF NOT EXISTS inst_trade (
    date              TEXT NOT NULL,
    code              TEXT NOT NULL,
    market            TEXT NOT NULL,
    foreign_net       INTEGER NOT NULL DEFAULT 0,  -- 外資合計 (含外資自營商)
    trust_net         INTEGER NOT NULL DEFAULT 0,  -- 投信
    dealer_self_net   INTEGER NOT NULL DEFAULT 0,  -- 自營商 (自行買賣)
    dealer_hedge_net  INTEGER NOT NULL DEFAULT 0,  -- 自營商 (避險)
    dealer_net        INTEGER NOT NULL DEFAULT 0,  -- 自營商合計
    total_net         INTEGER NOT NULL DEFAULT 0,  -- 三大法人合計
    close             REAL,                        -- 當日收盤價 (估算金額用)
    foreign_amt       REAL NOT NULL DEFAULT 0,     -- 以下為估算金額，單位：元
    trust_amt         REAL NOT NULL DEFAULT 0,
    dealer_amt        REAL NOT NULL DEFAULT 0,
    total_amt         REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (date, code)
);
CREATE INDEX IF NOT EXISTS idx_inst_trade_date ON inst_trade(date);

-- 類股每日資金流向 (由 inst_trade 聚合而成)
CREATE TABLE IF NOT EXISTS industry_daily (
    date            TEXT NOT NULL,
    industry        TEXT NOT NULL,
    foreign_amt     REAL NOT NULL DEFAULT 0,
    trust_amt       REAL NOT NULL DEFAULT 0,
    dealer_amt      REAL NOT NULL DEFAULT 0,
    total_amt       REAL NOT NULL DEFAULT 0,
    buy_count       INTEGER NOT NULL DEFAULT 0,   -- 該類股中三大法人買超的家數
    sell_count      INTEGER NOT NULL DEFAULT 0,
    stock_count     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, industry)
);
CREATE INDEX IF NOT EXISTS idx_industry_daily_date ON industry_daily(date);

-- 大盤指數每日開高低收與成交量值 (供 K 線圖使用)
CREATE TABLE IF NOT EXISTS index_daily (
    date            TEXT NOT NULL,
    index_code      TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          INTEGER NOT NULL DEFAULT 0,   -- 成交股數
    turnover        INTEGER NOT NULL DEFAULT 0,   -- 成交金額 (元)
    change          REAL,                          -- 漲跌點數
    PRIMARY KEY (date, index_code)
);
CREATE INDEX IF NOT EXISTS idx_index_daily_code ON index_daily(index_code, date);

-- 全市場籌碼：三大法人買賣金額與融資融券餘額 (market 為 TWSE / TPEX)。
-- 法人約 15:00 公布、融資要到晚間，兩者分開寫入，尚未取得的欄位為 NULL
CREATE TABLE IF NOT EXISTS market_chip (
    date            TEXT NOT NULL,
    market          TEXT NOT NULL,
    foreign_net     REAL,              -- 外資及陸資 (含外資自營商) 買賣超，單位：元
    trust_net       REAL,              -- 投信
    dealer_net      REAL,              -- 自營商 (自行買賣 + 避險)
    total_net       REAL,              -- 三大法人合計
    margin_amount   REAL,              -- 融資餘額，單位：元
    margin_units    INTEGER,           -- 融資餘額，單位：張
    short_units     INTEGER,           -- 融券餘額，單位：張
    margin_value    REAL,              -- 融資股票以當日收盤價計的市值，單位：元
    maintenance     REAL,              -- 融資維持率 (%) = margin_value / margin_amount
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, market)
);

-- 臺股儀表板的信用交易風險指標 (market 為 TWSE / TPEX / ALL)。
-- ALL 列為官方全市場擔保維持率與追繳處分；TWSE、TPEX 列為市值、成交值與信用交易成交值，
-- 供計算融資占市值與信用交易占成交比重；違約金額為證交所公布，記在 TWSE 列
CREATE TABLE IF NOT EXISTS market_credit (
    date            TEXT NOT NULL,
    market          TEXT NOT NULL,
    keep_rate       REAL,              -- 全市場擔保維持率 (%)，整戶融資融券合併計算
    below_acc_num   INTEGER,           -- 整戶擔保維持率低於 130% 的戶數
    call_amt        REAL,              -- 當日通知應補繳金額，單位：元
    exe_acc_num     INTEGER,           -- 次一營業日應處分的戶數
    exe_amt         REAL,              -- 次一營業日應處分的金額，單位：元
    market_cap      REAL,              -- 總市值，單位：元
    turnover        REAL,              -- 總成交值，單位：元
    credit_amount   REAL,              -- 信用交易 (融資融券) 成交值，單位：元
    default_amt     REAL,              -- 投資人違約金額 (買賣合計)，單位：元
    default_net_amt REAL,              -- 投資人違約金額 (買賣相抵後)，單位：元
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, market)
);

-- 年度融資占市值與信用交易占成交比重 (%)，當年度為截至上個月底
CREATE TABLE IF NOT EXISTS credit_history (
    market          TEXT NOT NULL,
    year            TEXT NOT NULL,
    margin_ratio    REAL,
    credit_ratio    REAL,
    PRIMARY KEY (market, year)
);

-- 總體指標日資料：美元兌台幣、台指 VIX、美國 VIX。
-- 日期為各自市場的交易日，美國 VIX 的日期是美國時間
CREATE TABLE IF NOT EXISTS macro_daily (
    series          TEXT NOT NULL,
    date            TEXT NOT NULL,
    value           REAL NOT NULL,
    PRIMARY KEY (series, date)
);

-- 主動式 ETF 每日持股明細 (由各投信官網取得，日期以其淨值日為準)
CREATE TABLE IF NOT EXISTS etf_holding (
    date            TEXT NOT NULL,
    etf_code        TEXT NOT NULL,
    stock_code      TEXT NOT NULL,
    stock_name      TEXT,
    shares          INTEGER NOT NULL DEFAULT 0,
    weight          REAL,
    PRIMARY KEY (date, etf_code, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_holding_date ON etf_holding(date);
CREATE INDEX IF NOT EXISTS idx_etf_holding_stock ON etf_holding(stock_code);

-- 主動式 ETF 每日規模與淨值，同時記錄該日持股是否成功取得
CREATE TABLE IF NOT EXISTS etf_snapshot (
    date            TEXT NOT NULL,
    etf_code        TEXT NOT NULL,
    issuer          TEXT NOT NULL,
    nav             REAL,
    aum             REAL,
    units           INTEGER,
    holding_count   INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, etf_code)
);

-- 期貨每日行情 (期交所每日交易行情下載)
CREATE TABLE IF NOT EXISTS future_daily (
    date            TEXT NOT NULL,
    commodity       TEXT NOT NULL,   -- 商品代碼，例如 TMF (微型臺指期貨)
    contract_month  TEXT NOT NULL,   -- 到期月份，例如 202610
    session         TEXT NOT NULL,   -- regular (一般) / afterhours (盤後)
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    settlement      REAL,            -- 結算價，盤後時段沒有
    volume          INTEGER NOT NULL DEFAULT 0,
    open_interest   INTEGER,         -- 未沖銷契約數，盤後時段沒有
    PRIMARY KEY (date, commodity, contract_month, session)
);
CREATE INDEX IF NOT EXISTS idx_future_daily_lookup
    ON future_daily(commodity, session, date, contract_month);

-- 分析師共識的年度 EPS 預估 (Yahoo Finance)，每天存一份快照才能累積歷史。
-- Yahoo 只提供今年與明年兩個會計年度，前瞻本益比由收盤價除以這裡的 eps_avg 計算
CREATE TABLE IF NOT EXISTS eps_estimate (
    date            TEXT NOT NULL,     -- 抓取日 YYYYMMDD
    code            TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,  -- 會計年度，取自 Yahoo 的年度結束日
    ticker          TEXT NOT NULL,     -- Yahoo 代號，例如 2330.TW、6488.TWO
    currency        TEXT NOT NULL DEFAULT 'TWD',  -- Yahoo 原始的計價幣別
    fx_rate         REAL NOT NULL DEFAULT 1,      -- 換算台幣的匯率，以下 EPS 都已換成台幣
    eps_avg         REAL,              -- 共識平均 (台幣)
    eps_low         REAL,
    eps_high        REAL,
    analysts        INTEGER,           -- 提供預估的分析師人數
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, code, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_eps_estimate_code ON eps_estimate(code, date);

-- 集保戶股權分散表 (臺灣集中保管結算所)，每週一份，依持股級距列出人數與股數。
-- level 1~15 為持股級距，16 為差異數調整，17 為合計。
-- 開放資料只提供最新一週，過去的週次查不回來，因此每週都要匯入
CREATE TABLE IF NOT EXISTS holder_dist (
    date            TEXT NOT NULL,     -- 資料日 YYYYMMDD (每週最後一個營業日)
    code            TEXT NOT NULL,
    level           INTEGER NOT NULL,
    people          INTEGER NOT NULL,
    shares          INTEGER NOT NULL,
    pct             REAL NOT NULL,     -- 佔集保庫存數比例 (%)
    PRIMARY KEY (date, code, level)
);
CREATE INDEX IF NOT EXISTS idx_holder_dist_code ON holder_dist(code, date);

-- 每日匯入狀態，供重跑與排錯使用
CREATE TABLE IF NOT EXISTS ingest_log (
    date            TEXT NOT NULL,
    market          TEXT NOT NULL,
    status          TEXT NOT NULL,     -- ok / no_data / error
    row_count       INTEGER NOT NULL DEFAULT 0,
    message         TEXT,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, market)
);

-- 永豐 Shioaji 的每日查詢次數。存在資料庫而非記憶體，服務重啟後仍延續當日的計數，
-- 才不會因為重啟歸零而超過官方的每日上限
CREATE TABLE IF NOT EXISTS sino_usage (
    date            TEXT NOT NULL,
    kind            TEXT NOT NULL,     -- kbar (當日分時) / history (歷史日線)
    count           INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (date, kind)
);
"""


def connect():
    """建立資料庫連線。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# 後來才加入的欄位。CREATE TABLE IF NOT EXISTS 不會替既有資料表補欄位，
# 因此另外以 ALTER TABLE 補上。已存在的欄位會被略過，可重複執行。
MIGRATIONS = [
    # 個股開高低。證交所與櫃買的收盤行情本來就含這三欄，改為一併存下來供 K 線圖使用
    ("daily_price", "open", "REAL"),
    ("daily_price", "high", "REAL"),
    ("daily_price", "low", "REAL"),
]


def _apply_migrations(conn):
    for table, column, column_type in MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_schema(conn=None):
    """建立所有資料表並套用欄位異動 (可重複執行)。"""
    own = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA)
        _apply_migrations(conn)
        conn.commit()
    finally:
        if own:
            conn.close()
