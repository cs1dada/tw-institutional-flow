<script setup lang="ts">
/**
 * 估值九宮格：前瞻本益比 × 股價相對季線的位置。
 *
 * 橫軸是前瞻本益比與所屬環節合理區間的比較 (相對低估／合理／相對高估)，
 * 縱軸是收盤相對 60 日均線的距離 (強勢區／季線區／修復區)，九格各有一個操作提示。
 * 判定都在後端算好 (app/services/valuation_grid.py)，這裡只負責呈現、切換日期與年度、篩選，
 * 以及比較選定日期與約一週前的快照，列出換格的個股。
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

interface Axis<T> {
    key: T
    label: string
}

interface CellDef {
    name: string
    action: string
    /** good：值得留意；warn：要驗證；avoid：避開；plain：觀望 */
    tone: "good" | "warn" | "avoid" | "plain"
}

type CellKey = `${PriceZone}-${ValuationLevel}`

const LEVELS: Axis<ValuationLevel>[] = [
    { key: "low", label: "相對低估" },
    { key: "fair", label: "合理估值" },
    { key: "high", label: "相對高估" },
]

const LEVEL_LABELS: Record<ValuationLevel, string> = { low: "相對低估", fair: "合理估值", high: "相對高估" }

const ZONES: Axis<PriceZone>[] = [
    { key: "strong", label: "強勢區" },
    { key: "ma", label: "季線區" },
    { key: "repair", label: "修復區" },
]

const ZONE_LABELS: Record<PriceZone, string> = { strong: "強勢區", ma: "季線區", repair: "修復區" }

/** 依九宮格由左上到右下的順序，換格清單也照這個順序排 */
const CELLS: Record<CellKey, CellDef> = {
    "strong-low": { name: "拉回候選", action: "接", tone: "good" },
    "strong-fair": { name: "趨勢持有", action: "拿", tone: "good" },
    "strong-high": { name: "高預期", action: "跟", tone: "warn" },
    "ma-low": { name: "突破候選", action: "攻", tone: "good" },
    "ma-fair": { name: "等待表態", action: "看", tone: "plain" },
    "ma-high": { name: "突破確認", action: "驗", tone: "warn" },
    "repair-low": { name: "修復候選", action: "等", tone: "good" },
    "repair-fair": { name: "等待止跌", action: "守", tone: "plain" },
    "repair-high": { name: "低優先區", action: "避", tone: "avoid" },
}

const CELL_ORDER = Object.keys(CELLS)
const ZONE_ORDER: Record<PriceZone, number> = { strong: 0, ma: 1, repair: 2 }
const LEVEL_ORDER: Record<ValuationLevel, number> = { low: 0, fair: 1, high: 2 }

const ALL = "全部"
const DEFAULT_THEME = "晶圓代工"
/** 換格比較的間隔：取選定日期往前至少這麼多個日曆日的快照 */
const COMPARE_DAYS = 7

const index = ref<ValuationIndex | null>(null)
const snapshot = ref<ValuationSnapshot | null>(null)
const compareSnapshot = ref<ValuationSnapshot | null>(null)
const selectedDate = ref("")
const error = ref<string | null>(null)
const year = ref("")
const theme = ref(ALL)
const query = ref("")

type SortKey = "code" | "segment" | "close" | "change_pct" | "dist_ma_pct" | "zone" | `pe:${string}` | `val:${string}`
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

/** 另一個年度，用來標示換格的個股 */
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

/** 選定年度沒有進九宮格的檔數 (分析師不足、沒有預估、EPS 為負或沒有季線) */
const unplacedCount = computed(() => filtered.value.filter((s) => !cellKey(s, year.value)).length)

/** 兩個年度的估值判定不同，代表成長消化後位置會移動 */
function moves(stock: ValuationStock): boolean {
    const now = yearOf(stock, year.value)?.valuation
    const other = yearOf(stock, otherYear.value)?.valuation
    return Boolean(now && other && now !== other)
}

/* ===== 本週換格 ===== */

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
    from: CellDef | null
    to: CellDef | null
    reasons: string[]
}

/** 選定年度在兩個快照間換格的個股，含新列入與移出九宮格 */
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
            reasons.push(`位階 ${ZONE_LABELS[before.zone]} → ${ZONE_LABELS[stock.zone]}`)
        }
        const beforeLevel = yearOf(before, y)?.valuation
        const nowLevel = yearOf(stock, y)?.valuation
        if (beforeLevel && nowLevel && beforeLevel !== nowLevel) {
            reasons.push(`估值 ${LEVEL_LABELS[beforeLevel]} → ${LEVEL_LABELS[nowLevel]}`)
        }
        if (!fromKey) {
            reasons.push("新列入")
        } else if (!toKey) {
            reasons.push(`移出 (${stock.zone ? skipText(yearOf(stock, y)) : "無季線"})`)
        }
        result.push({
            stock,
            before,
            from: fromKey ? CELLS[fromKey] : null,
            to: toKey ? CELLS[toKey] : null,
            reasons,
        })
    }
    // 依換入的格子排序 (九宮格由左上到右下)，移出的排最後
    const order = (key: CellKey | null) => (key ? CELL_ORDER.indexOf(key) : CELL_ORDER.length)
    return result.sort((a, b) => order(cellKey(a.stock, y)) - order(cellKey(b.stock, y)))
})

/* ===== 顯示用 ===== */

function peText(item: ValuationYear | null): string {
    if (!item || item.pe === null) {
        return "--"
    }
    return `${item.near_edge ? "≈" : ""}${item.pe.toFixed(2)}x`
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

function cellOf(stock: ValuationStock, y: string): CellDef | null {
    const key = cellKey(stock, y)
    return key ? CELLS[key] : null
}

/**
 * 判定旁的小 bar：三等分為低估、合理、高估，標記本益比的位置。
 * 刻度範圍是合理區間往兩側各延伸一個區間寬度，超出時貼在兩端。
 */
function barPosition(stock: ValuationStock, y: string): number | null {
    const pe = stock.years[y]?.pe
    if (pe === null || pe === undefined || !stock.band) {
        return null
    }
    const [low, high] = stock.band
    const width = high - low
    const ratio = (pe - (low - width)) / (width * 3)
    return Math.min(1, Math.max(0, ratio)) * 100
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

/* ===== 明細表排序 ===== */

function sortValue(stock: ValuationStock, key: SortKey): number | string | null {
    if (key.startsWith("pe:")) {
        return stock.years[key.slice(3)]?.pe ?? null
    }
    if (key.startsWith("val:")) {
        const item = stock.years[key.slice(4)]
        if (!item?.valuation || !stock.zone) {
            return null
        }
        return LEVEL_ORDER[item.valuation] * 3 + ZONE_ORDER[stock.zone]
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
        // 文字欄位預設升冪，數字欄位預設降冪
        sortDesc.value = !(key === "code" || key === "segment" || key === "zone" || key.startsWith("val:"))
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
        // 比較用的快照載入失敗時只是不顯示換格，不影響九宮格
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
                <h1>估值九宮格</h1>
                <p class="subtitle">
                    前瞻本益比對照環節的合理區間，再看股價離季線多遠，判斷該接、該等還是該避
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
                    {{ y }} 年
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

        <section v-if="index && snapshot" class="panel" data-nav="九宮格">
            <div class="vgrid-wrap">
                <div class="vgrid">
                    <div class="corner">
                        <strong>{{ year }} 年</strong>
                        <span>前瞻本益比 →</span>
                        <span>距季線 ↓</span>
                    </div>
                    <div v-for="level in LEVELS" :key="level.key" class="col-head" :class="`level-${level.key}`">
                        {{ level.label }}
                        <span class="count">{{ levelCounts[level.key] }}</span>
                    </div>

                    <template v-for="zone in ZONES" :key="zone.key">
                        <div class="row-head">
                            <strong>{{ zone.label }}</strong>
                            <span v-if="zone.key === 'strong'">距季線 &gt; +{{ index.zone_pct }}%</span>
                            <span v-else-if="zone.key === 'ma'">距季線 ±{{ index.zone_pct }}% 以內</span>
                            <span v-else>距季線 &lt; -{{ index.zone_pct }}%</span>
                        </div>
                        <div v-for="level in LEVELS" :key="`${zone.key}-${level.key}`" class="cell">
                            <div class="cell-axis">{{ zone.label }} × {{ level.label }}</div>
                            <span class="cell-tag" :class="`tone-${CELLS[`${zone.key}-${level.key}`].tone}`">
                                {{ CELLS[`${zone.key}-${level.key}`].name }}
                                <span class="cell-action">{{ CELLS[`${zone.key}-${level.key}`].action }}</span>
                            </span>
                            <ul v-if="cellStocks(zone.key, level.key).length" class="cell-list">
                                <li
                                    v-for="stock in cellStocks(zone.key, level.key)"
                                    :key="stock.code"
                                    :class="{ moves: moves(stock) }"
                                    :title="stockTitle(stock)"
                                >
                                    <span class="cell-name">{{ stock.name }}</span>
                                    <span class="cell-pe" :class="{ edge: yearOf(stock, year)?.near_edge }">
                                        {{ peText(yearOf(stock, year)) }}
                                    </span>
                                    <span class="cell-dist" :class="changeClass(stock.dist_ma_pct)">
                                        {{ pctText(stock.dist_ma_pct) }}
                                    </span>
                                </li>
                            </ul>
                            <p v-else class="cell-empty">—</p>
                        </div>
                    </template>
                </div>
            </div>

            <ul class="legend">
                <li>
                    右欄數字為距季線 ({{ index.ma_days }} 日均線)，<span class="val-buy">紅字</span>在季線之上、<span class="val-sell">綠字</span>在季線之下
                </li>
                <li>
                    <span class="edge-sample">≈</span>本益比距合理區間邊界 {{ index.edge_pct }}% 以內，股價一動就可能換格
                </li>
                <li v-if="otherYear">
                    <span class="moves-sample">虛線框</span>{{ year }} 與 {{ otherYear }} 年的估值判定不同 (成長消化後會移動)
                </li>
                <li>
                    分析師少於 {{ index.min_analysts }} 位、沒有預估或 EPS 為負的個股不列入，目前 {{ unplacedCount }} 檔，可在下方明細表查看
                </li>
            </ul>
        </section>

        <section v-if="index && snapshot" class="panel" data-nav="本週換格">
            <div class="panel-head">
                <h2>本週換格</h2>
                <p v-if="compareSnapshot" class="panel-note">
                    {{ year }} 年判定，{{ formatDate(compareSnapshot.date) }} → {{ formatDate(snapshot.date) }}，
                    {{ theme === ALL ? "全部題材" : theme }}共 {{ changes.length }} 檔換格
                </p>
            </div>
            <p v-if="!compareDate" class="notice">
                EPS 共識從 {{ formatDate(firstEstimateDate) }} 開始每天累積，至少要有兩個日期才能比較換格
            </p>
            <p v-else-if="compareSnapshot && !compareSnapshot.years.includes(year)" class="notice">
                {{ formatDate(compareSnapshot.date) }} 的快照沒有 {{ year }} 年的預估，無法比較
            </p>
            <p v-else-if="compareSnapshot && !changes.length" class="notice">這段期間沒有個股換格</p>
            <div v-else-if="changes.length" class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號／名稱</th>
                            <th>原本</th>
                            <th>現在</th>
                            <th>原因</th>
                            <th class="num">{{ year }} PE</th>
                            <th class="num">距季線</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="item in changes" :key="item.stock.code" :title="stockTitle(item.stock)">
                            <td class="nowrap"><span class="code">{{ item.stock.code }}</span>{{ item.stock.name }}</td>
                            <td class="nowrap">
                                <span v-if="item.from" :class="`level-text-${yearOf(item.before, year)?.valuation}`">
                                    {{ item.from.name }}｜{{ item.from.action }}
                                </span>
                                <span v-else class="muted">未列入</span>
                            </td>
                            <td class="nowrap">
                                <span v-if="item.to" class="judge-tag" :class="`level-text-${yearOf(item.stock, year)?.valuation}`">
                                    {{ item.to.name }}｜{{ item.to.action }}
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

        <section v-if="index && snapshot" class="panel" data-nav="個股明細表">
            <div class="panel-head">
                <h2>個股明細表</h2>
                <p class="panel-note">點欄位標題可排序。本益比 = 收盤 ÷ 分析師共識 EPS，滑鼠移到個股上可看預估 EPS 與分析師人數</p>
            </div>
            <div class="table-wrap">
                <table class="data-table detail-table">
                    <thead>
                        <tr>
                            <th class="sortable" @click="sortBy('code')">代號／名稱 {{ sortMark("code") }}</th>
                            <th class="sortable" @click="sortBy('segment')">環節 {{ sortMark("segment") }}</th>
                            <th class="num sortable" @click="sortBy('close')">收盤 {{ sortMark("close") }}</th>
                            <th class="num sortable" @click="sortBy('change_pct')">漲跌 {{ sortMark("change_pct") }}</th>
                            <th class="num sortable" @click="sortBy('dist_ma_pct')">距季線 {{ sortMark("dist_ma_pct") }}</th>
                            <th class="sortable" @click="sortBy('zone')">位階 {{ sortMark("zone") }}</th>
                            <template v-for="y in years" :key="y">
                                <th class="num sortable" :class="{ 'is-current': y === year }" @click="sortBy(`pe:${y}`)">
                                    {{ y }} PE {{ sortMark(`pe:${y}`) }}
                                </th>
                                <th class="sortable" :class="{ 'is-current': y === year }" @click="sortBy(`val:${y}`)">
                                    {{ y }} 判定 {{ sortMark(`val:${y}`) }}
                                </th>
                            </template>
                            <th class="num">合理區間</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="stock in sortedRows" :key="stock.code" :title="stockTitle(stock)">
                            <td class="nowrap"><span class="code">{{ stock.code }}</span>{{ stock.name }}</td>
                            <td class="segment-cell">{{ stock.segment }}</td>
                            <td class="num">{{ stock.close.toLocaleString() }}</td>
                            <td class="num" :class="changeClass(stock.change_pct)">{{ pctText(stock.change_pct) }}</td>
                            <td class="num" :class="changeClass(stock.dist_ma_pct)">{{ pctText(stock.dist_ma_pct) }}</td>
                            <td>
                                <span v-if="stock.zone" class="zone-tag" :class="`zone-${stock.zone}`">{{ ZONE_LABELS[stock.zone] }}</span>
                                <span v-else class="muted">--</span>
                            </td>
                            <template v-for="y in years" :key="y">
                                <td class="num" :class="{ muted: !stock.years[y]?.valuation }">
                                    <span :class="{ edge: stock.years[y]?.near_edge }">{{ peText(stock.years[y] ?? null) }}</span>
                                </td>
                                <td class="judge-cell">
                                    <template v-if="cellOf(stock, y)">
                                        <span
                                            class="judge-tag"
                                            :class="`level-text-${stock.years[y].valuation}`"
                                            :title="LEVEL_LABELS[stock.years[y].valuation as ValuationLevel]"
                                        >
                                            {{ cellOf(stock, y)?.name }}｜{{ cellOf(stock, y)?.action }}
                                        </span>
                                        <span v-if="barPosition(stock, y) !== null" class="band-bar" aria-hidden="true">
                                            <span class="band-marker" :style="{ left: `${barPosition(stock, y)}%` }" />
                                        </span>
                                    </template>
                                    <span v-else class="muted">{{ stock.zone ? skipText(stock.years[y] ?? null) : "無季線" }}</span>
                                </td>
                            </template>
                            <td class="num nowrap">
                                <template v-if="stock.band">
                                    {{ stock.band[0] }}～{{ stock.band[1] }}x<span v-if="stock.band_source === 'stock'" class="muted">*</span>
                                </template>
                                <span v-else class="muted">--</span>
                            </td>
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

/* ===== 九宮格 ===== */

/* 依九宮格本身的寬度切換版面，側欄展開或視窗縮小時都適用 */
.vgrid-wrap {
    container-type: inline-size;
}

.vgrid {
    display: grid;
    grid-template-columns: 104px repeat(3, minmax(0, 1fr));
    gap: 8px;
}

.corner,
.col-head,
.row-head {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    text-align: center;
}

.corner {
    padding: 8px;
    background: var(--text-primary);
    color: var(--surface-1);
    font-size: 11px;
    line-height: 1.4;
}

.corner strong {
    font-size: 15px;
}

.col-head {
    flex-direction: row;
    gap: 8px;
    padding: 10px 8px;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
}

.level-low {
    background: var(--sell);
}

.level-fair {
    background: var(--text-primary);
    color: var(--surface-1);
}

.level-high {
    background: var(--buy);
}

.count {
    min-width: 22px;
    padding: 0 6px;
    border-radius: 999px;
    background: rgb(255 255 255 / 25%);
    font-size: 12px;
    font-weight: 400;
}

.row-head {
    gap: 2px;
    padding: 8px;
    border: 1px solid var(--border);
    background: var(--surface-0);
}

.row-head strong {
    font-size: 15px;
}

.row-head span {
    color: var(--text-muted);
    font-size: 11px;
}

.cell {
    min-width: 0;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-1);
}

.cell-axis {
    display: none;
    margin-bottom: 6px;
    color: var(--text-muted);
    font-size: 12px;
}

/* 提示以文字標示，顏色只是輔助 */
.cell-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
}

.cell-action {
    padding-left: 6px;
    border-left: 1px solid currentcolor;
}

.tone-good {
    border-color: #d9a520;
    color: #a67a00;
}

.tone-warn {
    border-color: var(--buy);
    color: var(--buy);
}

.tone-avoid {
    border-color: var(--buy);
    background: var(--buy);
    color: #fff;
}

.cell-list {
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
}

.cell-list li {
    display: grid;
    grid-template-columns: minmax(4em, 1fr) auto 64px;
    gap: 8px;
    padding: 2px 6px;
    border: 1px dashed transparent;
    border-radius: 4px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
}

.cell-list li.moves {
    border-color: var(--text-muted);
}

.cell-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.cell-pe,
.cell-dist {
    text-align: right;
}

.cell-empty {
    margin: 16px 0;
    color: var(--text-muted);
    text-align: center;
}

.edge {
    text-decoration: underline dotted;
    text-underline-offset: 3px;
}

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 20px;
    margin: 12px 0 0;
    padding: 0;
    color: var(--text-secondary);
    font-size: 12px;
    list-style: none;
}

.edge-sample {
    margin-right: 4px;
    font-weight: 600;
}

.moves-sample {
    margin-right: 4px;
    padding: 0 4px;
    border: 1px dashed var(--text-muted);
    border-radius: 3px;
}

/* ===== 明細表 ===== */

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

.zone-tag {
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 12px;
    white-space: nowrap;
}

.zone-strong {
    border-color: var(--buy);
    color: var(--buy);
}

.zone-repair {
    border-color: var(--sell);
    color: var(--sell);
}

.judge-cell {
    white-space: nowrap;
}

.judge-tag {
    margin-right: 8px;
    font-size: 13px;
    font-weight: 600;
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

/* 三等分：低估、合理、高估 */
.band-bar {
    position: relative;
    display: inline-block;
    width: 60px;
    height: 6px;
    border-radius: 3px;
    background: linear-gradient(
        to right,
        color-mix(in srgb, var(--sell) 35%, transparent) 0 33.3%,
        var(--neutral) 33.3% 66.6%,
        color-mix(in srgb, var(--buy) 35%, transparent) 66.6% 100%
    );
    vertical-align: middle;
}

.band-marker {
    position: absolute;
    top: -3px;
    width: 3px;
    height: 12px;
    margin-left: -1.5px;
    border-radius: 1px;
    background: var(--text-primary);
}

.muted {
    color: var(--text-muted);
}

.foot {
    margin-top: 4px;
}

/*
 * 每格少於約 200px 時股名會被擠掉，改為卡片排列，每格自己標示軸。
 * 卡片依九宮格由左上到右下的順序排列。
 */
@container (max-width: 840px) {
    .vgrid {
        grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr));
    }

    .corner,
    .col-head,
    .row-head {
        display: none;
    }

    .cell-axis {
        display: block;
    }
}
</style>
