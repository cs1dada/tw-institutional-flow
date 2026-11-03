<script setup lang="ts">
/**
 * 估值趨勢矩陣：前瞻本益比 × 股價相對 60 日均線的位置。
 *
 * 縱軸是前瞻本益比與所屬環節合理區間的比較 (由上而下為偏貴、合理、便宜)，
 * 橫軸是收盤相對 60 日均線的距離 (由左而右為均線下方、附近、上方)，
 * 讀法跟散布圖一樣：越上面越貴、越右邊走勢越強。每格標示一個狀態描述。
 * 判定都在後端算好 (app/services/valuation_grid.py)，這裡只負責呈現、切換日期與年度、篩選，
 * 以及比較選定日期與約一週前的快照，列出落點改變的個股。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadValuation, loadValuationSnapshot } from "@/api/dataSource"
import type {
    PriceZone,
    ValuationIndex,
    ValuationLevel,
    ValuationSnapshot,
    ValuationStock,
    ValuationYear,
} from "@/types"
import { formatDate, signed } from "@/utils/format"

/** focus：可優先研究；check：要另外驗證；neutral：沒有明顯訊號；weak：條件最弱 */
type Tone = "focus" | "check" | "neutral" | "weak"

interface CellDef {
    name: string
    tone: Tone
    /** 這格代表的狀態 */
    meaning: string
    /** 需要留意的地方 */
    caution: string
}

type CellKey = `${PriceZone}-${ValuationLevel}`

/** 由上而下：越上面越貴 */
const LEVEL_ROWS: ValuationLevel[] = ["high", "fair", "low"]
/** 由左而右：越右邊走勢越強 */
const ZONE_COLS: PriceZone[] = ["repair", "ma", "strong"]

const LEVEL_LABELS: Record<ValuationLevel, string> = { low: "便宜", fair: "合理", high: "偏貴" }
const LEVEL_NOTES: Record<ValuationLevel, string> = {
    low: "低於區間下緣",
    fair: "落在區間內",
    high: "高於區間上緣",
}

const ZONE_LABELS: Record<PriceZone, string> = { strong: "均線上方", ma: "均線附近", repair: "均線下方" }

const TONE_LABELS: Record<Tone, string> = {
    focus: "優先研究",
    check: "需要驗證",
    neutral: "中性",
    weak: "條件最弱",
}

const CELLS: Record<CellKey, CellDef> = {
    "repair-high": {
        name: "溢價修正",
        tone: "weak",
        meaning: "本益比高於區間，股價又落在均線下方，估值和走勢都不站在這邊",
        caution: "估值還有往區間回落的空間，等本益比回到區間內再重新評估",
    },
    "ma-high": {
        name: "溢價整理",
        tone: "check",
        meaning: "本益比高於區間，股價在均線附近來回",
        caution: "需要新的成長理由才撐得住估值，留意法說會與月營收是否支持",
    },
    "strong-high": {
        name: "溢價上行",
        tone: "check",
        meaning: "股價走在均線上方，本益比已經超過區間，市場給了很高的期待",
        caution: "期待落空時修正幅度通常較大，持有時要先想好出場條件",
    },
    "repair-fair": {
        name: "合理轉弱",
        tone: "neutral",
        meaning: "本益比在區間內，但股價跌到均線下方，走勢還沒止穩",
        caution: "觀察能否止跌並重新站回均線，在那之前不急著判斷",
    },
    "ma-fair": {
        name: "中性整理",
        tone: "neutral",
        meaning: "本益比在區間內，股價也在均線附近，估值和走勢都沒有明顯訊號",
        caution: "等股價離開均線、往上或往下表態後再看",
    },
    "strong-fair": {
        name: "合理上行",
        tone: "focus",
        meaning: "本益比在區間內，股價走在均線上方，上漲有獲利預估支撐",
        caution: "留意本益比是否逼近區間上緣，越靠近上緣，再往上的空間越小",
    },
    "repair-low": {
        name: "價值探底",
        tone: "check",
        meaning: "本益比已低於區間，股價卻仍在均線下方",
        caution: "便宜有時是市場預期 EPS 會下修，等走勢止穩、預估沒有往下調再評估",
    },
    "ma-low": {
        name: "價值盤整",
        tone: "focus",
        meaning: "本益比低於區間，股價在均線附近整理，估值提供下檔緩衝",
        caution: "可留意股價能否帶量站穩均線，轉為上行時估值與走勢同時有利",
    },
    "strong-low": {
        name: "價值轉強",
        tone: "focus",
        meaning: "股價已站上均線，本益比仍低於區間，獲利預估成長得比股價快",
        caution: "這格通常檔數少，先確認不是短線急漲，也要確認預估 EPS 是否可信",
    },
}

/** 矩陣由左上到右下的順序，落點變化清單也照這個順序排 */
const CELL_ORDER: CellKey[] = LEVEL_ROWS.flatMap((level) => ZONE_COLS.map((zone) => `${zone}-${level}` as CellKey))
const ZONE_ORDER: Record<PriceZone, number> = { repair: 0, ma: 1, strong: 2 }

const ALL = "全部"
const DEFAULT_THEME = "晶圓代工"
/** 落點變化的比較間隔：取選定日期往前至少這麼多個日曆日的快照 */
const COMPARE_DAYS = 7

const index = ref<ValuationIndex | null>(null)
const snapshot = ref<ValuationSnapshot | null>(null)
const compareSnapshot = ref<ValuationSnapshot | null>(null)
const selectedDate = ref("")
const error = ref<string | null>(null)
const year = ref("")
const theme = ref(ALL)
const query = ref("")

type SortKey =
    | "code"
    | "segment"
    | "close"
    | "change_pct"
    | "dist_ma_pct"
    | "zone"
    | `pe:${string}`
    | `val:${string}`
    | `pos:${string}`
const sortKey = ref<SortKey>("dist_ma_pct")
const sortDesc = ref(true)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    if (index.value && !index.value.dates.length) {
        return "尚無 EPS 共識資料"
    }
    if (!snapshot.value) {
        return "載入中"
    }
    return `收盤 ${formatDate(snapshot.value.date)}，EPS 共識 ${formatDate(snapshot.value.estimate_date)}`
})

const years = computed(() => snapshot.value?.years ?? [])

/** 另一個年度，用來標示兩年落點不同的個股 */
const otherYear = computed(() => years.value.find((y) => y !== year.value) ?? null)

/** 與題材分類頁相同的順序 */
const themes = computed(() => [ALL, ...(index.value?.themes ?? [])])

/** EPS 共識開始累積的日期 */
const firstEstimateDate = computed(() => {
    const dates = index.value?.dates ?? []
    return dates[dates.length - 1]?.estimate_date ?? null
})

const keyword = computed(() => query.value.trim().toLowerCase())

function matches(stock: ValuationStock): boolean {
    // 只要分類表中出現在這個題材就列入，不限主要環節
    if (theme.value !== ALL && !stock.themes.includes(theme.value)) {
        return false
    }
    if (!keyword.value) {
        return true
    }
    return (
        stock.code.includes(keyword.value)
        || (stock.name ?? "").toLowerCase().includes(keyword.value)
        || stock.segment.toLowerCase().includes(keyword.value)
    )
}

const filtered = computed<ValuationStock[]>(() => (snapshot.value?.stocks ?? []).filter(matches))

function yearOf(stock: ValuationStock | null | undefined, y: string | null): ValuationYear | null {
    return stock && y ? stock.years[y] ?? null : null
}

function cellKey(stock: ValuationStock | null | undefined, y: string): CellKey | null {
    const level = yearOf(stock, y)?.valuation
    return stock?.zone && level ? `${stock.zone}-${level}` : null
}

function cellStocks(zone: PriceZone, level: ValuationLevel): ValuationStock[] {
    return filtered.value
        .filter((s) => s.zone === zone && yearOf(s, year.value)?.valuation === level)
        .sort((a, b) => (b.dist_ma_pct ?? 0) - (a.dist_ma_pct ?? 0))
}

const levelCounts = computed(() => {
    const counts: Record<ValuationLevel, number> = { low: 0, fair: 0, high: 0 }
    for (const stock of filtered.value) {
        const level = yearOf(stock, year.value)?.valuation
        if (level && stock.zone) {
            counts[level] += 1
        }
    }
    return counts
})

const zoneCounts = computed(() => {
    const counts: Record<PriceZone, number> = { strong: 0, ma: 0, repair: 0 }
    for (const stock of filtered.value) {
        if (stock.zone && yearOf(stock, year.value)?.valuation) {
            counts[stock.zone] += 1
        }
    }
    return counts
})

/** 選定年度沒有放進矩陣的檔數 (分析師不足、沒有預估、EPS 為負或沒有均線) */
const unplacedCount = computed(() => filtered.value.filter((s) => !cellKey(s, year.value)).length)

/** 另一個年度的估值判定；跟選定年度相同時回傳 null */
function otherLevel(stock: ValuationStock): ValuationLevel | null {
    const now = yearOf(stock, year.value)?.valuation
    const other = yearOf(stock, otherYear.value)?.valuation
    return now && other && now !== other ? other : null
}

/* ===== 近一週落點變化 ===== */

/** 選定日期往前至少 COMPARE_DAYS 天的快照；不足一週時取最早的一份 */
const compareDate = computed(() => {
    const current = selectedDate.value
    if (!current) {
        return null
    }
    const target = new Date(Date.UTC(+current.slice(0, 4), +current.slice(4, 6) - 1, +current.slice(6, 8)))
    target.setUTCDate(target.getUTCDate() - COMPARE_DAYS)
    const limit = target.toISOString().slice(0, 10).replaceAll("-", "")
    const earlier = (index.value?.dates ?? []).filter((d) => d.date < current)
    return (earlier.find((d) => d.date <= limit) ?? earlier[earlier.length - 1])?.date ?? null
})

interface CellChange {
    stock: ValuationStock
    before: ValuationStock | null
    fromKey: CellKey | null
    toKey: CellKey | null
    reasons: string[]
}

/** 選定年度在兩個快照間落點改變的個股，含新列入與移出矩陣 */
const changes = computed<CellChange[]>(() => {
    const prev = compareSnapshot.value
    const y = year.value
    if (!prev || !snapshot.value || !prev.years.includes(y)) {
        return []
    }
    const prevByCode = new Map(prev.stocks.map((s) => [s.code, s]))
    const result: CellChange[] = []
    for (const stock of filtered.value) {
        const before = prevByCode.get(stock.code) ?? null
        const fromKey = cellKey(before, y)
        const toKey = cellKey(stock, y)
        if (fromKey === toKey) {
            continue
        }
        const reasons: string[] = []
        if (before?.zone && stock.zone && before.zone !== stock.zone) {
            reasons.push(`走勢 ${ZONE_LABELS[before.zone]} → ${ZONE_LABELS[stock.zone]}`)
        }
        const beforeLevel = yearOf(before, y)?.valuation
        const nowLevel = yearOf(stock, y)?.valuation
        if (beforeLevel && nowLevel && beforeLevel !== nowLevel) {
            reasons.push(`估值 ${LEVEL_LABELS[beforeLevel]} → ${LEVEL_LABELS[nowLevel]}`)
        }
        if (!fromKey) {
            reasons.push("新列入")
        } else if (!toKey) {
            reasons.push(`移出 (${stock.zone ? skipText(yearOf(stock, y)) : "無均線"})`)
        }
        result.push({ stock, before, fromKey, toKey, reasons })
    }
    // 依現在的落點排序 (矩陣由左上到右下)，移出的排最後
    const order = (key: CellKey | null) => (key ? CELL_ORDER.indexOf(key) : CELL_ORDER.length)
    return result.sort((a, b) => order(a.toKey) - order(b.toKey))
})

/* ===== 顯示用 ===== */

function peText(item: ValuationYear | null): string {
    if (!item || item.pe === null) {
        return "--"
    }
    return `${item.pe.toFixed(1)}x`
}

function skipText(item: ValuationYear | null): string {
    if (!item) {
        return "無預估"
    }
    switch (item.reason) {
        case "few_analysts":
            return `分析師 ${item.analysts ?? 0} 位`
        case "negative_eps":
            return "EPS 為負"
        case "no_band":
            return "未設區間"
        default:
            return "無預估"
    }
}

function cellTitle(key: CellKey): string {
    const cell = CELLS[key]
    return `${cell.meaning}\n留意：${cell.caution}`
}

function stockTitle(stock: ValuationStock): string {
    const lines = [`${stock.code} ${stock.name ?? ""}`, `${stock.theme}／${stock.segment}`]
    for (const y of years.value) {
        const item = stock.years[y]
        if (item?.eps !== null && item?.eps !== undefined) {
            lines.push(`${y}：預估 EPS ${item.eps}，PE ${item.pe ?? "--"}x，分析師 ${item.analysts ?? "?"} 位`)
        } else {
            lines.push(`${y}：${skipText(item ?? null)}`)
        }
    }
    if (stock.band) {
        lines.push(`合理區間 ${stock.band[0]}～${stock.band[1]}x${stock.band_source === "stock" ? " (個股設定)" : ""}`)
    }
    if (stock.themes.length > 1) {
        lines.push(`出現在：${stock.themes.join("、")}`)
    }
    return lines.join("\n")
}

/** 本益比在合理區間中的位置：0% 為下緣、100% 為上緣，超出區間時小於 0 或大於 100 */
function bandPosition(stock: ValuationStock, y: string): number | null {
    const pe = stock.years[y]?.pe
    if (pe === null || pe === undefined || !stock.band) {
        return null
    }
    const [low, high] = stock.band
    return high > low ? ((pe - low) / (high - low)) * 100 : null
}

function positionText(value: number | null): string {
    return value === null ? "--" : `${Math.round(value)}%`
}

function changeClass(value: number | null): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

function pctText(value: number | null): string {
    return value === null ? "--" : `${signed(value)}%`
}

/* ===== 總表排序 ===== */

function sortValue(stock: ValuationStock, key: SortKey): number | string | null {
    if (key.startsWith("pe:")) {
        return stock.years[key.slice(3)]?.pe ?? null
    }
    if (key.startsWith("pos:")) {
        return bandPosition(stock, key.slice(4))
    }
    if (key.startsWith("val:")) {
        const item = stock.years[key.slice(4)]
        if (!item?.valuation || !stock.zone) {
            return null
        }
        return CELL_ORDER.indexOf(`${stock.zone}-${item.valuation}`)
    }
    if (key === "zone") {
        return stock.zone ? ZONE_ORDER[stock.zone] : null
    }
    return stock[key as "code" | "segment" | "close" | "change_pct" | "dist_ma_pct"]
}

const sortedRows = computed(() => {
    const rows = [...filtered.value]
    const dir = sortDesc.value ? -1 : 1
    return rows.sort((a, b) => {
        const va = sortValue(a, sortKey.value)
        const vb = sortValue(b, sortKey.value)
        // 沒有值的一律排最後，不受升降冪影響
        if (va === null || vb === null) {
            return va === vb ? 0 : va === null ? 1 : -1
        }
        if (typeof va === "string" || typeof vb === "string") {
            return String(va).localeCompare(String(vb), "zh-Hant") * dir
        }
        return (va - vb) * dir
    })
})

function sortBy(key: SortKey) {
    if (sortKey.value === key) {
        sortDesc.value = !sortDesc.value
    } else {
        sortKey.value = key
        // 文字與落點欄位預設升冪，數字欄位預設降冪
        sortDesc.value = !(key === "code" || key === "segment" || key.startsWith("val:"))
    }
}

function sortMark(key: SortKey): string {
    if (sortKey.value !== key) {
        return ""
    }
    return sortDesc.value ? "▼" : "▲"
}

/* ===== 載入 ===== */

async function loadSnapshot(date: string) {
    error.value = null
    try {
        snapshot.value = await loadValuationSnapshot(date)
        // 年底時今年的 EPS 已接近實際值，預設看明年；切換日期時盡量保留原本的年度
        if (!snapshot.value.years.includes(year.value)) {
            year.value = snapshot.value.years[snapshot.value.years.length - 1] ?? ""
        }
    } catch (err) {
        error.value = (err as Error).message
    }
}

async function loadCompare(date: string | null) {
    compareSnapshot.value = null
    if (!date) {
        return
    }
    try {
        compareSnapshot.value = await loadValuationSnapshot(date)
    } catch {
        // 比較用的快照載入失敗時只是不顯示落點變化，不影響矩陣
        compareSnapshot.value = null
    }
}

watch(selectedDate, (date) => {
    if (date && date !== snapshot.value?.date) {
        loadSnapshot(date)
    }
})

watch(compareDate, (date) => loadCompare(date))

onMounted(async () => {
    try {
        index.value = await loadValuation()
        if (index.value.themes.includes(DEFAULT_THEME)) {
            theme.value = DEFAULT_THEME
        }
        const latest = index.value.dates[0]
        if (latest) {
            selectedDate.value = latest.date
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
                <h1>估值趨勢矩陣</h1>
                <p class="subtitle">
                    把前瞻本益比放進所屬環節的合理區間，再對照股價與 60 日均線的距離，看估值和走勢各站在哪一邊
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div class="controls">
            <label class="control">
                <span class="control-label">日期</span>
                <select v-model="selectedDate">
                    <option v-for="item in index?.dates ?? []" :key="item.date" :value="item.date">
                        {{ formatDate(item.date) }}
                    </option>
                </select>
            </label>
            <div class="tabs" role="tablist" aria-label="會計年度">
                <button
                    v-for="y in years"
                    :key="y"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': year === y }"
                    role="tab"
                    @click="year = y"
                >
                    {{ y }} 年 EPS
                </button>
            </div>
            <label class="control">
                <span class="control-label">題材</span>
                <select v-model="theme">
                    <option v-for="name in themes" :key="name" :value="name">{{ name }}</option>
                </select>
            </label>
            <label class="control">
                <span class="control-label">查詢</span>
                <input v-model="query" class="search-input" type="search" placeholder="代號、名稱或環節">
            </label>
        </div>

        <section v-if="index && snapshot" class="panel" data-nav="矩陣">
            <div class="matrix-wrap">
                <div class="matrix">
                    <div class="y-caption">
                        <span>本益比相對合理區間</span>
                    </div>

                    <template v-for="(level, row) in LEVEL_ROWS" :key="level">
                        <div class="row-label" :style="{ gridRow: row + 1 }">
                            <strong>{{ LEVEL_LABELS[level] }}</strong>
                            <span>{{ LEVEL_NOTES[level] }}</span>
                            <span class="tally">{{ levelCounts[level] }} 檔</span>
                        </div>
                        <div
                            v-for="(zone, col) in ZONE_COLS"
                            :key="`${zone}-${level}`"
                            class="cell"
                            :class="`tone-${CELLS[`${zone}-${level}`].tone}`"
                            :style="{ gridRow: row + 1, gridColumn: col + 3 }"
                        >
                            <div class="cell-head" :title="cellTitle(`${zone}-${level}`)">
                                <strong>{{ CELLS[`${zone}-${level}`].name }}</strong>
                                <span class="cell-axis">{{ LEVEL_LABELS[level] }}・{{ ZONE_LABELS[zone] }}</span>
                                <span class="cell-count">{{ cellStocks(zone, level).length }}</span>
                            </div>
                            <ul v-if="cellStocks(zone, level).length" class="chips">
                                <li
                                    v-for="stock in cellStocks(zone, level)"
                                    :key="stock.code"
                                    class="chip"
                                    :title="stockTitle(stock)"
                                >
                                    <span class="chip-name">{{ stock.name }}</span>
                                    <span class="chip-pe">
                                        {{ peText(yearOf(stock, year)) }}<sup v-if="yearOf(stock, year)?.near_edge" class="chip-edge">邊</sup>
                                    </span>
                                    <span class="chip-dist" :class="changeClass(stock.dist_ma_pct)">
                                        {{ pctText(stock.dist_ma_pct) }}
                                    </span>
                                    <span v-if="otherLevel(stock)" class="chip-other">
                                        {{ otherYear }} {{ LEVEL_LABELS[otherLevel(stock)!] }}
                                    </span>
                                </li>
                            </ul>
                            <p v-else class="cell-empty">無個股</p>
                        </div>
                    </template>

                    <div
                        v-for="(zone, col) in ZONE_COLS"
                        :key="`label-${zone}`"
                        class="col-label"
                        :style="{ gridColumn: col + 3 }"
                    >
                        <strong>{{ ZONE_LABELS[zone] }}</strong>
                        <span v-if="zone === 'repair'">低於 -{{ index.zone_pct }}%</span>
                        <span v-else-if="zone === 'ma'">±{{ index.zone_pct }}% 以內</span>
                        <span v-else>高於 +{{ index.zone_pct }}%</span>
                        <span class="tally">{{ zoneCounts[zone] }} 檔</span>
                    </div>
                    <div class="x-caption">
                        <span>弱</span>
                        <span>收盤距 {{ index.ma_days }} 日均線</span>
                        <span>強</span>
                    </div>
                </div>
            </div>

            <ul class="legend">
                <li>
                    每檔顯示 {{ year }} 年前瞻本益比與距均線，<span class="val-buy">紅字</span>在均線之上、<span class="val-sell">綠字</span>在均線之下
                </li>
                <li>
                    <sup class="chip-edge">邊</sup> 本益比距合理區間邊界 {{ index.edge_pct }}% 以內，股價小幅變動就可能換到相鄰的格子
                </li>
                <li v-if="otherYear">
                    <span class="chip-other">{{ otherYear }} 便宜</span> 改用 {{ otherYear }} 年 EPS 計算時的估值不同
                </li>
                <li>
                    分析師少於 {{ index.min_analysts }} 位、沒有預估或 EPS 為負的個股不放進矩陣，目前 {{ unplacedCount }} 檔，可在總表查看原因
                </li>
            </ul>

            <details class="guide">
                <summary>各格狀態說明</summary>
                <p class="guide-intro">
                    縱軸看估值：前瞻本益比跟所屬環節的合理區間比，越上面越貴。
                    橫軸看走勢：收盤跟 {{ index.ma_days }} 日均線比，越右邊越強。
                    右下角是估值與走勢都有利的位置，左上角則兩者都不利。滑鼠移到格子標題上也能看到說明。
                </p>
                <div class="guide-wrap">
                    <table class="data-table guide-table">
                        <thead>
                            <tr>
                                <th>狀態</th>
                                <th>估值・走勢</th>
                                <th>代表什麼</th>
                                <th>留意</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="key in [...CELL_ORDER].reverse()" :key="key">
                                <td class="guide-name">
                                    <span class="tone-mark" :class="`tone-${CELLS[key].tone}`">{{ CELLS[key].name }}</span>
                                    <span class="guide-tone">{{ TONE_LABELS[CELLS[key].tone] }}</span>
                                </td>
                                <td class="guide-axis">
                                    {{ LEVEL_LABELS[key.split("-")[1] as ValuationLevel] }}・{{ ZONE_LABELS[key.split("-")[0] as PriceZone] }}
                                </td>
                                <td>{{ CELLS[key].meaning }}</td>
                                <td>{{ CELLS[key].caution }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <ul class="guide-notes">
                    <li>合理區間是人工設定的，判定是否可靠取決於區間設得合不合理</li>
                    <li>景氣循環股 (例如記憶體) 在獲利高峰時本益比特別低，看起來便宜，其實可能接近景氣頂點</li>
                    <li>改用明年 EPS 後變便宜，通常代表預估明年獲利大幅成長，要等成長兌現</li>
                    <li>矩陣只是篩選工具，不構成投資建議</li>
                </ul>
            </details>
        </section>

        <section v-if="index && snapshot" class="panel" data-nav="近一週落點變化">
            <div class="panel-head">
                <h2>近一週落點變化</h2>
                <p v-if="compareSnapshot" class="panel-note">
                    {{ year }} 年 EPS，{{ formatDate(compareSnapshot.date) }} → {{ formatDate(snapshot.date) }}，
                    {{ theme === ALL ? "全部題材" : theme }}共 {{ changes.length }} 檔改變
                </p>
            </div>
            <p v-if="!compareDate" class="notice">
                EPS 共識從 {{ formatDate(firstEstimateDate) }} 開始每天累積，至少要有兩個日期才能比較
            </p>
            <p v-else-if="compareSnapshot && !compareSnapshot.years.includes(year)" class="notice">
                {{ formatDate(compareSnapshot.date) }} 的快照沒有 {{ year }} 年的預估，無法比較
            </p>
            <p v-else-if="compareSnapshot && !changes.length" class="notice">這段期間沒有個股改變落點</p>
            <div v-else-if="changes.length" class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號／名稱</th>
                            <th>落點變化</th>
                            <th>原因</th>
                            <th class="num">{{ year }} PE</th>
                            <th class="num">距均線</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="item in changes" :key="item.stock.code" :title="stockTitle(item.stock)">
                            <td class="nowrap"><span class="code">{{ item.stock.code }}</span>{{ item.stock.name }}</td>
                            <td class="nowrap">
                                <span v-if="item.fromKey" class="muted">{{ CELLS[item.fromKey].name }}</span>
                                <span v-else class="muted">未列入</span>
                                <span class="arrow">→</span>
                                <span v-if="item.toKey" class="tone-mark" :class="`tone-${CELLS[item.toKey].tone}`">
                                    {{ CELLS[item.toKey].name }}
                                </span>
                                <span v-else class="muted">移出</span>
                            </td>
                            <td>{{ item.reasons.join("，") }}</td>
                            <td class="num nowrap">
                                {{ peText(yearOf(item.before, year)) }} → {{ peText(yearOf(item.stock, year)) }}
                            </td>
                            <td class="num nowrap">
                                {{ pctText(item.before?.dist_ma_pct ?? null) }} →
                                <span :class="changeClass(item.stock.dist_ma_pct)">{{ pctText(item.stock.dist_ma_pct) }}</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section v-if="index && snapshot" class="panel" data-nav="個股估值總表">
            <div class="panel-head">
                <h2>個股估值總表</h2>
                <p class="panel-note">
                    點欄位標題可排序。本益比 = 收盤 ÷ 分析師共識 EPS；區間位置 0% 為合理區間下緣、100% 為上緣
                </p>
            </div>
            <div class="table-wrap">
                <table class="data-table detail-table">
                    <thead>
                        <tr>
                            <th class="sortable" @click="sortBy('code')">代號／名稱 {{ sortMark("code") }}</th>
                            <th class="sortable" @click="sortBy('segment')">環節 {{ sortMark("segment") }}</th>
                            <th class="num sortable" @click="sortBy('close')">收盤 {{ sortMark("close") }}</th>
                            <th class="num sortable" @click="sortBy('change_pct')">漲跌 {{ sortMark("change_pct") }}</th>
                            <th class="num sortable" @click="sortBy('dist_ma_pct')">距均線 {{ sortMark("dist_ma_pct") }}</th>
                            <th class="num">合理區間</th>
                            <template v-for="y in years" :key="y">
                                <th class="num sortable" :class="{ 'is-current': y === year }" @click="sortBy(`pe:${y}`)">
                                    {{ y }} PE {{ sortMark(`pe:${y}`) }}
                                </th>
                                <th class="num sortable" :class="{ 'is-current': y === year }" @click="sortBy(`pos:${y}`)">
                                    區間位置 {{ sortMark(`pos:${y}`) }}
                                </th>
                                <th class="sortable" :class="{ 'is-current': y === year }" @click="sortBy(`val:${y}`)">
                                    {{ y }} 狀態 {{ sortMark(`val:${y}`) }}
                                </th>
                            </template>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="stock in sortedRows" :key="stock.code" :title="stockTitle(stock)">
                            <td class="nowrap"><span class="code">{{ stock.code }}</span>{{ stock.name }}</td>
                            <td class="segment-cell">{{ stock.segment }}</td>
                            <td class="num">{{ stock.close.toLocaleString() }}</td>
                            <td class="num" :class="changeClass(stock.change_pct)">{{ pctText(stock.change_pct) }}</td>
                            <td class="num" :class="changeClass(stock.dist_ma_pct)">{{ pctText(stock.dist_ma_pct) }}</td>
                            <td class="num nowrap">
                                <template v-if="stock.band">
                                    {{ stock.band[0] }}～{{ stock.band[1] }}x<span v-if="stock.band_source === 'stock'" class="muted">*</span>
                                </template>
                                <span v-else class="muted">--</span>
                            </td>
                            <template v-for="y in years" :key="y">
                                <td class="num" :class="{ muted: !stock.years[y]?.valuation }">
                                    {{ peText(stock.years[y] ?? null) }}
                                </td>
                                <td class="num" :class="stock.years[y]?.valuation ? `level-text-${stock.years[y].valuation}` : 'muted'">
                                    {{ positionText(bandPosition(stock, y)) }}
                                </td>
                                <td class="nowrap">
                                    <span
                                        v-if="cellKey(stock, y)"
                                        class="tone-mark"
                                        :class="`tone-${CELLS[cellKey(stock, y)!].tone}`"
                                        :title="cellTitle(cellKey(stock, y)!)"
                                    >
                                        {{ CELLS[cellKey(stock, y)!].name }}
                                    </span>
                                    <span v-else class="muted">{{ stock.zone ? skipText(stock.years[y] ?? null) : "無均線" }}</span>
                                </td>
                            </template>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p v-if="!sortedRows.length" class="notice">找不到符合的個股</p>
        </section>

        <p v-if="index" class="panel-note foot">
            EPS 共識來自 Yahoo Finance，與其他券商共識來源可能不同。Yahoo 只提供今年與明年兩個會計年度，
            也沒有歷史資料，可選日期從 {{ formatDate(firstEstimateDate) }} 開始每天累積。
            合理區間依環節人工設定 (data/valuation_bands.json，{{ index.bands_updated }} 更新)，標 * 的為個股另外設定；
            個股出現在多個環節時，採關聯度最高的環節。判定僅供篩選參考，不構成投資建議。
        </p>
    </section>
</template>

<style scoped>
.search-input {
    width: 180px;
    padding: 5px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-1);
    color: var(--text-primary);
    font-family: inherit;
    font-size: 13px;
}

.search-input:focus {
    outline: none;
    border-color: var(--text-muted);
}

/* ===== 狀態色調：以左側色條與淡底色區分，文字一律標示狀態名稱 ===== */

.tone-focus {
    --tone: var(--series-foreign);
}

.tone-check {
    --tone: var(--series-trust);
}

.tone-neutral {
    --tone: var(--text-muted);
}

.tone-weak {
    --tone: var(--text-primary);
}

/* ===== 矩陣 ===== */

/* 依矩陣本身的寬度切換版面，側欄展開或視窗縮小時都適用 */
.matrix-wrap {
    container-type: inline-size;
}

.matrix {
    display: grid;
    grid-template-columns: 22px 88px repeat(3, minmax(0, 1fr));
    grid-template-rows: repeat(3, auto) auto auto;
    gap: 0;
    border-left: 2px solid var(--text-secondary);
}

.y-caption {
    grid-row: 1 / 4;
    grid-column: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 12px;
    letter-spacing: 2px;
}

.y-caption span {
    /* 中文直書由上而下閱讀，英數字保持橫排 */
    writing-mode: vertical-rl;
    text-orientation: mixed;
}

.row-label {
    grid-column: 2;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    padding: 8px 10px 8px 0;
    text-align: right;
}

.row-label strong {
    font-size: 16px;
}

.row-label span {
    color: var(--text-muted);
    font-size: 11px;
}

.tally {
    color: var(--text-secondary) !important;
    font-variant-numeric: tabular-nums;
}

.cell {
    min-width: 0;
    margin: 0 0 -1px -1px;
    padding: 10px 12px 12px;
    border: 1px solid var(--border);
    border-left: 3px solid var(--tone);
    background: color-mix(in srgb, var(--tone) 6%, var(--surface-1));
}

.cell-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
    cursor: help;
}

.cell-head strong {
    color: var(--tone);
    font-size: 14px;
}

.cell-axis {
    display: none;
    color: var(--text-muted);
    font-size: 12px;
}

.cell-count {
    margin-left: auto;
    color: var(--text-muted);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}

.chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
}

.chip {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    max-width: 100%;
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-1);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}

/* 格子窄時寧可讓標籤換行，也不截斷股名 */
.chip {
    flex-wrap: wrap;
}

.chip-name {
    flex-shrink: 0;
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
}

.chip-pe {
    color: var(--text-secondary);
    white-space: nowrap;
}

.chip-dist {
    white-space: nowrap;
}

.chip-edge {
    margin-left: 1px;
    color: var(--series-trust);
    font-size: 10px;
    font-weight: 600;
}

.chip-other {
    padding: 0 4px;
    border-radius: 3px;
    background: var(--neutral);
    color: var(--text-secondary);
    font-size: 11px;
    white-space: nowrap;
}

.cell-empty {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 12px;
}

.col-label {
    grid-row: 4;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1px;
    padding: 8px 4px 2px;
    border-top: 2px solid var(--text-secondary);
}

.col-label strong {
    font-size: 15px;
}

.col-label span {
    color: var(--text-muted);
    font-size: 11px;
}

.x-caption {
    grid-row: 5;
    grid-column: 3 / 6;
    display: flex;
    justify-content: space-between;
    padding: 4px 4px 0;
    color: var(--text-muted);
    font-size: 12px;
}

.x-caption span:first-child::before {
    content: "← ";
}

.x-caption span:last-child::after {
    content: " →";
}

/* ===== 圖例與說明 ===== */

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 20px;
    margin: 14px 0 0;
    padding: 0;
    color: var(--text-secondary);
    font-size: 12px;
    list-style: none;
}

.guide {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
}

.guide summary {
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
}

.guide summary:hover {
    color: var(--text-primary);
}

.guide-intro {
    margin: 10px 0 8px;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

/* 只橫向捲動，不像共用的 table-wrap 限制高度 */
.guide-wrap {
    overflow-x: auto;
}

/* 固定欄寬；共用表格預設不換行，說明文字要換行才不會擠出版面 */
.guide-table {
    width: 100%;
    min-width: 640px;
    table-layout: fixed;
    font-size: 13px;
}

.guide-table th:nth-child(1) {
    width: 150px;
}

.guide-table th:nth-child(2) {
    width: 120px;
}

.guide-table td {
    vertical-align: top;
    white-space: normal;
}

.guide-table td.guide-name,
.guide-table td.guide-axis {
    white-space: nowrap;
}

.guide-tone {
    display: block;
    color: var(--text-muted);
    font-size: 11px;
}

.guide-notes {
    margin: 12px 0 0;
    padding-left: 18px;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.8;
}

/* 狀態名稱：前面一個色條，顏色只是輔助 */
.tone-mark {
    padding-left: 7px;
    border-left: 3px solid var(--tone);
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
}

/* ===== 表格 ===== */

.arrow {
    margin: 0 6px;
    color: var(--text-muted);
}

.detail-table th.sortable {
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}

.detail-table th.sortable:hover {
    color: var(--text-primary);
}

.detail-table th.is-current {
    color: var(--text-primary);
}

.nowrap {
    white-space: nowrap;
}

.code {
    margin-right: 6px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
}

.segment-cell {
    min-width: 96px;
    color: var(--text-secondary);
}

.level-text-low {
    color: var(--sell);
}

.level-text-fair {
    color: var(--text-primary);
}

.level-text-high {
    color: var(--buy);
}

.muted {
    color: var(--text-muted);
}

.foot {
    margin-top: 4px;
}

/*
 * 每格太窄時股名會被擠掉，改為卡片排列，每格自己標示估值與走勢。
 * 卡片依矩陣由左上到右下的順序排列。
 */
@container (max-width: 720px) {
    .matrix {
        grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr));
        grid-template-rows: none;
        gap: 8px;
        border-left: 0;
    }

    .y-caption,
    .row-label,
    .col-label,
    .x-caption {
        display: none;
    }

    .cell {
        grid-row: auto !important;
        grid-column: auto !important;
        margin: 0;
    }

    .cell-axis {
        display: inline;
    }
}
</style>
