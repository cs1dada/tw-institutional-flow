<script setup lang="ts">
/**
 * 題材分類：題材 → 環節 → 個股。
 *
 * 分類表 data/themes.json 由人工維護，一檔股票可以同時出現在多個題材或環節，
 * 每次出現各自標註關聯度。分類結構只載入一次，收盤、漲跌與主動式 ETF 持有檔數
 * 依選擇的揭露日另外載入，並列出 ETF 有持有、但分類表還沒收錄的個股。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadThemes, loadThemesSnapshot } from "@/api/dataSource"
import type { ThemeRelevance, ThemeStockInfo, ThemeStockQuote, ThemesData, ThemesSnapshot } from "@/types"
import { YI, formatDate, signed } from "@/utils/format"

const REL_LABELS: Record<ThemeRelevance, string> = {
    high: "高",
    mid: "中",
    low: "低",
}

const REL_ORDER: Record<ThemeRelevance, number> = { high: 0, mid: 1, low: 2 }

const ALL = "全部"

interface StockRow extends ThemeStockInfo, ThemeStockQuote {
    code: string
}

interface SegmentRow {
    id: string
    name: string
    description: string
    stocks: (StockRow & { rel: ThemeRelevance })[]
}

interface ThemeRow {
    id: string
    name: string
    group: string
    description: string
    stockCount: number
    etfValue: number
    segments: SegmentRow[]
}

const EMPTY_QUOTE: ThemeStockQuote = { close: null, change_pct: null, etf_holders: 0, etf_value: 0 }

const data = ref<ThemesData | null>(null)
const snapshot = ref<ThemesSnapshot | null>(null)
const selectedDate = ref("")
const error = ref<string | null>(null)
const group = ref(ALL)
const query = ref("")
const heldOnly = ref(false)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    if (!data.value || !snapshot.value) {
        return "載入中"
    }
    return `分類表更新於 ${data.value.updated}`
})

function stockRow(code: string): StockRow {
    const info = data.value?.stocks[code] ?? { name: null, industry: null }
    const quote = snapshot.value?.stocks[code] ?? EMPTY_QUOTE
    return { code, ...info, ...quote }
}

/** 分類結構接上當日數字，關聯度高的排前面，同等級依 ETF 持股市值排序 */
const themeRows = computed<ThemeRow[]>(() => {
    if (!data.value || !snapshot.value) {
        return []
    }
    return data.value.themes.map((theme) => {
        const codes = new Set<string>()
        const segments = theme.segments.map((segment) => {
            const stocks = segment.stocks
                .map((s) => ({ ...stockRow(s.code), rel: s.rel }))
                .sort((a, b) => REL_ORDER[a.rel] - REL_ORDER[b.rel] || b.etf_value - a.etf_value)
            stocks.forEach((s) => codes.add(s.code))
            return { id: segment.id, name: segment.name, description: segment.description, stocks }
        })
        const etfValue = [...codes].reduce((sum, code) => sum + (snapshot.value?.stocks[code]?.etf_value ?? 0), 0)
        return {
            id: theme.id,
            name: theme.name,
            group: theme.group,
            description: theme.description,
            stockCount: codes.size,
            etfValue,
            segments,
        }
    })
})

const groups = computed(() => {
    const seen: string[] = []
    for (const theme of data.value?.themes ?? []) {
        if (!seen.includes(theme.group)) {
            seen.push(theme.group)
        }
    }
    return [ALL, ...seen]
})

const keyword = computed(() => query.value.trim().toLowerCase())

function matches(stock: StockRow): boolean {
    if (heldOnly.value && !stock.etf_holders) {
        return false
    }
    if (!keyword.value) {
        return true
    }
    return stock.code.includes(keyword.value) || (stock.name ?? "").toLowerCase().includes(keyword.value)
}

/** 依大類、搜尋字與「只看 ETF 持有」篩選後的題材，沒有剩下個股的環節與題材一併隱藏 */
const visibleThemes = computed<ThemeRow[]>(() => {
    const result: ThemeRow[] = []
    for (const theme of themeRows.value) {
        if (group.value !== ALL && theme.group !== group.value) {
            continue
        }
        const segments = theme.segments
            .map((segment) => ({ ...segment, stocks: segment.stocks.filter(matches) }))
            .filter((segment) => segment.stocks.length)
        if (segments.length) {
            result.push({ ...theme, segments })
        }
    }
    return result
})

/** 搜尋個股時，彙整它出現在哪些題材與環節 */
const memberships = computed(() => {
    if (!keyword.value) {
        return []
    }
    const found = new Map<string, { stock: StockRow; places: string[] }>()
    for (const theme of themeRows.value) {
        for (const segment of theme.segments) {
            for (const stock of segment.stocks) {
                if (!matches(stock)) {
                    continue
                }
                const item = found.get(stock.code) ?? { stock, places: [] }
                item.places.push(`${theme.name}／${segment.name} (${REL_LABELS[stock.rel]})`)
                found.set(stock.code, item)
            }
        }
    }
    return [...found.values()]
})

const unclassifiedRows = computed<StockRow[]>(() =>
    (snapshot.value?.unclassified ?? []).map((item) => ({
        ...item,
        ...(snapshot.value?.stocks[item.code] ?? EMPTY_QUOTE),
    })),
)

const visibleUnclassified = computed(() => (group.value === ALL ? unclassifiedRows.value.filter(matches) : []))

const totalStocks = computed(() => Object.keys(data.value?.stocks ?? {}).length)

function dateLabel(item: { date: string; etf_count: number }): string {
    return `${formatDate(item.date)} (${item.etf_count} 檔 ETF)`
}

function toYiText(value: number): string {
    return (value / YI).toFixed(0)
}

function changeClass(value: number | null): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

async function loadSnapshot(date: string) {
    error.value = null
    try {
        snapshot.value = await loadThemesSnapshot(date)
    } catch (err) {
        error.value = (err as Error).message
    }
}

watch(selectedDate, (date) => {
    if (date && date !== snapshot.value?.date) {
        loadSnapshot(date)
    }
})

onMounted(async () => {
    try {
        data.value = await loadThemes()
        const latest = data.value.dates[0]
        if (latest) {
            selectedDate.value = latest.date
            await loadSnapshot(latest.date)
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
                <h1>題材分類</h1>
                <p class="subtitle">
                    依供應鏈環節整理的個股分類，比證交所產業別細。一檔股票可以同時屬於多個題材
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div v-if="data" class="quote-grid theme-tiles">
            <div class="quote-card">
                <div class="quote-name">題材</div>
                <div class="quote-value">{{ data.themes.length }}</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">已分類個股</div>
                <div class="quote-value">{{ totalStocks }}</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">ETF 持有但未分類</div>
                <div class="quote-value">{{ snapshot?.unclassified.length ?? "--" }}</div>
            </div>
        </div>

        <div class="controls">
            <label class="control">
                <span class="control-label">揭露日</span>
                <select v-model="selectedDate">
                    <option v-for="item in data?.dates ?? []" :key="item.date" :value="item.date">
                        {{ dateLabel(item) }}
                    </option>
                </select>
            </label>
            <div class="tabs theme-groups" role="tablist">
                <button
                    v-for="name in groups"
                    :key="name"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': group === name }"
                    role="tab"
                    @click="group = name"
                >
                    {{ name }}
                </button>
            </div>
            <label class="control">
                <span class="control-label">查詢個股</span>
                <input v-model="query" class="search-input" type="search" placeholder="代號或名稱">
            </label>
            <label class="control control-inline">
                <input v-model="heldOnly" type="checkbox">
                只看主動式 ETF 有持有的
            </label>
        </div>

        <div v-if="data" class="legend">
            <span class="legend-title">關聯度</span>
            <span v-for="(desc, rel) in data.relevance" :key="rel" class="legend-item">
                <span class="rel" :class="`rel-${rel}`">{{ REL_LABELS[rel] }}</span>{{ desc }}
            </span>
            <span v-if="snapshot" class="legend-item legend-etf">
                「ETF 持有檔數」為 {{ formatDate(snapshot.date) }} 持有這檔股票的主動式 ETF 檔數 (共 {{ snapshot.etf_count }} 檔)
            </span>
        </div>

        <div v-if="memberships.length" class="notice memberships">
            <div v-for="item in memberships" :key="item.stock.code" class="membership">
                <strong>{{ item.stock.code }} {{ item.stock.name }}</strong>
                <span class="muted">{{ item.stock.industry }}</span>
                <span>出現在 {{ item.places.length }} 處：{{ item.places.join("、") }}</span>
            </div>
        </div>

        <p v-if="snapshot && !visibleThemes.length && !visibleUnclassified.length" class="notice">
            找不到符合的個股
        </p>

        <section
            v-for="theme in visibleThemes"
            :id="`theme-${theme.id}`"
            :key="theme.id"
            class="panel"
            :data-nav="theme.name"
        >
            <div class="panel-head theme-head">
                <div>
                    <h2>
                        {{ theme.name }}
                        <span class="theme-group">{{ theme.group }}</span>
                    </h2>
                    <p class="panel-note">{{ theme.description }}</p>
                </div>
                <div class="theme-stats">
                    <span>{{ theme.stockCount }} 檔</span>
                    <span>ETF 持股 {{ toYiText(theme.etfValue) }} 億</span>
                </div>
            </div>

            <div class="segments">
                <div v-for="segment in theme.segments" :key="segment.id" class="segment">
                    <div class="segment-head">
                        <h3>{{ segment.name }}</h3>
                        <p>{{ segment.description }}</p>
                    </div>
                    <table class="data-table stock-table">
                        <thead>
                            <tr>
                                <th>關聯</th>
                                <th>個股</th>
                                <th class="num">收盤</th>
                                <th class="num">漲跌</th>
                                <th class="num">ETF 持有檔數</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="stock in segment.stocks" :key="stock.code" :title="stock.industry ?? ''">
                                <td><span class="rel" :class="`rel-${stock.rel}`">{{ REL_LABELS[stock.rel] }}</span></td>
                                <td class="stock-name">
                                    <span class="code">{{ stock.code }}</span>{{ stock.name }}
                                </td>
                                <td class="num">{{ stock.close?.toLocaleString() ?? "--" }}</td>
                                <td class="num" :class="changeClass(stock.change_pct)">
                                    {{ signed(stock.change_pct) }}{{ stock.change_pct === null ? "" : "%" }}
                                </td>
                                <td class="num" :class="{ muted: !stock.etf_holders }">{{ stock.etf_holders || "-" }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <section v-if="visibleUnclassified.length" class="panel" data-nav="尚未分類">
            <div class="panel-head">
                <h2>尚未分類</h2>
                <p class="panel-note">主動式 ETF 有持有，但分類表還沒收錄的個股，依 ETF 持股市值排序</p>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>名稱</th><th>證交所產業別</th>
                            <th class="num">收盤</th>
                            <th class="num">漲跌</th>
                            <th class="num">ETF 持有檔數</th>
                            <th class="num">ETF 持股（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="stock in visibleUnclassified" :key="stock.code">
                            <td>{{ stock.code }}</td>
                            <td>{{ stock.name }}</td>
                            <td>{{ stock.industry }}</td>
                            <td class="num">{{ stock.close?.toLocaleString() ?? "--" }}</td>
                            <td class="num" :class="changeClass(stock.change_pct)">
                                {{ signed(stock.change_pct) }}{{ stock.change_pct === null ? "" : "%" }}
                            </td>
                            <td class="num">{{ stock.etf_holders }}</td>
                            <td class="num">{{ (stock.etf_value / YI).toFixed(1) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <p class="panel-note theme-foot">
            分類依各公司公開的主要產品人工整理，一檔股票出現在多個題材時，各題材的 ETF 持股市值會重複計算，不可加總。
            收盤與漲跌為 {{ formatDate(snapshot?.date) }}，漲跌相對前一交易日 {{ formatDate(snapshot?.prev_date) }}。
        </p>
    </section>
</template>

<style scoped>
.theme-tiles {
    margin-bottom: 16px;
}

.theme-groups {
    flex-wrap: wrap;
}

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

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    align-items: center;
    margin: -8px 0 16px;
    color: var(--text-secondary);
    font-size: 12px;
}

.legend-title {
    color: var(--text-muted);
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.legend-etf {
    color: var(--text-muted);
}

.memberships {
    margin-bottom: 16px;
}

.membership {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 10px;
}

.membership + .membership {
    margin-top: 6px;
}

.theme-head {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 24px;
    align-items: flex-start;
    justify-content: space-between;
}

.theme-group {
    margin-left: 8px;
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
    vertical-align: 2px;
}

.theme-stats {
    display: flex;
    gap: 16px;
    color: var(--text-secondary);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.segments {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
}

.segment {
    min-width: 0;
    padding: 12px 12px 6px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-0);
}

.segment-head {
    margin-bottom: 8px;
}

h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
}

.segment-head p {
    margin: 2px 0 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.5;
}

.stock-table {
    width: 100%;
    background: transparent;
}

.stock-table th,
.stock-table td {
    padding: 4px 6px;
}

.stock-name {
    white-space: nowrap;
}

.code {
    margin-right: 6px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
}

/* 關聯度以文字標示，顏色只是輔助，不依賴色彩辨識 */
.rel {
    display: inline-block;
    min-width: 22px;
    padding: 0 5px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 12px;
    text-align: center;
}

.rel-high {
    background: var(--text-primary);
    border-color: var(--text-primary);
    color: var(--surface-1);
}

.rel-mid {
    background: var(--surface-1);
    border-color: var(--text-muted);
    color: var(--text-primary);
}

.rel-low {
    background: transparent;
    color: var(--text-muted);
    border-style: dashed;
}

.muted {
    color: var(--text-muted);
}

.theme-foot {
    margin-top: 4px;
}
</style>
