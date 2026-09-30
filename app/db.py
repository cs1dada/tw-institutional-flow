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
