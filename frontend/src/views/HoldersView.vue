<script setup lang="ts">
/**
 * 籌碼分布：股票這一週流向大戶還是散戶。
 *
 * 三大法人以外的買賣沒有官方每日統計，集保每週的股權分散表是少數看得到
 * 「誰在接手」的公開資料。頁面只看兩個數字：股東人數 (散戶進出) 與千張大戶比例 (大戶收或賣)，
 * 其餘級距收在點開後的明細。
 *
 * 集保依身分歸戶，外資、投信、ETF 的帳戶各算一人，多半落在千張大戶，因此千張大戶包含法人。
 */
import { computed, nextTick, onMounted, ref, watch } from "vue"

import { loadHolders, loadHoldersAnalysis, loadHoldersStock, loadHoldersWeek, loadThemes } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import HoldersLevelChart from "@/components/HoldersLevelChart.vue"
import HoldersScatter from "@/components/HoldersScatter.vue"
import HoldersThemeFlowChart from "@/components/HoldersThemeFlowChart.vue"
import HoldersThemeHeatmap from "@/components/HoldersThemeHeatmap.vue"
import HoldersTrendChart from "@/components/HoldersTrendChart.vue"
import type { HoldersAnalysis, HoldersBacktestRow, HoldersRow, HoldersStock, HoldersWeek, ThemesData } from "@/types"
import { formatDate, signed, signedPct } from "@/utils/format"

type Board = "big_up" | "big_down" | "retail_in" | "retail_out" | "streak_up" | "non_inst" | "mid_up"
type Scope = "theme" | "all"
type Period = 1 | 4 | 12

const BOARD_LABELS: Record<Board, string> = {
    big_up: "大戶在收",
    big_down: "大戶在賣",
    retail_in: "散戶湧入",
    retail_out: "散戶離開",
    streak_up: "連續在收",
    non_inst: "非法人大戶在收",
    mid_up: "中實戶在收",
}

const BOARD_NOTES: Record<Board, string> = {
    big_up: "千張大戶比例上升最多的個股，股票往大戶手上集中。比例只看集中程度，不代表買進金額大",
    big_down: "千張大戶比例下降最多的個股，大戶 (含外資、投信) 在賣",
    retail_in: "股東人數增加最多 (%) 的個股，散戶進場，常見於急跌後的承接",
    retail_out: "股東人數減少最多 (%) 的個股，散戶離開，股票往少數人手上集中",
    streak_up: "千張大戶比例連續 3 週以上增加的個股，比單週大增更穩定",
    non_inst: "千張大戶持股增加，但同期三大法人合計賣超，代表買的是法人以外的大戶 (本土大戶、公司派等)",
    mid_up: "400~1000 張中實戶佔股份上升的個股。千張大戶混了許多法人帳戶，這一層比較接近主力",
}

/** 只看單週資料的排行，切到 4 週、12 週時不顯示 */
const WEEKLY_ONLY_BOARDS: Board[] = ["non_inst", "mid_up"]

const PERIOD_LABELS: Record<Period, string> = { 1: "1 週", 4: "4 週", 12: "12 週" }

/**
 * 各比較期間的門檻：千張大戶比例變化 (百分點) 與股東人數變化 (%)。
 * 期間越長變化越大，門檻跟著放寬，否則 12 週時大半個股都會被列入。
 */
const PERIOD_THRESHOLDS: Record<Period, { big: number; retailIn: number; retailOut: number }> = {
    1: { big: 0.5, retailIn: 3, retailOut: -1.5 },
    4: { big: 1, retailIn: 6, retailOut: -3 },
    12: { big: 2, retailIn: 12, retailOut: -6 },
}

/** 連續增加達這個週數才列入「連續在收」 */
const STREAK_MIN = 3
/** 中實戶佔股份一週上升超過這個百分點才列入「中實戶在收」 */
const MID_THRESHOLD = 0.3
/** 位階達到或低於這個數字，標示為近一年高檔或低檔 */
const RANK_HIGH = 80
const RANK_LOW = 20

const COLLAPSED_ROWS = 5

/** 至少兩週才連得成線，週數少時圖只有幾個點，逐週明細表仍可展開對照 */
const TREND_MIN_WEEKS = 2

/** 產業至少要有這麼多檔可比較的個股，平均值才有參考價值 */
const INDUSTRY_MIN_STOCKS = 3

/** 「各題材 / 產業大戶持股比例變化」的分組方式：題材 (與題材輪動同一套分類) 或證交所產業別 */
type GroupBy = "theme" | "industry"

const GROUP_LABELS: Record<GroupBy, string> = { theme: "題材", industry: "產業" }

interface IndustryRow {
    /** 題材或產業的名稱 */
    industry: string
    count: number
    bigDiff: number
    holdersPct: number
    bigUp: number
    bigDown: number
    /** 成員個股，依千張大戶比例變化由高到低 */
    members: { code: string; name: string; bigDiff: number }[]
}

/** 提示框最多列出幾檔成員，超過的只顯示檔數 */
const TOOLTIP_MEMBERS = 5

const weeks = ref<{ date: string; stock_count: number }[]>([])
const selectedWeek = ref("")
const week = ref<HoldersWeek | null>(null)
const scope = ref<Scope>("theme")
const period = ref<Period>(4)
const board = ref<Board>("big_up")
const keyword = ref("")
const expanded = ref(false)
const openCode = ref<string | null>(null)
const detail = ref<HoldersStock | null>(null)
const detailError = ref<string | null>(null)
const error = ref<string | null>(null)
const showGuide = ref(false)
const analysis = ref<HoldersAnalysis | null>(null)
const analysisError = ref<string | null>(null)
/** 題材分類，用來把個股歸到題材；載入失敗時只能用產業別分組 */
const themesData = ref<ThemesData | null>(null)
const groupBy = ref<GroupBy>("theme")

/** 目前比較期間的門檻 */
const th = computed(() => PERIOD_THRESHOLDS[period.value])

const boardKeys = computed(() =>
    (Object.keys(BOARD_LABELS) as Board[]).filter((key) => period.value === 1 || !WEEKLY_ONLY_BOARDS.includes(key)),
)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    return week.value ? `資料日 ${formatDate(week.value.date)}` : "載入中"
})

const hasPrev = computed(() => Boolean(week.value?.prev_date))

/**
 * 依範圍篩選、並換成目前比較期間數值的個股。
 *
 * 4 週、12 週時把 big_diff、holders_pct、price_pct 換成累計值，排行、摘要卡、散佈圖與解讀
 * 都沿用同一套欄位；往回沒有足夠週數的個股不列入。
 */
const comparable = computed<HoldersRow[]>(() => {
    const rows = (week.value?.rows ?? []).filter((row) => scope.value === "all" || row.theme)
    if (period.value === 1) {
        return rows
    }
    const k = period.value
    const pick = (row: HoldersRow, key: "big_diff" | "holders_pct" | "price_pct") =>
        row[`${key}_${k}w` as keyof HoldersRow] as number | undefined
    return rows
        .filter((row) => pick(row, "big_diff") !== undefined && pick(row, "holders_pct") !== undefined)
        .map((row) => ({
            ...row,
            big_diff: pick(row, "big_diff") as number,
            holders_pct: pick(row, "holders_pct") as number,
            price_pct: pick(row, "price_pct") ?? null,
        }))
})

/** 全部個股中有前一週資料、但不在題材分類的檔數，為 0 時切換範圍看不出差別 */
const extraComparable = computed(() => (week.value?.rows ?? []).filter((row) => !row.theme).length)

/** 當週有資料、但前一週沒有資料可比較的個股數 */
const missingPrev = computed(() => week.value?.uncompared ?? 0)

const searching = computed(() => keyword.value.trim() !== "")

const boardRows = computed<HoldersRow[]>(() => {
    const rows = comparable.value
    // 搜尋時不分排行，直接列出符合的個股
    if (searching.value) {
        const key = keyword.value.trim()
        return rows.filter((r) => r.code.includes(key) || (r.name ?? "").includes(key))
    }
    const big = (r: HoldersRow) => r.big_diff
    const retail = (r: HoldersRow) => r.holders_pct
    const t = th.value
    switch (board.value) {
        // 門檻與摘要卡、解讀相同，清單的檔數才會與摘要卡一致
        case "big_up":
            return rows.filter((r) => big(r) >= t.big).sort((a, b) => big(b) - big(a))
        case "big_down":
            return rows.filter((r) => big(r) <= -t.big).sort((a, b) => big(a) - big(b))
        case "retail_in":
            return rows.filter((r) => retail(r) >= t.retailIn).sort((a, b) => retail(b) - retail(a))
        case "retail_out":
            return rows.filter((r) => retail(r) <= t.retailOut).sort((a, b) => retail(a) - retail(b))
        case "streak_up":
            return rows
                .filter((r) => (r.streak ?? 0) >= STREAK_MIN)
                .sort((a, b) => (b.streak ?? 0) - (a.streak ?? 0) || big(b) - big(a))
        case "non_inst": {
            // 張數與法人買賣超都是單週，和 1 週的千張大戶比例一起判斷；依「大戶增加 - 法人買超」排序
            const gap = (r: HoldersRow) => (r.big_lots_diff ?? 0) - (r.inst_lots ?? 0)
            return rows
                .filter((r) => big(r) >= t.big && (r.big_lots_diff ?? 0) > 0 && r.inst_lots !== undefined && r.inst_lots <= 0)
                .sort((a, b) => gap(b) - gap(a))
        }
        default:
            return rows
                .filter((r) => (r.mid_diff ?? 0) >= MID_THRESHOLD)
                .sort((a, b) => (b.mid_diff ?? 0) - (a.mid_diff ?? 0))
    }
})

const visibleRows = computed(() => (expanded.value ? boardRows.value : boardRows.value.slice(0, COLLAPSED_ROWS)))

const summary = computed(() => {
    const rows = comparable.value
    const t = th.value
    return {
        total: rows.length,
        bigUp: rows.filter((r) => r.big_diff >= t.big).length,
        bigDown: rows.filter((r) => r.big_diff <= -t.big).length,
        retailIn: rows.filter((r) => r.holders_pct >= t.retailIn).length,
        retailOut: rows.filter((r) => r.holders_pct <= t.retailOut).length,
    }
})

/** 每檔個股所屬的題材，一檔可能屬於好幾個題材 */
const themesOfCode = computed(() => {
    const map = new Map<string, string[]>()
    for (const theme of themesData.value?.themes ?? []) {
        const codes = new Set(theme.segments.flatMap((seg) => seg.stocks.map((st) => st.code)))
        for (const code of codes) {
            const list = map.get(code) ?? []
            list.push(theme.name)
            map.set(code, list)
        }
    }
    return map
})

/** 實際使用的分組方式，題材分類還沒載入或載入失敗時用產業別 */
const activeGroupBy = computed<GroupBy>(() => (groupBy.value === "theme" && themesData.value ? "theme" : "industry"))

/**
 * 依題材或產業彙總千張大戶比例的平均變化，看這段期間大戶在收哪些族群。
 * 一檔股票屬於多個題材時，每個題材都算一次，與題材輪動的算法相同。
 */
const industryRows = computed<IndustryRow[]>(() => {
    const groups = new Map<string, HoldersRow[]>()
    const byTheme = activeGroupBy.value === "theme"
    for (const row of comparable.value) {
        const names = byTheme ? (themesOfCode.value.get(row.code) ?? []) : (row.industry ? [row.industry] : [])
        for (const name of names) {
            const list = groups.get(name) ?? []
            list.push(row)
            groups.set(name, list)
        }
    }
    const avg = (list: HoldersRow[], pick: (r: HoldersRow) => number) =>
        list.reduce((sum, r) => sum + pick(r), 0) / list.length
    return [...groups.entries()]
        .filter(([, list]) => list.length >= INDUSTRY_MIN_STOCKS)
        .map(([industry, list]) => ({
            industry,
            count: list.length,
            bigDiff: +avg(list, (r) => r.big_diff).toFixed(2),
            holdersPct: avg(list, (r) => r.holders_pct),
            bigUp: list.filter((r) => r.big_diff >= th.value.big).length,
            bigDown: list.filter((r) => r.big_diff <= -th.value.big).length,
            members: list
                .map((r) => ({ code: r.code, name: r.name ?? r.code, bigDiff: r.big_diff }))
                .sort((a, b) => b.bigDiff - a.bigDiff),
        }))
        .sort((a, b) => b.bigDiff - a.bigDiff)
})

const showAllIndustries = ref(true)

/** 大戶在收產業長條圖：預設顯示全部產業，可收合為前 5 名 */
const displayIndustryRows = computed(() => {
    if (showAllIndustries.value) {
        return industryRows.value
    }
    return industryRows.value.slice(0, 5)
})

/**
 * 長條圖的提示框：平均值之外，列出成員個股由高到低的變化 (最多 TOOLTIP_MEMBERS 檔)，
 * 看得出平均是普遍上升，還是被少數幾檔撐起來
 */
function industryTooltip(row: IndustryRow): string {
    const shown = row.members.slice(0, TOOLTIP_MEMBERS).map((m) => {
        const color = m.bigDiff > 0 ? "var(--buy)" : m.bigDiff < 0 ? "var(--sell)" : "inherit"
        return `　${m.code} ${m.name}　<span style="color:${color}">${signed(m.bigDiff)}</span>`
    })
    const rest = row.members.length - shown.length
    return [
        `<strong>${row.industry}</strong> (${row.count} 檔)`,
        `千張大戶平均　${signed(row.bigDiff)} 百分點`,
        `股東人數平均　${signedPct(row.holdersPct, 1)}`,
        `大戶在收 ${row.bigUp} 檔，在賣 ${row.bigDown} 檔`,
        `個股 (比例變化由高到低)：`,
        ...shown,
        ...(rest > 0 ? [`　…其餘 ${rest} 檔`] : []),
    ].join("<br>")
}

const tablePanel = ref<HTMLElement | null>(null)

/** 從散佈圖點選個股：改用查詢模式列出該檔並展開明細 */
async function selectFromChart(code: string) {
    keyword.value = code
    // 等 keyword 的 watch 清掉 openCode 之後再展開
    await nextTick()
    if (openCode.value !== code) {
        await toggle(code)
    }
    tablePanel.value?.scrollIntoView({ behavior: "smooth", block: "start" })
}

const panelNote = computed(() => {
    if (!week.value?.prev_date) {
        return ""
    }
    const start = period.value === 1 ? week.value.prev_date : weekBefore(week.value.date, period.value)
    const range = `${start ? formatDate(start) : `前 ${period.value} 週`} → ${formatDate(week.value.date)}`
    const label = scope.value === "theme" ? "題材分類" : "全部個股"
    if (searching.value) {
        return `${range}，${label}中符合「${keyword.value.trim()}」的個股`
    }
    return `${range}，${label}共比較 ${comparable.value.length} 檔。${BOARD_NOTES[board.value]}`
})

/** 依股價、股東人數、千張大戶比例的變化，產生一句白話解讀 */
function verdict(row: HoldersRow): { text: string; tone: string } {
    const big = row.big_diff
    const retail = row.holders_pct
    const fell = (row.price_pct ?? 0) < 0
    const t = th.value
    if (big >= t.big && retail <= 0) {
        return { text: fell ? "價跌但大戶在收，散戶離開" : "大戶在收，散戶離開", tone: "val-buy" }
    }
    if (big <= -t.big && retail >= 1) {
        return { text: fell ? "下跌時大戶賣、散戶接手" : "大戶賣給散戶", tone: "val-sell" }
    }
    if (big >= t.big) {
        return { text: fell ? "價跌但大戶在收" : "大戶在收", tone: "val-buy" }
    }
    if (big <= -t.big) {
        return { text: "大戶在賣", tone: "val-sell" }
    }
    if (retail >= t.retailIn) {
        return { text: fell ? "下跌時散戶大量進場" : "散戶大量進場", tone: "" }
    }
    if (retail <= t.retailOut) {
        return { text: "散戶離開", tone: "" }
    }
    return { text: "變化不大", tone: "muted" }
}

/** 往前第 k 週的資料日，週次清單由新到舊 */
function weekBefore(date: string, k: number): string | null {
    const index = weeks.value.findIndex((w) => w.date === date)
    return index >= 0 && index + k < weeks.value.length ? weeks.value[index + k].date : null
}

/** 連續週數，例如「連 5 週增」 */
function streakText(value: number | undefined): string {
    if (!value) {
        return "--"
    }
    return value > 0 ? `連 ${value} 週增` : `連 ${-value} 週減`
}

/** 位階加上高檔、低檔標示 */
function rankText(value: number | undefined): string {
    if (value === undefined) {
        return "--"
    }
    if (value >= RANK_HIGH) {
        return `${value} 高檔`
    }
    if (value <= RANK_LOW) {
        return `${value} 低檔`
    }
    return `${value}`
}

/** 千張大戶增減與法人買賣超的對照，推論是誰在買賣 */
function flowNote(row: HoldersRow): string {
    const big = row.big_lots_diff
    const inst = row.inst_lots
    if (big === undefined) {
        return ""
    }
    if (inst === undefined) {
        return "這段期間沒有法人買賣超資料可以對照"
    }
    if (big > 0 && inst <= 0) {
        return "千張大戶增加，但法人賣超，買的是法人以外的大戶"
    }
    if (big < 0 && inst >= 0) {
        return "千張大戶減少，但法人買超，賣的是法人以外的大戶"
    }
    if (big > 0) {
        return inst >= big ? "法人買超涵蓋了千張大戶的增加，主要是法人在買" : "法人有買，但千張大戶增加得更多，還有其他大戶在買"
    }
    if (big < 0) {
        return -inst >= -big ? "法人賣超涵蓋了千張大戶的減少，主要是法人在賣" : "法人有賣，但千張大戶減少得更多，還有其他大戶在賣"
    }
    return ""
}

function lots(value: number | undefined): string {
    if (value === undefined) {
        return "--"
    }
    return `${(value > 0 ? "+" : "") + value.toLocaleString()} 張`
}

/** 回測表的欄位值 */
function stat(row: HoldersBacktestRow | Record<string, number | null>, key: string): number | null {
    const value = row[key]
    return typeof value === "number" ? value : null
}

/** 多漲 / 少漲達到這個百分點才算訊號有明顯差別；持有越久漲跌越大，門檻跟著放寬 */
const EXCESS_CLEAR_BY_HORIZON: Record<number, number> = { 1: 0.5, 4: 1, 12: 2 }
/** 訊號出現次數少於這個數字時不下結論，避免幾次運氣好就被當成有效 */
const CONCLUSION_MIN_COUNT = 100

/** 回測「訊號出現後再看幾週」，預設看較長的 12 週，短期漲跌雜訊較大 */
const btHorizon = ref(12)

/**
 * 目前比較期間的回測：訊號用往回 period 週的累計變化判斷，與上方排行一致。
 * 舊版匯出的檔案只有 1 週的回測，其他期間回傳 null。
 */
const backtest = computed(() => {
    const data = analysis.value
    if (!data) {
        return null
    }
    return data.backtests?.[String(period.value)] ?? (period.value === 1 ? data.backtest : null)
})

/** 實際使用的往後週數，資料沒有選定的週數時改用最後一個 */
const btK = computed(() => {
    const horizons = backtest.value?.horizons ?? []
    return horizons.includes(btHorizon.value) ? btHorizon.value : (horizons[horizons.length - 1] ?? btHorizon.value)
})

/** 目前持有期間的「有明顯差別」門檻 */
const btClear = computed(() => EXCESS_CLEAR_BY_HORIZON[btK.value] ?? 2)

/** 訊號的判斷條件，依比較期間的門檻產生 */
function signalRule(key: string): string {
    const t = th.value
    const span = period.value === 1 ? "單週" : `${period.value} 週內`
    const streak = analysis.value?.thresholds.streak ?? STREAK_MIN
    const rules: Record<string, string> = {
        big_up: `${span}大戶比例增加 ${t.big} 個百分點以上`,
        big_down: `${span}大戶比例減少 ${t.big} 個百分點以上`,
        retail_in: `${span}股東人數增加 ${t.retailIn}% 以上`,
        retail_out: `${span}股東人數減少 ${-t.retailOut}% 以上`,
        streak_up: `大戶比例連續 ${streak} 週以上每週增加`,
        streak_down: `大戶比例連續 ${streak} 週以上每週減少`,
        gather: `${span}大戶比例增加 ${t.big} 個百分點以上，且股東人數沒有增加`,
        scatter: `${span}大戶比例減少 ${t.big} 個百分點以上，且股東人數增加 1% 以上`,
    }
    return rules[key] ?? ""
}

interface BacktestView {
    key: string
    label: string
    rule: string
    excess: number | null
    median: number | null
    win: number | null
    count: number
    verdict: string
    tone: string
}

/** 回測表每一列：超額、判讀與明細數字 */
const btRows = computed<BacktestView[]>(() => {
    const bt = backtest.value
    if (!bt) {
        return []
    }
    const k = btK.value
    return bt.rows.map((row) => {
        // 以畫面上顯示的一位小數判讀，避免顯示 +2.0 卻判成「沒差別」
        const raw = stat(row, `excess_${k}w`)
        const excess = raw === null ? null : Math.round(raw * 10) / 10
        const count = stat(row, `count_${k}w`) ?? 0
        let verdict = "沒差別"
        let tone = "is-flat"
        if (excess === null || count < CONCLUSION_MIN_COUNT) {
            verdict = "次數太少"
            tone = "is-few"
        } else if (excess >= btClear.value) {
            verdict = "比較會漲"
            tone = "is-up"
        } else if (excess <= -btClear.value) {
            verdict = "比較不會漲"
            tone = "is-down"
        }
        return {
            key: row.key,
            label: row.label,
            rule: signalRule(row.key),
            excess,
            median: stat(row, `median_${k}w`),
            win: stat(row, `win_${k}w`),
            count,
            verdict,
            tone,
        }
    })
})

/** 長條的刻度範圍：涵蓋 0、隨便買與每個訊號的漲跌，右側 (與負數時的左側) 留一點空間 */
const btDomain = computed(() => {
    const values = [0, btBaseline.value?.median ?? 0, ...btRows.value.map((r) => r.median ?? 0)]
    const lo = Math.min(...values)
    const hi = Math.max(...values)
    const pad = (hi - lo) * 0.08 || 1
    return { lo: lo < 0 ? lo - pad : 0, hi: hi + pad }
})

/** 數值在長條格中的位置 (%) */
function btPos(value: number): number {
    const { lo, hi } = btDomain.value
    return ((value - lo) / (hi - lo)) * 100
}

/** 長條從 0 畫到訊號的漲跌中位數 */
function btBarStyle(median: number | null): Record<string, string> {
    if (median === null) {
        return { display: "none" }
    }
    const a = btPos(0)
    const b = btPos(median)
    return { left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }
}

/**
 * 長條顏色：比隨便買好是紅、差是綠；差距在門檻內 (沒差別) 或次數太少時用淺色，完全一樣時用灰色
 */
function btBarClass(row: BacktestView): string[] {
    if (row.excess === null || row.excess === 0) {
        return ["is-flat"]
    }
    const side = row.excess > 0 ? "is-up" : "is-down"
    return row.tone === "is-up" || row.tone === "is-down" ? [side] : [side, "is-light"]
}

const btZeroStyle = computed(() => ({ left: `${btPos(0)}%` }))

/** 隨便買的基準線 */
const btBaseStyle = computed(() => ({ left: `${btPos(btBaseline.value?.median ?? 0)}%` }))

/** 基準線左右 ± 門檻的灰色區，長條停在裡面代表跟隨便買差不多 */
const btBandStyle = computed(() => {
    const base = btBaseline.value?.median ?? 0
    const a = btPos(base - btClear.value)
    const b = btPos(base + btClear.value)
    return { left: `${a}%`, width: `${b - a}%` }
})

/** 對照組 (全部題材股) 的同期表現 */
const btBaseline = computed(() => {
    const bt = backtest.value
    const k = btK.value
    if (!bt) {
        return null
    }
    return {
        median: stat(bt.baseline, `median_${k}w`),
        win: stat(bt.baseline, `win_${k}w`),
        count: stat(bt.baseline, `count_${k}w`),
    }
})

/**
 * 回測的白話結論，依目前的比較期間與往後週數產生，資料更新後會跟著變。
 *
 * 先說明同期整體行情，再列出超額明顯的訊號，都不明顯時直接說單看籌碼效果不明顯。
 */
const backtestConclusion = computed<string>(() => {
    if (!btRows.value.length) {
        return ""
    }
    // 隨便買的漲幅已在步驟 3 顯示，結論只講哪些訊號有差別
    const k = btK.value
    const parts: string[] = []
    const eligible = btRows.value.filter(
        (r): r is BacktestView & { excess: number } => r.excess !== null && r.count >= CONCLUSION_MIN_COUNT,
    )
    const better = eligible.filter((r) => r.excess >= btClear.value).sort((a, b) => b.excess - a.excess).slice(0, 2)
    const worse = eligible.filter((r) => r.excess <= -btClear.value).sort((a, b) => a.excess - b.excess).slice(0, 2)
    if (!better.length && !worse.length) {
        parts.push(
            `以 ${PERIOD_LABELS[period.value]}的訊號來看，每個訊號跟隨便買的差距都在 ±${btClear.value} 個百分點以內：有沒有出現訊號，股票表現都差不多。`,
        )
        return parts.join("")
    }
    const describe = (list: typeof better, word: string) =>
        list.map((r) => `「${r.label}」${word} ${Math.abs(r.excess).toFixed(1)} 個百分點`).join("、")
    // 開頭固定說明是哪個比較期間的訊號、持有幾週，只有少漲的訊號時也一樣
    const lead = `以 ${PERIOD_LABELS[period.value]}的訊號來看，出現訊號後持有 ${k} 週，`
    if (better.length) {
        parts.push(`${lead}${describe(better, "多漲")}。`)
    }
    if (worse.length) {
        parts.push(`${better.length ? "" : lead}${describe(worse, "少漲")}。`)
    }
    parts.push("其餘訊號跟隨便買差不多。")
    return parts.join("")
})

/** 點熱力圖的某一週，切換到該週的排行，比較期間維持不變，與熱力圖看的是同一段期間 */
function selectWeek(date: string) {
    if (weeks.value.some((w) => w.date === date)) {
        selectedWeek.value = date
        tablePanel.value?.scrollIntoView({ behavior: "smooth", block: "start" })
    }
}

function polarity(value: number | null | undefined): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

function count(value: number): string {
    return value.toLocaleString()
}

/** 人數變化，一萬以上改用「萬」 */
function people(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return "--"
    }
    const sign = value > 0 ? "+" : value < 0 ? "-" : ""
    const abs = Math.abs(value)
    return sign + (abs >= 10000 ? `${(abs / 10000).toFixed(1)} 萬` : abs.toLocaleString())
}

function signedCount(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return (value > 0 ? "+" : "") + value.toLocaleString()
}

function levelDiff(level: number, key: "people" | "pct"): number | null {
    const prev = detail.value?.previous?.levels.find((l) => l.level === level)
    const now = detail.value?.latest.levels.find((l) => l.level === level)
    if (!prev || !now) {
        return null
    }
    return now[key] - prev[key]
}

async function toggle(code: string) {
    if (openCode.value === code) {
        openCode.value = null
        return
    }
    openCode.value = code
    detail.value = null
    detailError.value = null
    try {
        detail.value = await loadHoldersStock(code)
    } catch (err) {
        detailError.value = (err as Error).message
    }
}

async function load(date: string) {
    error.value = null
    try {
        week.value = await loadHoldersWeek(date)
        selectedWeek.value = week.value.date
        openCode.value = null
    } catch (err) {
        error.value = (err as Error).message
    }
}

watch(selectedWeek, (date) => {
    if (date && date !== week.value?.date) {
        load(date)
    }
})

watch([board, scope, keyword, period], () => {
    expanded.value = false
    openCode.value = null
})

// 切到 4 週、12 週時，只適用單週的排行改回預設
watch(period, () => {
    if (!boardKeys.value.includes(board.value)) {
        board.value = "big_up"
    }
})

onMounted(async () => {
    // 回測與熱力圖另外載入，失敗時不影響排行
    loadHoldersAnalysis()
        .then((data) => {
            analysis.value = data
        })
        .catch((err) => {
            analysisError.value = (err as Error).message
        })
    // 題材分類只用於「各題材大戶持股比例變化」的分組，失敗時改用產業別
    loadThemes()
        .then((data) => {
            themesData.value = data
        })
        .catch(() => {
            themesData.value = null
        })
    try {
        weeks.value = (await loadHolders()).weeks
        if (weeks.value.length) {
            await load(weeks.value[0].date)
        }
    } catch (err) {
        error.value = (err as Error).message
    }
})
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>籌碼分布</h1>
                <p class="subtitle">
                    每週一次：股票這一週流向大戶，還是流向散戶？
                    <button type="button" class="guide-toggle" :aria-expanded="showGuide" @click="showGuide = !showGuide">
                        {{ showGuide ? "收起說明" : "怎麼看？" }}
                    </button>
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <!-- 說明預設收合，開關接在副標題後面，熟悉的人不用每次捲過 -->
        <section v-if="showGuide" class="panel guide">
            <p>
                官方每天只公布三大法人的買賣，法人賣出時是誰買走的看不到。集保每週公布每檔股票有多少人持有、各持有多少，
                比較前後兩週，就知道股票往誰手上跑。只要看兩個數字：
            </p>
            <ul>
                <li><strong>股東人數</strong>：增加代表散戶進場、股票變分散；減少代表散戶離開。</li>
                <li><strong>千張大戶比例</strong>：持有 1,000 張以上的人合計佔多少股份，上升代表大戶在收，下降代表大戶在賣。</li>
            </ul>
            <p class="muted">
                例：台積電 10/30 到 11/06 股價跌 9.9%，股東人數一週多了 7.4 萬人，千張大戶比例小降，代表下跌時是散戶在接。
                千張大戶也包含外資、投信等法人帳戶，不全是個人大戶。
            </p>
        </section>

        <div class="controls">
            <label class="control">
                <span class="control-label">週次</span>
                <select v-model="selectedWeek">
                    <option v-for="item in weeks" :key="item.date" :value="item.date">{{ formatDate(item.date) }}</option>
                </select>
            </label>
            <div class="control">
                <span class="control-label">比較期間</span>
                <div class="chip-row">
                    <button
                        v-for="(label, key) in PERIOD_LABELS"
                        :key="key"
                        type="button"
                        class="chip"
                        :class="{ 'is-active': period === Number(key) }"
                        @click="period = Number(key) as Period"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>
            <div class="control">
                <span class="control-label">範圍</span>
                <div class="chip-row">
                    <button type="button" class="chip" :class="{ 'is-active': scope === 'theme' }" @click="scope = 'theme'">
                        題材分類
                    </button>
                    <button type="button" class="chip" :class="{ 'is-active': scope === 'all' }" @click="scope = 'all'">
                        全部個股
                    </button>
                </div>
            </div>
            <label class="control">
                <span class="control-label">查個股</span>
                <input v-model="keyword" type="search" placeholder="代號或名稱" class="search-input">
            </label>
        </div>

        <p v-if="week && !hasPrev" class="notice holders-notice">
            這一週沒有前一週的資料可以比較。集保開放資料只提供最新一週，下週更新後就會有變化。
        </p>

        <p v-if="week && hasPrev && scope === 'all' && extraComparable === 0" class="notice holders-notice">
            目前和「題材分類」顯示的是同樣 {{ comparable.length }} 檔：前一週 ({{ formatDate(week.prev_date) }}) 只補了題材分類的個股，
            其他 {{ missingPrev.toLocaleString() }} 檔沒有前一週資料可以比較。下週集保更新後，全部個股都會有週變化。
        </p>

        <p v-if="week && hasPrev && period !== 1 && !comparable.length" class="notice holders-notice">
            這一週往前沒有 {{ period }} 週的資料可以比較，請改看較短的期間或較近的週次。
        </p>

        <div v-if="week && hasPrev" class="quote-grid holders-tiles">
            <div class="quote-card">
                <div class="quote-name">大戶在收</div>
                <div class="quote-value val-buy">{{ summary.bigUp }} 檔</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">大戶在賣</div>
                <div class="quote-value val-sell">{{ summary.bigDown }} 檔</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">散戶湧入</div>
                <div class="quote-value">{{ summary.retailIn }} 檔</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">散戶離開</div>
                <div class="quote-value">{{ summary.retailOut }} 檔</div>
            </div>
        </div>

        <div v-if="hasPrev && (comparable.length || industryRows.length)" class="charts-row">
            <section v-if="comparable.length" class="panel holders-chart-panel" data-nav="籌碼流向分布">
                <div class="panel-head">
                    <h2>籌碼流向分布</h2>
                    <p class="panel-note">
                        一個點是一檔股票，看的是 {{ PERIOD_LABELS[period] }} 的變化，紅漲綠跌是同期間的股價漲跌，空心點代表數值超出畫面、貼在邊緣。
                        左上是大戶收、散戶走，右下是大戶賣、散戶接。點一下可看該檔明細。
                    </p>
                </div>
                <HoldersScatter
                    :rows="comparable"
                    :big-threshold="th.big"
                    :retail-in="th.retailIn"
                    :retail-out="th.retailOut"
                    @select="selectFromChart"
                />
            </section>

            <section v-if="industryRows.length" class="panel holders-chart-panel" data-nav="大戶持股比例變化">
                <div class="panel-head">
                    <div class="panel-head-flex">
                        <!-- 標題強調是「比例」的變化，避免被誤會成買賣金額 (金額請看題材輪動的資金流向圖) -->
                        <h2>各{{ GROUP_LABELS[activeGroupBy] }}大戶持股比例變化 {{ showAllIndustries ? "" : "(前 5 名)" }}</h2>
                        <div class="group-controls">
                            <div class="chip-row">
                                <button
                                    v-for="(label, key) in GROUP_LABELS"
                                    :key="key"
                                    type="button"
                                    class="chip"
                                    :class="{ 'is-active': activeGroupBy === key }"
                                    :disabled="key === 'theme' && !themesData"
                                    @click="groupBy = key"
                                >
                                    {{ label }}
                                </button>
                            </div>
                            <button
                                v-if="industryRows.length > 5"
                                type="button"
                                class="chip flow-toggle"
                                @click="showAllIndustries = !showAllIndustries"
                            >
                                {{ showAllIndustries ? "收合為前 5 名" : `查看全部 ${industryRows.length} 個${GROUP_LABELS[activeGroupBy]}` }}
                            </button>
                        </div>
                    </div>
                    <p class="panel-note">
                        各{{ GROUP_LABELS[activeGroupBy] }}千張大戶比例在 {{ PERIOD_LABELS[period] }} 內的平均變化 (百分點)，只列可比較個股達 {{ INDUSTRY_MIN_STOCKS }} 檔以上的{{ GROUP_LABELS[activeGroupBy] }}。
                        看的是持股比例，不是買賣金額：小型股比例動幾個百分點，實際金額可能不多；金額請看下方題材輪動的資金流向圖。
                        <template v-if="activeGroupBy === 'theme'">
                            題材與下方題材輪動是同一套分類，一檔股票屬於多個題材時每個題材都會算到；
                            這裡固定以千張為大戶門檻，題材輪動則依股價調整門檻，數字會略有不同。
                        </template>
                        <template v-else>
                            產業別採用證交所「國際證券辨識號碼 (ISIN) 一覽表」的產業分類，上市、上櫃共用同一套名稱，
                            與下方的題材分類不同 (例如 PCB 個股多屬電子零組件業)。
                        </template>
                    </p>
                </div>
                <BarChart
                    :rows="displayIndustryRows"
                    :name-of="(row: IndustryRow) => `${row.industry} (${row.count})`"
                    :value-of="(row: IndustryRow) => row.bigDiff"
                    :tooltip="industryTooltip"
                    :label-width="170"
                    unit="百分點"
                />
            </section>
        </div>

        <section v-if="hasPrev" ref="tablePanel" class="panel" data-nav="個股排行">
            <div class="panel-head">
                <h2>{{ searching ? "查詢結果" : BOARD_LABELS[board] }}</h2>
                <p class="panel-note">{{ panelNote }}</p>
            </div>
            <div v-if="!searching" class="controls controls-inline">
                <div class="tabs" role="tablist">
                    <button
                        v-for="key in boardKeys"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': board === key }"
                        role="tab"
                        @click="board = key"
                    >
                        {{ BOARD_LABELS[key] }}
                    </button>
                </div>
            </div>

            <div class="table-wrap holders-table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>個股</th>
                            <th class="num">股價漲跌</th>
                            <th class="num">股東人數變化</th>
                            <th class="num">千張大戶比例變化</th>
                            <th class="num" title="千張大戶比例連續增加或減少的週數">連續</th>
                            <th class="num" title="目前千張大戶比例在近一年中的位置，0 最低、100 最高">一年位階</th>
                            <th>解讀</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!visibleRows.length" class="empty-row">
                            <td colspan="7">沒有符合的個股</td>
                        </tr>
                        <template v-for="row in visibleRows" :key="row.code">
                            <tr class="clickable" :class="{ 'is-selected': openCode === row.code }" @click="toggle(row.code)">
                                <td>
                                    {{ row.code }} {{ row.name ?? "" }}
                                    <span class="muted">{{ row.industry ?? "" }}</span>
                                    <!-- 所屬題材，與上方「各題材大戶持股比例變化」對照 -->
                                    <span v-if="themesOfCode.get(row.code)?.length" class="row-themes">
                                        ・{{ themesOfCode.get(row.code)?.join("、") }}
                                    </span>
                                </td>
                                <td class="num" :class="polarity(row.price_pct)">{{ signedPct(row.price_pct, 1) }}</td>
                                <td class="num">
                                    <!-- 累計期間只有比例，沒有人數差 -->
                                    <template v-if="period === 1">
                                        {{ people(row.holders_diff) }}
                                        <span class="muted">（{{ signedPct(row.holders_pct, 1) }}）</span>
                                    </template>
                                    <template v-else>{{ signedPct(row.holders_pct, 1) }}</template>
                                </td>
                                <td class="num" :class="polarity(row.big_diff)">
                                    {{ signed(row.big_diff) }}
                                    <span class="muted">（{{ row.big_pct.toFixed(1) }}%）</span>
                                </td>
                                <td class="num" :class="polarity(row.streak)">{{ streakText(row.streak) }}</td>
                                <td class="num">{{ rankText(row.big_rank) }}</td>
                                <td class="verdict" :class="verdict(row).tone">{{ verdict(row).text }}</td>
                            </tr>
                            <tr v-if="openCode === row.code" class="detail-row">
                                <td colspan="7">
                                    <dl v-if="row.big_lots_diff !== undefined || row.mid_pct !== undefined" class="flow-strip">
                                        <div>
                                            <dt>千張大戶本週</dt>
                                            <dd :class="polarity(row.big_lots_diff)">{{ lots(row.big_lots_diff) }}</dd>
                                        </div>
                                        <div>
                                            <dt>三大法人同期</dt>
                                            <dd :class="polarity(row.inst_lots)">{{ lots(row.inst_lots) }}</dd>
                                        </div>
                                        <div>
                                            <dt>400~1000 張中實戶</dt>
                                            <dd>
                                                {{ row.mid_pct?.toFixed(2) ?? "--" }}%
                                                <span class="muted" :class="polarity(row.mid_diff)">（{{ signed(row.mid_diff) }}）</span>
                                            </dd>
                                        </div>
                                        <div>
                                            <dt>股東人數一年位階</dt>
                                            <dd>{{ rankText(row.holders_rank) }}</dd>
                                        </div>
                                        <p v-if="flowNote(row)" class="flow-note">{{ flowNote(row) }}</p>
                                    </dl>
                                    <p v-if="detailError" class="notice">載入失敗：{{ detailError }}</p>
                                    <p v-else-if="!detail" class="muted">載入中</p>
                                    <div v-else class="detail-grid">
                                        <div class="detail-chart">
                                            <h3 class="detail-title">逐週走勢</h3>
                                            <HoldersTrendChart v-if="detail.series.length >= TREND_MIN_WEEKS" :series="detail.series" />
                                            <p v-else class="muted">只有 1 週資料，還畫不出走勢。</p>
                                            <details class="level-table" :open="detail.series.length < TREND_MIN_WEEKS">
                                                <summary class="muted">看逐週明細表</summary>
                                                <table class="data-table detail-table">
                                                <thead>
                                                    <tr>
                                                        <th>資料日</th>
                                                        <th class="num">收盤</th>
                                                        <th class="num">股東人數</th>
                                                        <th class="num">千張大戶</th>
                                                        <th class="num">50 張以下</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    <tr v-for="item in [...detail.series].reverse()" :key="item.date">
                                                        <td>{{ formatDate(item.date) }}</td>
                                                        <td class="num">{{ item.close ?? "--" }}</td>
                                                        <td class="num">{{ count(item.holders) }}</td>
                                                        <td class="num">{{ item.big_pct.toFixed(2) }}%</td>
                                                        <td class="num">{{ item.small_pct.toFixed(2) }}%</td>
                                                    </tr>
                                                </tbody>
                                                </table>
                                            </details>
                                        </div>
                                        <div class="detail-chart">
                                            <h3 class="detail-title">
                                                各持股級距
                                                <span v-if="detail.previous" class="muted">（與前一週相比）</span>
                                            </h3>
                                            <HoldersLevelChart :latest="detail.latest" :previous="detail.previous" />
                                            <details class="level-table">
                                                <summary class="muted">看級距明細表</summary>
                                                <table class="data-table detail-table">
                                                <thead>
                                                    <tr>
                                                        <th>持股 (股)</th>
                                                        <th class="num">人數</th>
                                                        <th class="num">增減</th>
                                                        <th class="num">佔股份</th>
                                                        <th class="num">增減</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    <tr v-for="lv in detail.latest.levels" :key="lv.level" :class="{ 'total-row': lv.level === 17 }">
                                                        <td>{{ lv.label }}</td>
                                                        <td class="num">{{ count(lv.people) }}</td>
                                                        <td class="num" :class="polarity(levelDiff(lv.level, 'people'))">{{ signedCount(levelDiff(lv.level, "people")) }}</td>
                                                        <td class="num">{{ lv.pct.toFixed(2) }}%</td>
                                                        <td class="num" :class="polarity(levelDiff(lv.level, 'pct'))">{{ signed(levelDiff(lv.level, "pct")) }}</td>
                                                    </tr>
                                                </tbody>
                                                </table>
                                            </details>
                                        </div>
                                    </div>
                                </td>
                            </tr>
                        </template>
                    </tbody>
                </table>
            </div>

            <div v-if="boardRows.length > COLLAPSED_ROWS" class="more-wrap">
                <button type="button" class="chip" @click="expanded = !expanded">
                    {{ expanded ? `收合為前 ${COLLAPSED_ROWS} 名` : `展開全部 ${boardRows.length} 名` }}
                </button>
            </div>

            <p class="panel-note holders-foot">
                千張大戶比例變化的單位是百分點，括號內是目前的比例。{{ PERIOD_LABELS[period] }}內變化達 {{ th.big }} 個百分點才算大戶在收或在賣，
                股東人數增加 {{ th.retailIn }}% 以上算散戶湧入、減少 {{ -th.retailOut }}% 以上算散戶離開；期間越長門檻越寬。
                「連續」是千張大戶比例連續增加或減少的週數，「一年位階」是目前比例在近一年的位置 (0 最低、100 最高)。
                點選列可看法人對照、逐週走勢與各級距的人數。
            </p>
        </section>

        <p v-if="analysisError" class="notice holders-notice">回測與題材輪動載入失敗：{{ analysisError }}</p>

        <section v-if="analysis && analysis.heatmap.weeks.length" class="panel holders-chart-panel" data-nav="題材輪動">
            <div class="panel-head">
                <!-- 標題與比較期間放同一列，省下垂直空間，讓下方圖表不用捲動就能看到 -->
                <div class="panel-head-flex">
                    <h2>題材輪動</h2>
                    <!-- 與頁面上方的比較期間是同一個設定，捲到這裡時不用再捲回頂端切換 -->
                    <div class="control">
                        <span class="control-label">比較期間</span>
                        <div class="chip-row">
                            <button
                                v-for="(label, key) in PERIOD_LABELS"
                                :key="key"
                                type="button"
                                class="chip"
                                :class="{ 'is-active': period === Number(key) }"
                                @click="period = Number(key) as Period"
                            >
                                {{ label }}
                            </button>
                        </div>
                    </div>
                </div>
                <p class="panel-note">
                    各題材個股的大戶比例平均變化，看選定期間內大戶的錢在哪些題材之間移動。大戶門檻依股價調整 (約持股 4 億元以上)。
                </p>
                <details class="threshold-more panel-note">
                    <summary>大戶門檻說明</summary>
                    <p>
                        題材輪動與下方熱力圖的大戶門檻依股價調整，約持股 4 億元以上算大戶：股價 1000 元以上 400 張、667~1000 元 600 張、
                        500~667 元 800 張、500 元以下維持 1000 張。高價股用千張當門檻，持股好幾億的股東也會被算成小股東。
                        頁面上其他區塊 (個股排行、訊號、回測) 仍以千張為門檻。
                    </p>
                </details>
            </div>
            <HoldersThemeFlowChart
                :heatmap="analysis.heatmap"
                :period="period"
                :selected-date="selectedWeek || week?.date"
            />
        </section>

        <section v-if="analysis && analysis.heatmap.weeks.length" class="panel holders-chart-panel" data-nav="題材熱力圖">
            <div class="panel-head">
                <h2>題材熱力圖 (整年)</h2>
                <p class="panel-note">
                    每一列是一個題材，每一欄是一週，格子是大戶比例平均變化 ({{ period === 1 ? "單週" : `到該週為止的 ${period} 週合計` }})，紅色是大戶在收、綠色是在賣。
                    橫著看一列，連續同色代表大戶持續收或賣；上下對照同一段時間，一個題材由紅轉綠、另一個由綠轉紅，就是大戶從前者移到後者。
                    單週格子雜訊大，切到上方的 4 週比較容易看出輪動。點一下格子會切到那一週的排行。
                </p>
            </div>
            <HoldersThemeHeatmap :heatmap="analysis.heatmap" :period="period" @select="selectWeek" />
        </section>

        <section v-if="analysis" class="panel holders-chart-panel" data-nav="這些訊號準不準">
            <div class="panel-head">
                <h2>這些訊號準不準 (回測)</h2>
                <p class="panel-note">
                    照個股排行的訊號買股票，會比隨便買一檔題材股賺得多嗎？
                    用 {{ formatDate(analysis.first_week) }} ~ {{ formatDate(analysis.last_week) }} 這一年的 {{ analysis.stock_count }} 檔題材股，每一週都照下面三步驟驗證一次。
                </p>
            </div>

            <!-- 三步驟：往回看判斷訊號 → 往後看持有多久 → 跟隨便買比；兩組按鈕各放在對應的步驟裡 -->
            <ol class="bt-steps">
                <li class="bt-step">
                    <div class="bt-step-head"><span class="bt-step-no">1</span>判斷有沒有訊號：往回看</div>
                    <div class="chip-row">
                        <button
                            v-for="(label, key) in PERIOD_LABELS"
                            :key="key"
                            type="button"
                            class="chip"
                            :class="{ 'is-active': period === Number(key) }"
                            @click="period = Number(key) as Period"
                        >
                            {{ label }}
                        </button>
                    </div>
                    <p class="bt-step-note">
                        看這段期間的籌碼變化。例如「{{ signalRule("big_up") }}」就算一次「大戶在收」。
                        與頁面上方的比較期間是同一個設定。
                    </p>
                </li>
                <li class="bt-step">
                    <div class="bt-step-head"><span class="bt-step-no">2</span>出現訊號就買進，持有</div>
                    <div v-if="backtest" class="chip-row">
                        <button
                            v-for="k in backtest.horizons"
                            :key="k"
                            type="button"
                            class="chip"
                            :class="{ 'is-active': btK === k }"
                            @click="btHorizon = k"
                        >
                            {{ k }} 週
                        </button>
                    </div>
                    <p class="bt-step-note">
                        {{ btK }} 週後再看股價漲跌。{{ btK === 1 ? "只拿 1 週的漲跌受大盤與消息面影響大，參考性較低。" : "" }}
                    </p>
                </li>
                <li class="bt-step">
                    <div class="bt-step-head"><span class="bt-step-no">3</span>跟「隨便買」比</div>
                    <div class="bt-step-value">
                        隨便買一檔題材股持有 {{ btK }} 週：<strong>{{ signedPct(btBaseline?.median ?? null, 1) }}</strong>
                    </div>
                    <p class="bt-step-note">
                        照訊號買的漲幅減掉隨便買的漲幅，就是下表的「多漲 / 少漲」(都取中位數)。
                    </p>
                </li>
            </ol>

            <p v-if="!backtest" class="notice">目前的資料沒有 {{ PERIOD_LABELS[period] }}的回測，請重新產生籌碼分析資料。</p>
            <template v-else>
                <p v-if="backtestConclusion" class="backtest-conclusion">{{ backtestConclusion }}</p>

                <p class="panel-note bt-howto">
                    <strong>怎麼看下表：</strong>長條是照這個訊號買、持有 {{ btK }} 週的漲跌 (中位數)。
                    虛線是隨便買的 {{ signedPct(btBaseline?.median ?? null, 1) }}，灰色區是虛線左右 ±{{ btClear }} 個百分點。
                    長條超過灰色區 (紅) = 比隨便買多漲，沒碰到灰色區 (綠) = 少漲，停在灰色區裡 = 跟隨便買差不多。
                </p>

                <div class="table-wrap">
                    <table class="data-table bt-table">
                        <thead>
                            <tr>
                                <th>訊號</th>
                                <th>條件 ({{ PERIOD_LABELS[period] }})</th>
                                <th class="bt-bar-head">持有 {{ btK }} 週的漲跌 (虛線 = 隨便買 {{ signedPct(btBaseline?.median ?? null, 1) }})</th>
                                <th>判讀</th>
                                <th class="num" title="這一年內符合訊號的「個股 × 週」次數">次數</th>
                            </tr>
                        </thead>
                        <tbody>
                            <!-- 對照組放第一列當基準，下面每個訊號都跟它比 -->
                            <tr v-if="btBaseline" class="bt-base-row">
                                <td class="bt-label">隨便買</td>
                                <td class="bt-rule">不看籌碼，每週任選一檔題材股 (全部題材股的表現)</td>
                                <td>
                                    <div class="bt-bar-cell">
                                        <div class="bt-track">
                                            <span class="bt-band" :style="btBandStyle" />
                                            <span class="bt-axis" :style="btZeroStyle" />
                                            <span class="bt-bar is-base" :style="btBarStyle(btBaseline.median)" />
                                            <span class="bt-base" :style="btBaseStyle" />
                                        </div>
                                        <span class="bt-val">{{ signedPct(btBaseline.median, 1) }}</span>
                                        <span class="bt-diff muted">基準</span>
                                    </div>
                                </td>
                                <td><span class="bt-tag is-few">基準</span></td>
                                <td class="num secondary">{{ btBaseline.count?.toLocaleString() ?? "--" }}</td>
                            </tr>
                            <tr v-for="row in btRows" :key="row.key">
                                <td class="bt-label">{{ row.label }}</td>
                                <td class="bt-rule">{{ row.rule }}</td>
                                <td>
                                    <div class="bt-bar-cell">
                                        <div class="bt-track">
                                            <span class="bt-band" :style="btBandStyle" />
                                            <span class="bt-axis" :style="btZeroStyle" />
                                            <span class="bt-bar" :class="btBarClass(row)" :style="btBarStyle(row.median)" />
                                            <span class="bt-base" :style="btBaseStyle" />
                                        </div>
                                        <span class="bt-val">{{ signedPct(row.median, 1) }}</span>
                                        <span class="bt-diff" :class="polarity(row.excess)">
                                            {{ row.excess === null ? "" : `比隨便買 ${signed(row.excess, 1)}` }}
                                        </span>
                                    </div>
                                </td>
                                <td><span class="bt-tag" :class="row.tone">{{ row.verdict }}</span></td>
                                <td class="num secondary">{{ row.count.toLocaleString() }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <details class="bt-more">
                    <summary>看完整數字 (漲跌中位數、上漲機率)</summary>
                    <div class="table-wrap">
                        <table class="data-table bt-detail-table">
                            <thead>
                                <tr>
                                    <th>訊號</th>
                                    <th class="num">多漲 / 少漲</th>
                                    <th class="num">{{ btK }} 週漲跌中位數</th>
                                    <th class="num">上漲機率</th>
                                    <th class="num">次數</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="row in btRows" :key="row.key">
                                    <td>{{ row.label }}</td>
                                    <td class="num" :class="polarity(row.excess)">{{ signed(row.excess, 1) }}</td>
                                    <td class="num secondary">{{ signedPct(row.median, 1) }}</td>
                                    <td class="num secondary">{{ row.win?.toFixed(0) ?? "--" }}%</td>
                                    <td class="num secondary">{{ row.count.toLocaleString() }}</td>
                                </tr>
                                <tr v-if="btBaseline" class="total-row">
                                    <td>隨便買 (全部題材股)</td>
                                    <td class="num muted">--</td>
                                    <td class="num secondary">{{ signedPct(btBaseline.median, 1) }}</td>
                                    <td class="num secondary">{{ btBaseline.win?.toFixed(0) ?? "--" }}%</td>
                                    <td class="num secondary">{{ btBaseline.count?.toLocaleString() ?? "--" }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <p class="panel-note">
                        漲跌中位數：出現訊號後 {{ btK }} 週股價漲跌的中位數。上漲機率：這些次數中 {{ btK }} 週後股價上漲的比例。
                        多漲 / 少漲 = 訊號的漲跌中位數 − 隨便買的漲跌中位數。次數是「個股 × 週」，同一檔連續幾週都符合會算好幾次。
                    </p>
                </details>
            </template>

            <p class="panel-note holders-foot">
                用中位數而不是平均，是避免少數飆股把數字拉高。要注意：題材分類是現在的名單，有一點後見之明；
                過去一年又是多頭行情，結果不一定適用在空頭。僅供參考，不構成投資建議。
            </p>
        </section>
    </section>
</template>

<style scoped>
.guide {
    margin-bottom: 16px;
}

.threshold-more summary {
    cursor: pointer;
    color: var(--text-secondary);
    user-select: none;
}

.threshold-more p {
    margin: 4px 0 0;
}

/* 外觀像文字連結，接在副標題後面不搶版面 */
.guide-toggle {
    margin-left: 6px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text-secondary);
    font: inherit;
    text-decoration: underline;
    text-underline-offset: 3px;
    cursor: pointer;
}

.guide-toggle:hover {
    color: var(--text-primary);
}

.guide p:first-child {
    margin-top: 0;
}

.guide p,
.guide li {
    line-height: 1.7;
}

.guide ul {
    margin: 4px 0 8px;
    padding-left: 20px;
}

.holders-notice,
.holders-tiles {
    margin-bottom: 16px;
}

.chip-row {
    display: flex;
    gap: 6px;
}

.search-input {
    width: 140px;
}

.clickable {
    cursor: pointer;
}

.is-selected td {
    background: var(--neutral);
    font-weight: 600;
}

.muted {
    color: var(--text-secondary);
    font-size: 12px;
}

.detail-row > td {
    padding: 8px 12px 12px 32px;
    background: var(--surface-0);
}

.detail-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
    align-items: flex-start;
}

.detail-chart {
    flex: 1 1 420px;
    min-width: 0;
}

.level-table summary {
    cursor: pointer;
    margin: 4px 0 8px;
}

/* 清單已預設收合為前 20 名，展開的明細有圖表，不限制高度以免被擠進小捲動框 */
.holders-table-wrap {
    max-height: none;
}

/* 展開明細上方的法人對照與中實戶數字 */
.flow-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 28px;
    margin: 0 0 12px;
    padding: 8px 0 12px;
    border-bottom: 1px solid var(--border);
}

.flow-strip dt {
    color: var(--text-secondary);
    font-size: 12px;
}

.flow-strip dd {
    margin: 2px 0 0;
    font-size: 15px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.flow-note {
    flex-basis: 100%;
    margin: 0;
    color: var(--text-secondary);
    font-size: 13px;
}

/* 回測的三個步驟，寬螢幕排一列，窄螢幕改直排 */
.bt-steps {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
    margin: 0 0 12px;
    padding: 0;
    list-style: none;
}

.bt-step {
    position: relative;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-0);
}

/* 步驟之間的箭頭 */
.bt-step + .bt-step::before {
    content: "→";
    position: absolute;
    top: 50%;
    left: -10px;
    transform: translate(-50%, -50%);
    color: var(--text-muted);
    font-size: 14px;
}

.bt-step-head {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
    font-weight: 600;
    font-size: 13px;
}

.bt-step-no {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--text-primary);
    color: var(--surface-0);
    font-size: 11px;
}

.bt-step-value {
    font-size: 13px;
}

.bt-step-note {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.6;
}

@media (max-width: 760px) {
    .bt-steps {
        grid-template-columns: 1fr;
    }

    .bt-step + .bt-step::before {
        content: "↓";
        top: -10px;
        left: 50%;
    }
}

.bt-howto {
    margin: 0 0 8px;
}

.bt-label {
    font-weight: 600;
    white-space: nowrap;
}

.bt-rule {
    color: var(--text-secondary);
    font-size: 12px;
}

.bt-bar-head {
    width: 38%;
    min-width: 240px;
}

.bt-bar-cell {
    display: flex;
    align-items: center;
    gap: 8px;
}

/* 實線是 0，虛線是隨便買，灰帶是虛線左右 ± 門檻的「沒差別」區 */
.bt-track {
    position: relative;
    flex: 1;
    height: 14px;
    min-width: 160px;
}

.bt-band {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--neutral);
}

.bt-axis {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 1px;
    background: var(--text-muted);
}

.bt-base {
    position: absolute;
    top: -4px;
    bottom: -4px;
    margin-left: -1px;
    border-left: 2px dashed var(--text-primary);
}

.bt-bar {
    position: absolute;
    top: 3px;
    bottom: 3px;
    border-radius: 2px;
}

.bt-bar.is-up {
    background: var(--buy);
}

.bt-bar.is-down {
    background: var(--sell);
}

.bt-bar.is-flat {
    background: var(--text-muted);
    opacity: 0.55;
}

/* 方向同上，但差距在門檻內 (沒差別)，用淺色表示 */
.bt-bar.is-light {
    opacity: 0.35;
}

/* 隨便買的基準列：深色長條、底色區隔，和下面的訊號分開 */
.bt-bar.is-base {
    background: var(--text-primary);
    opacity: 0.75;
}

.bt-base-row td {
    background: var(--surface-0);
    border-bottom: 2px solid var(--border);
}

.bt-val {
    width: 52px;
    text-align: right;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.bt-diff {
    width: 92px;
    font-size: 12px;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}

.bt-tag {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 12px;
    white-space: nowrap;
}

.bt-tag.is-up {
    color: var(--buy);
    border: 1px solid var(--buy);
}

.bt-tag.is-down {
    color: var(--sell);
    border: 1px solid var(--sell);
}

.bt-tag.is-flat,
.bt-tag.is-few {
    color: var(--text-muted);
    border: 1px solid var(--border);
}

.bt-table .secondary,
.bt-detail-table .secondary {
    color: var(--text-secondary);
}

.bt-more {
    margin-top: 10px;
}

.bt-more summary {
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 13px;
    user-select: none;
}

.bt-more .table-wrap {
    margin-top: 8px;
}

.backtest-conclusion {
    margin: 0 0 12px;
    padding: 10px 14px;
    border-left: 3px solid var(--text-secondary);
    background: var(--surface-0);
    line-height: 1.7;
}

.charts-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    align-items: stretch;
    margin-bottom: 16px;
}

.charts-row .holders-chart-panel {
    margin-bottom: 0;
    display: flex;
    flex-direction: column;
}

/* 至少維持圖表自己算的高度 (題材多時長條圖會比較高)，同一列另一張圖較高時再撐滿 */
.charts-row .holders-chart-panel :deep(.chart-tall),
.charts-row .holders-chart-panel :deep(.chart) {
    flex: 1 0 auto;
    min-height: 380px;
}

.row-themes {
    color: var(--text-muted);
    font-size: 12px;
}

.group-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}

.panel-head-flex {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}

@media (max-width: 960px) {
    .charts-row {
        grid-template-columns: 1fr;
    }
}

.holders-chart-panel {
    margin-bottom: 16px;
}

.detail-title {
    margin: 4px 0 8px;
    font-size: 14px;
}

.detail-table {
    width: auto;
    min-width: 360px;
}

.total-row td {
    font-weight: 600;
    border-top: 1px solid var(--border);
}

.verdict {
    min-width: 180px;
    white-space: normal;
}

.more-wrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
}

.holders-foot {
    margin-top: 12px;
}
</style>
