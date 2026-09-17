/**
 * 指數 K 棒的聚合與計算。
 *
 * 全部是純函式，不碰 DOM 也不碰 Vue，方便單獨驗證。
 * 邏輯與舊版 app.js 的「大盤指數 K 線」區塊一致。
 */
import type { Bar, Bounds, IndexPayload, IndexRow, Period, ZoomRange } from "@/types"
import { formatDate } from "./format"

export const PERIOD_LABELS: Record<Period, string> = {
    daily: "日線",
    weekly: "週線",
    monthly: "月線",
}

/** 各週期的均線參數：日線為 5/20/60 日，週線約當季線與半年線，月線為半年到兩年 */
export const PERIOD_MA: Record<Period, number[]> = {
    daily: [5, 20, 60],
    weekly: [5, 13, 26],
    monthly: [6, 12, 24],
}

/** 區間快捷，months 為 null 表示全部資料 */
export const RANGE_PRESETS = [
    { key: "3m", label: "3 月", months: 3 },
    { key: "6m", label: "6 月", months: 6 },
    { key: "1y", label: "1 年", months: 12 },
    { key: "3y", label: "3 年", months: 36 },
    { key: "5y", label: "5 年", months: 60 },
    { key: "all", label: "全部", months: null },
] as const

export type RangeKey = (typeof RANGE_PRESETS)[number]["key"] | "custom"

/** 切換週期時套用的預設區間，K 棒數量才不會過少或過密 */
export const DEFAULT_RANGE: Record<Period, RangeKey> = {
    daily: "1y",
    weekly: "3y",
    monthly: "all",
}

/** 指數日線以陣列傳來，展開成物件 */
export function expandRows(payload: IndexPayload): IndexRow[] {
    return (payload.items ?? []).map((row) => {
        const obj: Record<string, unknown> = {}
        payload.fields.forEach((name, index) => {
            obj[name] = row[index]
        })
        return obj as unknown as IndexRow
    })
}

/** 該交易日所屬期間的代碼：週線取當週週一，月線取當月 */
export function periodKey(dateStr: string, period: Period): string {
    if (period === "monthly") {
        return dateStr.slice(0, 6)
    }
    const day = new Date(
        +dateStr.slice(0, 4),
        +dateStr.slice(4, 6) - 1,
        +dateStr.slice(6, 8),
    )
    // getDay() 以週日為 0，往回推到當週的週一
    day.setDate(day.getDate() - ((day.getDay() + 6) % 7))
    const month = `0${day.getMonth() + 1}`.slice(-2)
    const date = `0${day.getDate()}`.slice(-2)
    return `${day.getFullYear()}${month}${date}`
}

/** 日線聚合為週線或月線：開盤取期初、收盤取期末、高低取極值、成交金額加總 */
export function aggregate(rows: IndexRow[], period: Period): Bar[] {
    if (period === "daily") {
        return rows.map((row) => ({
            key: row.date,
            label: formatDate(row.date),
            date: row.date,
            start_date: row.date,
            open: row.open,
            high: row.high,
            low: row.low,
            close: row.close,
            turnover: row.turnover || 0,
            days: 1,
            diff: null,
            pct: null,
        }))
    }

    const bars: Bar[] = []
    let current: Bar | null = null
    for (const row of rows) {
        const key = periodKey(row.date, period)
        if (!current || current.key !== key) {
            current = {
                key,
                label: "",
                date: row.date,
                start_date: row.date,
                open: row.open,
                high: row.high,
                low: row.low,
                close: row.close,
                turnover: row.turnover || 0,
                days: 1,
                diff: null,
                pct: null,
            }
            bars.push(current)
            continue
        }
        current.date = row.date
        current.high = Math.max(current.high, row.high)
        current.low = Math.min(current.low, row.low)
        current.close = row.close
        current.turnover += row.turnover || 0
        current.days += 1
    }

    for (const bar of bars) {
        bar.label = period === "monthly"
            ? `${bar.key.slice(0, 4)}-${bar.key.slice(4, 6)}`
            : formatDate(bar.start_date)
    }
    return bars
}

/** 漲跌一律以前一根 K 棒的收盤價計算，三種週期的定義才會一致 */
export function withChange(bars: Bar[]): Bar[] {
    bars.forEach((bar, index) => {
        const prev = index > 0 ? bars[index - 1].close : null
        bar.diff = prev === null ? null : bar.close - prev
        bar.pct = prev ? ((bar.close - prev) / prev) * 100 : null
    })
    return bars
}

/** 移動平均，資料不足的前幾根以 "-" 表示，ECharts 會自動留白 */
export function movingAverage(bars: Bar[], size: number): (number | string)[] {
    const values: (number | string)[] = []
    let sum = 0
    bars.forEach((bar, index) => {
        sum += bar.close
        if (index >= size) {
            sum -= bars[index - size].close
        }
        values.push(index >= size - 1 ? +(sum / size).toFixed(2) : "-")
    })
    return values
}

/** 區間換算出的起訖日 (YYYYMMDD)，rows 為由舊到新的日線 */
export function rangeBounds(
    rows: IndexRow[],
    range: RangeKey,
    from: string | null,
    to: string | null,
): Bounds {
    const first = rows[0].date
    const last = rows[rows.length - 1].date
    if (range === "custom") {
        const start = from || first
        const end = to || last
        return start <= end ? { from: start, to: end } : { from: end, to: start }
    }
    const preset = RANGE_PRESETS.find((item) => item.key === range)
    if (!preset || !preset.months) {
        return { from: first, to: last }
    }
    const day = new Date(+last.slice(0, 4), +last.slice(4, 6) - 1, +last.slice(6, 8))
    day.setMonth(day.getMonth() - preset.months)
    const month = `0${day.getMonth() + 1}`.slice(-2)
    const date = `0${day.getDate()}`.slice(-2)
    return { from: `${day.getFullYear()}${month}${date}`, to: last }
}

/** 區間對應到的 K 棒索引。K 棒本身仍是全部資料，均線才不會在區間起點斷頭 */
export function visibleRange(bars: Bar[], bounds: Bounds): ZoomRange {
    let start = bars.length - 1
    for (let i = 0; i < bars.length; i++) {
        if (bars[i].date >= bounds.from) {
            start = i
            break
        }
    }
    let end = start
    for (let j = bars.length - 1; j >= start; j--) {
        if (bars[j].start_date <= bounds.to) {
            end = j
            break
        }
    }
    return { start, end }
}
