/**
 * 大盤籌碼與總體指標的資料整理。
 *
 * 全部是純函式，不碰 DOM 也不碰 Vue。
 */
import type { ChipRow, CreditRow, MarketPayload } from "@/types"

export type MarketKey = "TWSE" | "TPEX"

export const MARKET_LABELS: Record<MarketKey, string> = {
    TWSE: "上市",
    TPEX: "上櫃",
}

/** 籌碼圖可切換的指標 */
export const CHIP_METRICS = [
    { key: "total", label: "法人合計", unit: "億", kind: "net" },
    { key: "foreign", label: "外資", unit: "億", kind: "net" },
    { key: "trust", label: "投信", unit: "億", kind: "net" },
    { key: "dealer", label: "自營商", unit: "億", kind: "net" },
    { key: "margin", label: "融資餘額", unit: "億", kind: "level" },
    { key: "maintenance", label: "融資維持率", unit: "%", kind: "level" },
    { key: "short_units", label: "融券餘額", unit: "張", kind: "level" },
    // 融資餘額占總市值，下方說明另列信用交易占成交比重與年度歷史
    { key: "margin_ratio", label: "融資槓桿", unit: "%", kind: "ratio" },
    // 官方資料只有全市場，切換上市上櫃時都畫同一條
    { key: "calls", label: "追繳處分", unit: "戶", kind: "calls" },
    // 不分上市上櫃，下方同時畫台指與美國 VIX
    { key: "vix", label: "恐慌指標", unit: "VIX", kind: "vix" },
] as const

export type ChipMetric = (typeof CHIP_METRICS)[number]["key"]

export function expandChip(payload: MarketPayload, market: MarketKey): ChipRow[] {
    const fields = payload.chip.fields
    return (payload.chip[market] ?? []).map((row) => {
        const obj: Record<string, unknown> = {}
        fields.forEach((name, index) => {
            obj[name] = row[index]
        })
        return obj as unknown as ChipRow
    })
}

/** 官方全市場信用交易指標，舊版資料檔沒有時回傳空陣列 */
export function expandCredit(payload: MarketPayload): CreditRow[] {
    const credit = payload.credit
    if (!credit) {
        return []
    }
    return credit.items.map((row) => {
        const obj: Record<string, unknown> = {}
        credit.fields.forEach((name, index) => {
            obj[name] = row[index]
        })
        return obj as unknown as CreditRow
    })
}

export interface Latest {
    date: string
    value: number
    /** 與前一筆有值資料的差，只有一筆時為 null */
    diff: number | null
}

/** 某欄位最近一筆有值的資料與前一筆的差。法人與融資公布時間不同，要各自找 */
export function latestOf(rows: ChipRow[], key: keyof ChipRow): Latest | null {
    let found: Latest | null = null
    for (let i = rows.length - 1; i >= 0; i--) {
        const value = rows[i][key]
        if (typeof value !== "number") {
            continue
        }
        if (!found) {
            found = { date: rows[i].date, value, diff: null }
            continue
        }
        found.diff = found.value - value
        break
    }
    return found
}

/** [日期, 值] 序列的最新值 */
export function latestPoint(points: [string, number][] | undefined): Latest | null {
    if (!points?.length) {
        return null
    }
    const [date, value] = points[points.length - 1]
    const prev = points.length > 1 ? points[points.length - 2][1] : null
    return { date, value, diff: prev === null ? null : value - prev }
}

/** VIX 的恐慌門檻，與 vixLevel 一致 */
export const VIX_PANIC = { TW: 32, US: 30 } as const

export interface Level {
    label: string
    /** calm / normal / alert / panic，對應畫面上的色階 */
    tone: "calm" | "normal" | "alert" | "panic"
}

/**
 * VIX 的區間標籤。門檻是常見的經驗值，不是官方定義：
 * 美國 VIX 長期中位數約 17，台指 VIX 平時較高，門檻各自上調。
 */
export function vixLevel(value: number, market: "TW" | "US"): Level {
    const [calm, alert, panic] = market === "US" ? [15, 20, VIX_PANIC.US] : [18, 25, VIX_PANIC.TW]
    if (value >= panic) {
        return { label: "恐慌", tone: "panic" }
    }
    if (value >= alert) {
        return { label: "警戒", tone: "alert" }
    }
    if (value >= calm) {
        return { label: "正常", tone: "normal" }
    }
    return { label: "平靜", tone: "calm" }
}

/**
 * 融資維持率的區間標籤。個股跌破 130% 會被追繳，
 * 全市場平均落到 150% 以下時通常伴隨大量斷頭賣壓，同樣是經驗值。
 */
export function maintenanceLevel(value: number): Level {
    if (value < 150) {
        return { label: "斷頭壓力", tone: "panic" }
    }
    if (value < 160) {
        return { label: "偏低", tone: "alert" }
    }
    if (value < 175) {
        return { label: "中性", tone: "normal" }
    }
    return { label: "偏高", tone: "calm" }
}

/**
 * 官方全市場擔保維持率的分區，取自玉山證券投顧整理的市場實務觀察 (非官方標準)。
 * 原文沒有列 150% 到 160%，這裡當作恐慌與正常之間的過渡帶。
 * 維持率太低是斷頭壓力，太高則是融資浮盈多、獲利了結的壓力，兩端都標成警示色。
 */
export const OFFICIAL_ZONES = [
    { from: 0, to: 150, label: "恐慌", tone: "panic" },
    { from: 150, to: 160, label: "偏低", tone: "alert" },
    { from: 160, to: 180, label: "正常", tone: "normal" },
    { from: 180, to: 190, label: "偏熱", tone: "alert" },
    { from: 190, to: 200, label: "高熱", tone: "alert" },
    { from: 200, to: Infinity, label: "極度樂觀", tone: "panic" },
] as const

export function officialLevel(value: number): Level {
    const zone = OFFICIAL_ZONES.find((item) => value < item.to) ?? OFFICIAL_ZONES[OFFICIAL_ZONES.length - 1]
    return { label: zone.label, tone: zone.tone }
}

export interface SimilarDay {
    date: string
    margin: number
    /** 與今天融資餘額的差 (億)，正值代表當時比今天多 */
    diff: number
    /** 當時的指數收盤 */
    close: number | null
    /** 今天的指數相對當時的漲跌幅 (%) */
    pct: number | null
}

export interface SimilarOptions {
    /** 往回找的交易日數，約三個月 */
    lookback?: number
    /** 排除最近幾個交易日，否則找到的都是昨天前天 */
    skipRecent?: number
    /** 挑幾天 */
    count?: number
    /** 挑出的日期彼此至少相隔幾個交易日 */
    gap?: number
}

/**
 * 找出近期融資餘額最接近今天的幾天，對照當時的指數位置：
 * 同樣的融資水位，當時指數在哪裡，可以看出散戶槓桿與指數是否背離。
 */
export function similarMarginDays(
    rows: ChipRow[],
    closes: Map<string, number>,
    options: SimilarOptions = {},
): { today: Latest; days: SimilarDay[] } | null {
    const { lookback = 63, skipRecent = 5, count = 3, gap = 5 } = options
    const withMargin = rows.filter((row) => typeof row.margin === "number")
    if (withMargin.length <= skipRecent + 1) {
        return null
    }
    const last = withMargin[withMargin.length - 1]
    const today = latestOf(withMargin, "margin")
    if (!today) {
        return null
    }
    const end = withMargin.length - 1 - skipRecent
    const start = Math.max(0, withMargin.length - 1 - lookback)
    const candidates = []
    for (let i = start; i < end; i++) {
        candidates.push({ index: i, distance: Math.abs((withMargin[i].margin as number) - today.value) })
    }
    candidates.sort((a, b) => a.distance - b.distance)

    const picked: number[] = []
    for (const item of candidates) {
        if (picked.every((index) => Math.abs(index - item.index) >= gap)) {
            picked.push(item.index)
        }
        if (picked.length >= count) {
            break
        }
    }
    const todayClose = closes.get(last.date) ?? null
    const days = picked
        .sort((a, b) => a - b)
        .map((index) => {
            const row = withMargin[index]
            const close = closes.get(row.date) ?? null
            return {
                date: row.date,
                margin: row.margin as number,
                diff: (row.margin as number) - today.value,
                close,
                pct: close && todayClose ? (todayClose / close - 1) * 100 : null,
            }
        })
    return { today, days }
}

/* ===== 各指標下方的摘要與對照表 ===== */

export interface Point {
    date: string
    value: number
}

/** 從尾端往回數，最近一筆與之前連續同號的天數；正為連續買超，負為連續賣超 */
export function streak(values: number[]): number {
    if (!values.length) {
        return 0
    }
    const sign = Math.sign(values[values.length - 1])
    if (!sign) {
        return 0
    }
    let count = 0
    for (let i = values.length - 1; i >= 0 && Math.sign(values[i]) === sign; i--) {
        count++
    }
    return count * sign
}

/** 最近 n 筆的合計，資料不足 n 筆時回傳 null，避免把短期合計當成完整區間 */
export function sumLast(values: number[], n: number): number | null {
    if (values.length < n) {
        return null
    }
    return values.slice(-n).reduce((total, value) => total + value, 0)
}

/**
 * 挑出最高或最低的幾天，彼此至少相隔 gap 筆，
 * 否則同一波殺盤的連續幾天會把名額全部占掉。
 */
export function extremeDays(points: Point[], dir: "max" | "min", count = 5, gap = 10): Point[] {
    const order = points
        .map((point, index) => ({ point, index }))
        .sort((a, b) => (dir === "max" ? b.point.value - a.point.value : a.point.value - b.point.value))
    const picked: { point: Point; index: number }[] = []
    for (const item of order) {
        if (picked.every((p) => Math.abs(p.index - item.index) >= gap)) {
            picked.push(item)
        }
        if (picked.length >= count) {
            break
        }
    }
    return picked.map((item) => item.point)
}

/**
 * 某天之後 n 個交易日的指數漲跌幅 (%)。日期不是台股交易日 (例如美股) 時
 * 從下一個台股交易日起算；之後的交易日還不滿 n 天時回傳 null。
 */
export function forwardPct(
    tradingDates: string[],
    closes: Map<string, number>,
    date: string,
    n = 20,
): number | null {
    const start = tradingDates.findIndex((d) => d >= date)
    if (start < 0 || start + n >= tradingDates.length) {
        return null
    }
    const from = closes.get(tradingDates[start])
    const to = closes.get(tradingDates[start + n])
    return from && to ? (to / from - 1) * 100 : null
}

/**
 * 把大盤資料截到某一天 (含) 為止，用來回看過去某天的總覽與籌碼。
 * 各元件都以「最後一筆」當作今天，截掉之後的資料就能直接沿用，不必各自處理日期。
 */
export function marketAsOf(payload: MarketPayload, date: string): MarketPayload {
    const chipDate = payload.chip.fields.indexOf("date")
    const indexDate = payload.tpex_index.fields.indexOf("date")
    const upTo = (rows: (string | number | null)[][], at: number) =>
        rows.filter((row) => String(row[at]) <= date)
    const macro = {} as MarketPayload["macro"]
    for (const [key, points] of Object.entries(payload.macro) as [keyof MarketPayload["macro"], [string, number][]][]) {
        macro[key] = points.filter(([day]) => day <= date)
    }
    const credit = payload.credit && {
        fields: payload.credit.fields,
        items: upTo(payload.credit.items, payload.credit.fields.indexOf("date")),
    }
    return {
        ...payload,
        chip: {
            fields: payload.chip.fields,
            TWSE: upTo(payload.chip.TWSE, chipDate),
            TPEX: upTo(payload.chip.TPEX, chipDate),
        },
        tpex_index: { fields: payload.tpex_index.fields, items: upTo(payload.tpex_index.items, indexDate) },
        macro,
        credit,
    }
}

/**
 * 融資維持率最低的 5 天 (彼此相隔至少 10 個交易日)。
 * 籌碼圖的標記與下方對照表共用，確保圖上圈的就是表上列的那幾天。
 */
export function maintenanceLows(rows: ChipRow[]): Point[] {
    const points = rows
        .filter((row) => typeof row.maintenance === "number")
        .map((row) => ({ date: row.date, value: row.maintenance as number }))
    return extremeDays(points, "min", 5, 10)
}

/**
 * 追繳戶數 (低於 130%) 明顯暴增的日子：最多取 5 天，彼此相隔至少 10 個交易日，
 * 且至少要有最高那天的 30%。平時每天也有一兩百戶，不篩掉的話會把平常日子也標出來。
 * 籌碼圖的標記與下方對照表共用。
 */
export function callPeaks(rows: CreditRow[]): Point[] {
    const points = rows
        .filter((row) => typeof row.below_acc === "number")
        .map((row) => ({ date: row.date, value: row.below_acc as number }))
    const peaks = extremeDays(points, "max", 5, 10)
    const top = peaks[0]?.value ?? 0
    return peaks.filter((point) => point.value >= top * 0.3)
}

export interface VixHigh extends Point {
    market: "TW" | "US"
}

/**
 * 台指與美國 VIX 各自最高的 3 天 (彼此相隔至少 10 筆)，只看 since 之後的資料，
 * 讓美國 VIX 與台股籌碼的期間對齊。籌碼圖標記與下方對照表共用。
 */
export function vixHighs(
    tw: Map<string, number>,
    us: Map<string, number>,
    since: string,
): VixHigh[] {
    const toPoints = (source: Map<string, number>) =>
        [...source]
            .filter(([date]) => date >= since)
            .map(([date, value]) => ({ date, value }))
            .sort((a, b) => a.date.localeCompare(b.date))
    return [
        ...extremeDays(toPoints(tw), "max", 3).map((point) => ({ ...point, market: "TW" as const })),
        ...extremeDays(toPoints(us), "max", 3).map((point) => ({ ...point, market: "US" as const })),
    ].sort((a, b) => a.date.localeCompare(b.date))
}
