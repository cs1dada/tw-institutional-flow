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
    /** 主動式 ETF 截至當日的持股變動；舊版匯出的檔案沒有這個欄位 */
    etf_changes?: EtfChange[]
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
    /** 該 ETF 的最新快照日 */
    date: string
    /** 比對的前一個快照日 */
    prev_date: string
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

/* ------------------------------------------------------------------ */
/* 個股即時行情                                                        */
/* ------------------------------------------------------------------ */

/** 五檔的單一檔位 */
export interface QuoteLevel {
    price: number
    size: number
}

/** 微型臺指期貨 (來源為期交所) */
export interface QuoteFuture {
    code: string
    name: string
    price: number | null
    prev_close: number | null
    change: number | null
    pct: number | null
    open: number | null
    high: number | null
    low: number | null
    /** 成交口數 */
    volume: number | null
    bids: QuoteLevel[]
    asks: QuoteLevel[]
    /** 尚未開盤時顯示的是試撮價 */
    trial: boolean
    time: string
}

/** 加權指數 (來源為富果)，成交統計為全市場合計 */
export interface QuoteIndex {
    code: string
    name: string
    price: number | null
    prev_close: number | null
    change: number | null
    pct: number | null
    open: number | null
    high: number | null
    low: number | null
    /** 全市場成交金額 (元) */
    amount: number | null
    /** 全市場成交張數 */
    volume: number | null
    transaction: number | null
    time: string
}

export interface QuoteOverview {
    future: QuoteFuture | null
    index: QuoteIndex | null
    /** 期現價差：期貨減現貨，正值為正價差 */
    basis: number | null
    /** 是否在期貨交易時段 */
    session: boolean
    updated_at: string
    /** 取得失敗時沿用前一份資料，此旗標為 true */
    stale: boolean
    error: string | null
}

export interface QuoteStock {
    code: string
    name: string
    price: number | null
    prev_close: number | null
    change: number | null
    pct: number | null
    open: number | null
    high: number | null
    low: number | null
    avg: number | null
    amplitude: number | null
    /** 成交張數 */
    volume: number | null
    /** 成交金額 (元) */
    amount: number | null
    transaction: number | null
    /** 內盤量：以買方掛價成交 */
    at_bid: number
    /** 外盤量：以賣方掛價成交 */
    at_ask: number
    bids: QuoteLevel[]
    asks: QuoteLevel[]
    /** 盤中為 true，盤前試撮與收盤後為 false */
    continuous: boolean
    time: string
}

/** 當日分時 K 線的單一根 */
export interface QuoteCandle {
    time: string
    close: number
    volume: number
    average: number
}

export interface QuoteStockData {
    quote: QuoteStock
    candles: QuoteCandle[]
    updated_at: string
    stale: boolean
    error: string | null
}

export interface QuoteSearchItem {
    code: string
    name: string
    market: string
    industry: string
}

/* ------------------------------------------------------------------ */
/* 永豐 Shioaji 即時行情                                               */
/* ------------------------------------------------------------------ */

/** Shioaji 快照。期貨、指數與個股共用同一組欄位，缺的為 null */
export interface SinoSnapshot {
    code: string
    price: number | null
    change: number | null
    pct: number | null
    open: number | null
    high: number | null
    low: number | null
    avg: number | null
    /** 個股為張、期貨為口；指數為全市場成交張數 */
    volume: number | null
    /** 成交金額 (元)；指數為全市場合計 */
    amount: number | null
    /** 最佳一檔。五檔需要另外訂閱串流，這一頁不做 */
    bid: number | null
    ask: number | null
    bid_volume: number | null
    ask_volume: number | null
    /** 與昨日同時間的量能比，大於 1 代表今天量放大 */
    volume_ratio: number | null
    yesterday_volume: number | null
    time: string
}

export interface SinoCandle {
    time: string
    close: number
    volume: number
}

/** 訂閱中的期貨某一個交易時段的分時 */
export interface SinoSession {
    kind: "day" | "night"
    label: string
    start: string
    end: string
    candles: SinoCandle[]
}

export interface SinoQuoteData {
    future: SinoSnapshot | null
    /** 常駐期貨的名稱，由後端設定決定 */
    future_name: string
    index: SinoSnapshot | null
    stock: SinoSnapshot | null
    stock_name: string | null
    /** 期現價差：期貨減現貨，正值為正價差 */
    basis: number | null
    candles: SinoCandle[]
    /** 常駐期貨是否由逐筆成交即時更新；false 時為 10 秒一次的快照 */
    future_streaming: boolean
    /** 選定的是訂閱中的期貨時，最近的日盤與夜盤，依時間先後排列 */
    sessions: SinoSession[] | null
    /** 目前所在的時段，作為預設顯示 */
    current_session: "day" | "night" | null
    updated_at: string
    stale: boolean
    error: string | null
}

export interface SinoUsage {
    connections: number
    used_mb: number
    limit_mb: number
    percent: number
    /** 這一頁自己的 K 線用量，與官方流量分開計算 */
    kbar_used: number
    kbar_limit: number
}

export interface SinoSearchItem {
    code: string
    name: string
    exchange: string
}

/**
 * 個股歷史日線。格式與 IndexPayload 相同，可共用聚合工具。
 *
 * 兩個來源共用這個型別：本機資料庫 (source 為 db) 與行情 API，
 * 前者不消耗任何額度，是優先選擇。
 */
export interface StockHistory {
    code: string
    name: string | null
    /** TWSE / TPEX / TAIFEX。期貨的價格軸與成交量單位與個股不同 */
    market?: string | null
    months: number
    fields: string[]
    items: (string | number | null)[][]
    /** 資料庫來源會附上涵蓋範圍，供呼叫端判斷夠不夠用 */
    earliest?: string | null
    latest?: string | null
    source?: string
    updated_at?: string
    /** 成交量副圖的軸名與單位。個股是成交金額（億），期貨是成交量（口） */
    turnover_label?: string
    turnover_unit?: string
}

/** 個股走勢圖的週期。intraday 為當日分時，其餘沿用指數頁的 Period */
export type SinoPeriod = "intraday" | Period

/* ===== 經理人成本 ===== */

export interface EtfCostItem {
    code: string
    name: string | null
    industry: string | null
    close: number | null
    /** 最新一日仍持有的 ETF 檔數 */
    holders: number
    /** 觀察期間內有買進的 ETF 檔數 */
    buyers: number
    buy_count: number
    buy_shares: number
    buy_amt: number
    sell_amt: number
    /** 全體庫存的加權持倉成本 */
    cost: number | null
    /** 等權共識價 */
    equal: number | null
    /** 資金加權共識價 */
    weighted: number | null
    /** 共識價帶：各家買進均價的 25% 到 75% 分位 */
    band: [number, number] | null
}

export interface EtfCostSummary {
    date: string
    start: string
    days: number
    etfs: { etf_code: string; etf_name: string | null }[]
    daily: { date: string; buy_amt: number; sell_amt: number }[]
    items: EtfCostItem[]
}

export interface EtfCostDetail {
    code: string
    name: string | null
    dates: string[]
    close: (number | null)[]
    /** 各 ETF 的持倉成本線，未持有的日子為 null */
    cost_lines: Record<string, (number | null)[]>
    overall_cost: (number | null)[]
    trade_fields: string[]
    /** [日期, ETF 代號, 股數 (正為買進), 推估成交價] */
    trades: [string, string, number, number][]
    /** 偵測到的分割、股票股利、減資 */
    events: { date: string; factor: number }[]
    consensus: {
        buyer_avg: Record<string, number>
        equal: number
        weighted: number
        band: [number, number]
    } | null
}

/** ETF 每日榜單：單一 ETF 對某檔股票的當日變動 */
export interface EtfDailyTrade {
    etf_code: string
    /** 股數變化，正為買進 */
    shares: number
    /** 以當日 VWAP 推估的金額，正為買進 */
    amount: number
    type: "new" | "add" | "reduce" | "removed"
}

/** 被買最兇 / 被賣最重的一列 */
export interface EtfDailySideRow {
    code: string
    name: string | null
    industry: string | null
    close: number | null
    vwap: number | null
    /** 出手的 ETF 檔數 */
    etf_count: number
    /** 其中新進 (或出清) 的檔數 */
    new_count: number
    shares: number
    amount: number
    /** 同一天反方向的檔數與金額，用來看分歧 */
    opposite_count: number
    opposite_amount: number
    /** 全市場外資、投信買賣超張數 */
    foreign_lots: number | null
    trust_lots: number | null
    etfs: EtfDailyTrade[]
}

/** 最擁擠的一列 */
export interface EtfDailyCrowdedRow {
    code: string
    name: string | null
    industry: string | null
    close: number | null
    holders: number
    /** 前一個交易日的持有檔數 */
    prev_holders: number
    shares: number
    market_value: number | null
    foreign_lots: number | null
    trust_lots: number | null
    etfs: string[]
}

export interface EtfDailyData {
    date: string
    etfs: { etf_code: string; etf_name: string | null; reported: boolean; prev_date: string | null }[]
    buy_amt: number
    sell_amt: number
    buys: EtfDailySideRow[]
    sells: EtfDailySideRow[]
    crowded: EtfDailyCrowdedRow[]
}

export interface EtfDailyDateItem {
    date: string
    /** 當日已公布、可比對的 ETF 檔數 */
    reported: number
    /** 當日已上市的 ETF 檔數 */
    listed: number
}

export interface EtfDailyDates {
    dates: EtfDailyDateItem[]
}

/* ===== ETF 日報 ===== */

/** 日報中的個股列，金額單位為億元，賣出為負數 */
export interface EtfReportStockRow {
    code: string
    name: string | null
    industry: string | null
    buy_count: number
    buy_amt: number
    sell_count: number
    sell_amt: number
    net_amt: number
    buy_etfs: string[]
    sell_etfs: string[]
    /** 共識升溫或退潮：前一個揭露日的加碼家數與差異 */
    prev_buy_count?: number
    diff?: number
    /** 訊號分級 */
    grade?: EtfReportGrade
}

export type EtfReportGrade = "broad" | "concentrated" | "quiet" | "sync_sell" | "heavy_sell"

export interface EtfReportStockRef {
    code: string
    name: string | null
    industry: string | null
}

export interface EtfReportIndustryRow {
    industry: string
    buy_amt: number
    sell_amt: number
    net_amt: number
    stock_count: number
    leaders: (EtfReportStockRef & { net_amt: number })[]
}

/** 新進或清倉的一筆 */
export interface EtfReportPositionRow extends EtfReportStockRef {
    etf_code: string
    lots: number
    amt: number
}

export interface EtfReportAccuracyRow {
    etf_code: string
    etf_name: string | null
    buy_amt: number
    return_pct: number
    stock_count: number
    top_stocks: (EtfReportStockRef & { amt: number })[]
}

/** 校正前或校正後的一組統計 */
export interface EtfReportMode {
    buy_amt: number
    sell_amt: number
    net_amt: number
    top_buys: EtfReportStockRow[]
    top_sells: EtfReportStockRow[]
    consensus_buys: EtfReportStockRow[]
    consensus_sells: EtfReportStockRow[]
    industries: EtfReportIndustryRow[]
    warming: EtfReportStockRow[]
    cooling: EtfReportStockRow[]
    new_positions: EtfReportPositionRow[]
    new_count: number
    exits: EtfReportPositionRow[]
    exit_count: number
    signals: EtfReportStockRow[]
    accuracy: { days: number; from: string; items: EtfReportAccuracyRow[] }
}

export interface EtfReportEtf {
    etf_code: string
    etf_name: string | null
    reported: boolean
    prev_date: string | null
    unit_change_pct?: number | null
    /** 持股整批同比例變動的倍率，1 表示沒有被動買賣 */
    passive_factor?: number
    raw_net_amt?: number
    active_net_amt?: number
    passive_amt?: number
}

export interface EtfReportData {
    date: string
    prev_date: string | null
    thresholds: { big_amount_yi: number; consensus_count: number; accuracy_days: number }
    grades: Record<EtfReportGrade, string>
    etfs: EtfReportEtf[]
    modes: { adjusted: EtfReportMode; raw: EtfReportMode }
    /** 深度解讀的 Markdown 原文 */
    note: string | null
}

export interface EtfReportDateItem extends EtfDailyDateItem {
    has_note: boolean
}

export interface EtfReportDates {
    dates: EtfReportDateItem[]
}
