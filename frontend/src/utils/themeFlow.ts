/**
 * 題材分類的資料衍生。
 *
 * 與 flow.ts 的產業別版本平行：把當日全部個股依題材分類表 (themes.json)
 * 聚合成題材層的買賣超，並算出區塊組成、下鑽明細與連續買賣超。
 *
 * 題材分類與產業別不同，一檔股票可以同時屬於多個題材，這種個股會全額
 * 計入它出現的每個題材 (目前僅約 9 檔跨題材，影響很小)。輸出刻意沿用
 * IndustryFlow / StreakItem 的形狀 (industry 欄位改放題材名稱)，前端的
 * treemap、排行圖與 tooltip 因此完全不需要改動。
 */
import type {
    AmountField,
    HistoryData,
    IndustryFlow,
    Investor,
    Stock,
    StockFlow,
    StreakItem,
    ThemesData,
} from "@/types"

import { FIELD_OF, buildChildren } from "@/utils/flow"

/** 題材名稱 → 成員代號集合 */
export function themeMembership(themes: ThemesData): Map<string, Set<string>> {
    const membership = new Map<string, Set<string>>()
    for (const theme of themes.themes) {
        const codes = membership.get(theme.name) ?? new Set<string>()
        for (const segment of theme.segments) {
            for (const stock of segment.stocks) {
                codes.add(stock.code)
            }
        }
        membership.set(theme.name, codes)
    }
    return membership
}

/** 依題材分組，一檔股票可同時落在多個題材 */
export function groupByTheme(stocks: Stock[], membership: Map<string, Set<string>>): Record<string, Stock[]> {
    const byCode = new Map<string, Stock>()
    for (const stock of stocks) {
        byCode.set(stock.code, stock)
    }
    const groups: Record<string, Stock[]> = {}
    for (const [theme, codes] of membership) {
        const members: Stock[] = []
        for (const code of codes) {
            const stock = byCode.get(code)
            if (stock) {
                members.push(stock)
            }
        }
        if (members.length) {
            groups[theme] = members
        }
    }
    return groups
}

/** 單一題材成員的四種法人金額與買賣家數彙總，湊出 IndustryFlow 需要的欄位 */
function aggregate(members: Stock[]): {
    total_amt: number
    foreign_amt: number
    trust_amt: number
    dealer_amt: number
    buy_count: number
    sell_count: number
    stock_count: number
} {
    const sum = { total_amt: 0, foreign_amt: 0, trust_amt: 0, dealer_amt: 0 }
    let buy = 0
    let sell = 0
    for (const m of members) {
        sum.total_amt += m.total_amt || 0
        sum.foreign_amt += m.foreign_amt || 0
        sum.trust_amt += m.trust_amt || 0
        sum.dealer_amt += m.dealer_amt || 0
        // 與產業別版本一致，買賣家數以三大法人合計的方向判定
        if (m.total_amt > 0) {
            buy += 1
        } else if (m.total_amt < 0) {
            sell += 1
        }
    }
    return { ...sum, buy_count: buy, sell_count: sell, stock_count: members.length }
}

/** 題材清單，amount 依法人別取對應欄位，並附上同方向前幾名個股 */
export function themeFlow(
    stocks: Stock[],
    themes: ThemesData,
    investor: Investor,
    topStocks = 10,
): IndustryFlow[] {
    const key = FIELD_OF[investor]
    const groups = groupByTheme(stocks, themeMembership(themes))
    return Object.entries(groups)
        .map(([theme, members]) => {
            const agg = aggregate(members)
            const amount = agg[key as keyof typeof agg] as number
            return {
                industry: theme,
                ...agg,
                amount,
                children: buildChildren(members, key, amount, topStocks),
            }
        })
        .sort((a, b) => b.amount - a.amount)
}

/** 單一題材的全部個股，供下鑽檢視使用 */
export function themeStocks(
    stocks: Stock[],
    themes: ThemesData,
    theme: string,
    investor: Investor,
): StockFlow[] {
    const key = FIELD_OF[investor]
    const groups = groupByTheme(stocks, themeMembership(themes))
    return (groups[theme] ?? [])
        .map((m) => ({ ...m, amount: m[key] }))
        .sort((a, b) => b.amount - a.amount)
}

/**
 * 由題材歷史推算各題材的連續買賣超，結構與後端的產業別 streak 一致。
 *
 * 題材歷史本來就要給趨勢圖，streak 直接由它推導，不必另闢後端路徑。
 */
export function themeStreak(history: HistoryData, investor: Investor, days: number): StreakItem[] {
    const key = FIELD_OF[investor]
    const results: StreakItem[] = []
    for (const [theme, points] of Object.entries(history.industries)) {
        // 由新到舊取最近 days 天
        const recent = points.slice(-days).reverse()
        const amounts = recent.map((p) => (p[key as AmountField] as number) || 0)
        if (!amounts.length || amounts[0] === 0) {
            continue
        }
        const direction = amounts[0] > 0 ? 1 : -1
        let streak = 0
        let total = 0
        for (const amount of amounts) {
            if ((amount > 0 && direction > 0) || (amount < 0 && direction < 0)) {
                streak += 1
                total += amount
            } else {
                break
            }
        }
        results.push({
            industry: theme,
            direction: direction > 0 ? "buy" : "sell",
            streak_days: streak,
            total_amt: total,
        })
    }
    results.sort((a, b) => Math.abs(b.total_amt) - Math.abs(a.total_amt))
    return results
}
