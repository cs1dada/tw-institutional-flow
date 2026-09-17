/**
 * 後端回傳的資料結構。
 *
 * 型別對應 app/services/dataset.py 的輸出，兩種模式 (API 與靜態 JSON)
 * 格式完全相同，因此共用同一組定義。
 */

/** 法人別。對應後端的 total_amt / foreign_amt / trust_amt / dealer_amt 欄位 */
export type Investor = "all" | "foreign" | "trust" | "dealer"

/** 金額欄位名稱 */
export type AmountField = "total_amt" | "foreign_amt" | "trust_amt" | "dealer_amt"

/** 交易日與該日已收錄的市場，用於標示資料是否齊全 */
export interface DateItem {
    date: string
    markets: string[]
    complete: boolean
}

export interface Meta {
    dates: DateItem[]
    supported_etfs: string[]
    latest_date: string | null
    /** 資料產生時間，同時作為靜態檔的版本號 */
    generated_at: string
}

/** 單一類股的四種法人金額彙總 */
export interface Industry {
    industry: string
    total_amt: number
    foreign_amt: number
    trust_amt: number
    dealer_amt: number
    buy_count: number
    sell_count: number
    stock_count: number
}

/** 個股在前端展開後的樣子。後端以陣列傳輸，欄位名只寫一次 */
export interface Stock {
    code: string
    name: string
    market: string
    industry: string
    is_etf: number
    close: number | null
    total_amt: number
    foreign_amt: number
    trust_amt: number
    dealer_amt: number
}

export interface StreakItem {
    industry: string
    direction: "buy" | "sell"
    streak_days: number
    total_amt: number
}

export interface DayData {
    date: string
    industries: Industry[]
    stock_fields: string[]
    stocks: (string | number | null)[][]
    streak: Record<AmountField, StreakItem[]>
    streak_days: number
}

/** 類股在前端算出 amount (依法人別) 之後的樣子 */
export interface IndustryFlow extends Industry {
    /** 依目前法人別取出的金額 */
    amount: number
    /** 同方向金額最大的前幾檔個股，最後一項可能是合併的「其他」 */
    children: FlowChild[]
}

/** treemap 裡類股區塊內的個股節點 */
export interface FlowChild {
    code: string | null
    name: string
    market: string | null
    close: number | null
    amount: number
    is_other: boolean
    /** 合併項涵蓋的檔數 */
    count?: number
    /** 所屬類股，下鑽與 tooltip 用 */
    industry?: string
    /** 面積被上限截斷 (實際佔比更高) */
    areaCapped?: boolean
}

/** 個股加上依法人別取出的金額 */
export interface StockFlow extends Stock {
    amount: number
}

/** 各類股近 N 個交易日的趨勢 */
export interface HistoryData {
    dates: string[]
    industries: Record<string, HistoryPoint[]>
}

export interface HistoryPoint {
    date: string
    total_amt: number
    foreign_amt: number
    trust_amt: number
    dealer_amt: number
}

/* ===== 盤中觀察 ===== */

export interface IntradayIndex {
    code: string
    name: string
    market: string
    value: number
    prev_close: number
    diff: number
    pct: number
    /** 該市場個股加總的成交金額 (元) */
    amount: number
    /** 成交張數 */
    volume: number
    trades: number
    time: string
}

export interface IntradayIndustry {
    industry: string
    amount: number
    up_amount: number
    down_amount: number
    up_count: number
    down_count: number
    flat_count: number
    stock_count: number
    /** 以成交金額加權的漲跌幅 */
    weighted_pct: number
}

export interface IntradayStock {
    code: string
    name: string
    market: string
    industry: string
    price: number
    pct: number
    amount: number
    volume: number
}

export interface IntradayData {
    date: string
    updated_at: string
    quote_time: string
    trading: boolean
    indexes: IntradayIndex[]
    industries: IntradayIndustry[]
    stock_fields: string[]
    stocks: (string | number)[][]
    scanned: number
    quoted: number
    failed_batches: number
    elapsed: number
    cached: boolean
    age: number
    /** 來源忙碌時沿用前一份資料 */
    stale: boolean
}

/* ===== 主動式 ETF ===== */

export interface EtfSnapshot {
    date: string
    etf_code: string
    etf_name: string | null
    issuer: string | null
    nav: number | null
    aum: number | null
    units: number | null
    holding_count: number
}

export interface EtfHolding {
    date: string
    etf_code: string
    stock_code: string
    stock_name: string | null
    shares: number | null
    weight: number | null
    close: number | null
}

export interface EtfTopStock {
    stock_code: string
    stock_name: string | null
    etf_count: number
    total_shares: number | null
    market_value: number | null
    industry: string | null
}

export interface EtfChange {
    etf_code: string
    stock_code: string
    stock_name: string | null
    shares: number
    prev_shares: number
    share_change: number
    value_change: number | null
    change_type: "new" | "removed" | "changed"
}

export interface EtfData {
    etfs: EtfSnapshot[]
    holdings: EtfHolding[]
    top_stocks: EtfTopStock[]
    changes: EtfChange[]
    dates: string[]
}

/* ===== 大盤指數 ===== */

/** 指數日線，後端以陣列傳輸，fields 說明各欄位順序 */
export interface IndexPayload {
    index_code: string
    name: string
    fields: string[]
    items: (string | number | null)[][]
}

/** 展開後的單日指數 */
export interface IndexRow {
    date: string
    open: number
    high: number
    low: number
    close: number
    /** 成交金額，單位為億元 */
    turnover: number
    change: number | null
}

/** K 線週期 */
export type Period = "daily" | "weekly" | "monthly"

/**
 * 聚合後的一根 K 棒。日線為一日一根，週線與月線由日線聚合而成：
 * 開盤取期初、收盤取期末、高低取極值、成交金額加總。
 */
export interface Bar {
    /** 所屬期間的代碼：日線為日期、週線為當週週一、月線為年月 */
    key: string
    label: string
    /** 期末日期 */
    date: string
    /** 期初日期 */
    start_date: string
    open: number
    high: number
    low: number
    close: number
    turnover: number
    /** 這根 K 棒涵蓋幾個交易日 */
    days: number
    /** 與前一根收盤價的差，第一根為 null */
    diff: number | null
    pct: number | null
}

/** 區間的起訖日 (YYYYMMDD) */
export interface Bounds {
    from: string
    to: string
}

/** 區間對應到的 K 棒索引 */
export interface ZoomRange {
    start: number
    end: number
}
