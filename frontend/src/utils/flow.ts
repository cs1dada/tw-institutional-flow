/**
 * 類股資金流向的資料衍生。
 *
 * 後端只給當日原始資料 (各類股的四種法人金額 + 全部個股)，
 * 類股組成、個股排行、下鑽明細都由這裡算出來。全部是純函式。
 * 邏輯與舊版 app.js 的「由當日資料衍生出各區塊所需內容」一致。
 */
import type {
    AmountField,
    DayData,
    FlowChild,
    IndustryFlow,
    Investor,
    Stock,
    StockFlow,
} from "@/types"

/** ETF 在類股統計中的虛擬類別名稱 */
export const ETF_GROUP = "ETF"

/** 主動式 ETF 的代號規則：00 開頭、A 結尾 */
export const ACTIVE_ETF_RE = /^00\d{3}A$/

/** 類股趨勢圖顯示的交易日數 */
export const TREND_DAYS = 20
/** 類股區塊內切分出的個股檔數上限 */
export const TOP_STOCKS = 10
/** 資金規模最大的前幾個類股，區塊夠大可切較多檔 */
export const LARGE_INDUSTRIES = 6
export const LARGE_TOP_STOCKS = 10
/** 其餘區塊切分的個股檔數，避免切得太碎 */
export const SMALL_TOP_STOCKS = 5
/** 只對資金規模最大的前幾個類股切分個股 */
export const SPLIT_INDUSTRIES = 14
/** 類股 tooltip 內列出的個股檔數 */
export const TOOLTIP_STOCKS = 5
/** 「其他」格子最多佔類股區塊面積的比例 */
export const OTHER_MAX_RATIO = 0.1

export const INVESTOR_LABELS: Record<Investor, string> = {
    all: "三大法人",
    foreign: "外資",
    trust: "投信",
    dealer: "自營商",
}

export const FIELD_OF: Record<Investor, AmountField> = {
    all: "total_amt",
    foreign: "foreign_amt",
    trust: "trust_amt",
    dealer: "dealer_amt",
}

export const MARKET_LABELS: Record<string, string> = { TWSE: "上市", TPEX: "上櫃" }

/** 個股以陣列形式傳來以節省體積，用到時才轉成物件 */
export function expandStocks(day: DayData): Stock[] {
    return day.stocks.map((row) => {
        const obj: Record<string, unknown> = {}
        day.stock_fields.forEach((name, index) => {
            obj[name] = row[index]
        })
        return obj as unknown as Stock
    })
}

export function groupByIndustry(stocks: Stock[]): Record<string, Stock[]> {
    const groups: Record<string, Stock[]> = {}
    for (const stock of stocks) {
        ;(groups[stock.industry] ??= []).push(stock)
    }
    return groups
}

/** 取同方向金額最大的前幾檔，其餘合併為一項 */
export function buildChildren(
    members: Stock[],
    key: AmountField,
    amount: number,
    limit: number,
): FlowChild[] {
    if (!amount) {
        return []
    }
    const sameDirection = members
        .filter((m) => m[key] && m[key] > 0 === amount > 0)
        .sort((a, b) => Math.abs(b[key]) - Math.abs(a[key]))

    const leaders = sameDirection.slice(0, limit)
    const rest = sameDirection.slice(limit)
    const children: FlowChild[] = leaders.map((m) => ({
        code: m.code,
        name: m.name,
        market: m.market,
        close: m.close,
        amount: m[key],
        is_other: false,
    }))
    if (rest.length) {
        children.push({
            code: null,
            name: `其他 ${rest.length} 檔`,
            market: null,
            close: null,
            amount: rest.reduce((acc, m) => acc + m[key], 0),
            count: rest.length,
            is_other: true,
        })
    }
    return children
}

/** 類股清單，amount 依法人別取對應欄位，並附上同方向前幾名個股 */
export function industryFlow(
    day: DayData,
    stocks: Stock[],
    investor: Investor,
    includeEtf: boolean,
    topStocks = TOP_STOCKS,
): IndustryFlow[] {
    const key = FIELD_OF[investor]
    const groups = groupByIndustry(stocks)
    return day.industries
        .filter((row) => includeEtf || row.industry !== ETF_GROUP)
        .map((row) => {
            const amount = row[key] || 0
            return {
                ...row,
                amount,
                children: buildChildren(groups[row.industry] ?? [], key, amount, topStocks),
            }
        })
        .sort((a, b) => b.amount - a.amount)
}

/** 單一類股的全部個股，供下鑽檢視使用 */
export function industryStocks(
    stocks: Stock[],
    industry: string,
    investor: Investor,
): StockFlow[] {
    const key = FIELD_OF[investor]
    return (groupByIndustry(stocks)[industry] ?? [])
        .map((m) => ({ ...m, amount: m[key] }))
        .sort((a, b) => b.amount - a.amount)
}

/** 個股買超或賣超排行，不含 ETF */
export function stockRanking(
    stocks: Stock[],
    investor: Investor,
    side: "buy" | "sell",
    limit: number,
): StockFlow[] {
    const key = FIELD_OF[investor]
    const rows = stocks
        .filter((m) => !m.is_etf)
        .map((m) => ({ ...m, amount: m[key] }))
        .sort((a, b) => b.amount - a.amount)
    return side === "buy" ? rows.slice(0, limit) : rows.slice(-limit).reverse()
}

/** 主動式 ETF 自身的法人買賣超 */
export function etfFlowList(stocks: Stock[], investor: Investor): StockFlow[] {
    const key = FIELD_OF[investor]
    return stocks
        .filter((m) => ACTIVE_ETF_RE.test(m.code))
        .map((m) => ({ ...m, amount: m[key] }))
        .sort((a, b) => b.amount - a.amount)
}

/**
 * 依上限取該類股的前幾檔個股，其餘 (含已合併的部分) 重新併為一項。
 *
 * 類股區塊太小時個股會被切得太碎，因此依資金規模決定每個類股切幾檔。
 */
export function limitChildren(row: IndustryFlow, limit: number | undefined): FlowChild[] | null {
    if (!limit || !row.children?.length) {
        return null
    }
    const named = row.children.filter((kid) => !kid.is_other)
    const merged = row.children.filter((kid) => kid.is_other)
    const kept = named.slice(0, limit)
    const dropped = named.slice(limit)

    let restAmount = dropped.reduce((acc, kid) => acc + kid.amount, 0)
    let restCount = dropped.length
    for (const kid of merged) {
        restAmount += kid.amount
        restCount += kid.count ?? 0
    }
    // 沒有剩餘項目才不顯示「其他」；檔數取不到時仍保留這一格
    if (!dropped.length && !merged.length) {
        return kept
    }
    // 具名個股依面積由大到小，「其他」固定放在最後，版面上會落在右下角
    kept.sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
    return [
        ...kept,
        {
            code: null,
            name: restCount ? `其他 ${restCount} 檔` : "其他",
            market: null,
            close: null,
            amount: restAmount,
            count: restCount,
            is_other: true,
        },
    ]
}

/** 各類股在 treemap 中要切出幾檔個股 */
export function splitLimits(items: IndustryFlow[]): Record<string, number> {
    const limits: Record<string, number> = {}
    items
        .slice()
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
        .slice(0, SPLIT_INDUSTRIES)
        .forEach((row, index) => {
            limits[row.industry] = index < LARGE_INDUSTRIES ? LARGE_TOP_STOCKS : SMALL_TOP_STOCKS
        })
    return limits
}

/** 資料是否只收錄到單一市場 */
export function marketNote(item: { markets: string[]; complete: boolean } | undefined): string {
    if (!item || item.complete) {
        return ""
    }
    const names = item.markets.map((market) => MARKET_LABELS[market] ?? market)
    return names.length ? `僅${names.join("、")}` : "無資料"
}
