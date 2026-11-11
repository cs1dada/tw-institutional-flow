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

import { loadHolders, loadHoldersStock, loadHoldersWeek } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import HoldersLevelChart from "@/components/HoldersLevelChart.vue"
import HoldersScatter from "@/components/HoldersScatter.vue"
import HoldersTrendChart from "@/components/HoldersTrendChart.vue"
import type { HoldersRow, HoldersStock, HoldersWeek } from "@/types"
import { formatDate, signed, signedPct } from "@/utils/format"

type Board = "big_up" | "big_down" | "retail_in" | "retail_out"
type Scope = "theme" | "all"

const BOARD_LABELS: Record<Board, string> = {
    big_up: "大戶在收",
    big_down: "大戶在賣",
    retail_in: "散戶湧入",
    retail_out: "散戶離開",
}

const BOARD_NOTES: Record<Board, string> = {
    big_up: "千張大戶比例上升最多的個股，股票往大戶手上集中",
    big_down: "千張大戶比例下降最多的個股，大戶 (含外資、投信) 在賣",
    retail_in: "股東人數增加最多 (%) 的個股，散戶進場，常見於急跌後的承接",
    retail_out: "股東人數減少最多 (%) 的個股，散戶離開，股票往少數人手上集中",
}

/** 千張大戶比例變化超過這個百分點才算「在收」或「在賣」 */
const BIG_THRESHOLD = 0.5
/** 股東人數變化超過這個百分比才算散戶明顯進出 */
const RETAIL_IN_PCT = 3
const RETAIL_OUT_PCT = -1.5

const COLLAPSED_ROWS = 20

/** 至少兩週才連得成線，週數少時圖只有幾個點，逐週明細表仍可展開對照 */
const TREND_MIN_WEEKS = 2

/** 產業至少要有這麼多檔可比較的個股，平均值才有參考價值 */
const INDUSTRY_MIN_STOCKS = 3

interface IndustryRow {
    industry: string
    count: number
    bigDiff: number
    holdersPct: number
    bigUp: number
    bigDown: number
}

const weeks = ref<{ date: string; stock_count: number }[]>([])
const selectedWeek = ref("")
const week = ref<HoldersWeek | null>(null)
const scope = ref<Scope>("theme")
const board = ref<Board>("big_up")
const keyword = ref("")
const expanded = ref(false)
const openCode = ref<string | null>(null)
const detail = ref<HoldersStock | null>(null)
const detailError = ref<string | null>(null)
const error = ref<string | null>(null)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    return week.value ? `資料日 ${formatDate(week.value.date)}` : "載入中"
})

const hasPrev = computed(() => Boolean(week.value?.prev_date))

/** 依範圍篩選的個股，週檔只列出有前一週可比較的個股 */
const comparable = computed<HoldersRow[]>(() =>
    (week.value?.rows ?? []).filter((row) => scope.value === "all" || row.theme),
)

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
    switch (board.value) {
        // 門檻與摘要卡、解讀相同，清單的檔數才會與摘要卡一致
        case "big_up":
            return rows.filter((r) => big(r) >= BIG_THRESHOLD).sort((a, b) => big(b) - big(a))
        case "big_down":
            return rows.filter((r) => big(r) <= -BIG_THRESHOLD).sort((a, b) => big(a) - big(b))
        case "retail_in":
            return rows.filter((r) => retail(r) >= RETAIL_IN_PCT).sort((a, b) => retail(b) - retail(a))
        default:
            return rows.filter((r) => retail(r) <= RETAIL_OUT_PCT).sort((a, b) => retail(a) - retail(b))
    }
})

const visibleRows = computed(() => (expanded.value ? boardRows.value : boardRows.value.slice(0, COLLAPSED_ROWS)))

const summary = computed(() => {
    const rows = comparable.value
    return {
        total: rows.length,
        bigUp: rows.filter((r) => r.big_diff >= BIG_THRESHOLD).length,
        bigDown: rows.filter((r) => r.big_diff <= -BIG_THRESHOLD).length,
        retailIn: rows.filter((r) => r.holders_pct >= RETAIL_IN_PCT).length,
        retailOut: rows.filter((r) => r.holders_pct <= RETAIL_OUT_PCT).length,
    }
})

/** 依產業彙總千張大戶比例的平均變化，看這週大戶在收哪些族群 */
const industryRows = computed<IndustryRow[]>(() => {
    const groups = new Map<string, HoldersRow[]>()
    for (const row of comparable.value) {
        if (!row.industry) {
            continue
        }
        const list = groups.get(row.industry) ?? []
        list.push(row)
        groups.set(row.industry, list)
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
            bigUp: list.filter((r) => r.big_diff >= BIG_THRESHOLD).length,
            bigDown: list.filter((r) => r.big_diff <= -BIG_THRESHOLD).length,
        }))
        .sort((a, b) => b.bigDiff - a.bigDiff)
})

function industryTooltip(row: IndustryRow): string {
    return [
        `<strong>${row.industry}</strong> (${row.count} 檔)`,
        `千張大戶平均　${signed(row.bigDiff)} 百分點`,
        `股東人數平均　${signedPct(row.holdersPct, 1)}`,
        `大戶在收 ${row.bigUp} 檔，在賣 ${row.bigDown} 檔`,
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
    const range = `${formatDate(week.value.prev_date)} → ${formatDate(week.value.date)}`
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
    if (big >= BIG_THRESHOLD && retail <= 0) {
        return { text: fell ? "價跌但大戶在收，散戶離開" : "大戶在收，散戶離開", tone: "val-buy" }
    }
    if (big <= -BIG_THRESHOLD && retail >= 1) {
        return { text: fell ? "下跌時大戶賣、散戶接手" : "大戶賣給散戶", tone: "val-sell" }
    }
    if (big >= BIG_THRESHOLD) {
        return { text: fell ? "價跌但大戶在收" : "大戶在收", tone: "val-buy" }
    }
    if (big <= -BIG_THRESHOLD) {
        return { text: "大戶在賣", tone: "val-sell" }
    }
    if (retail >= RETAIL_IN_PCT) {
        return { text: fell ? "下跌時散戶大量進場" : "散戶大量進場", tone: "" }
    }
    if (retail <= RETAIL_OUT_PCT) {
        return { text: "散戶離開", tone: "" }
    }
    return { text: "變化不大", tone: "muted" }
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

watch([board, scope, keyword], () => {
    expanded.value = false
    openCode.value = null
})

onMounted(async () => {
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
                <p class="subtitle">每週一次：股票這一週流向大戶，還是流向散戶？</p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <section class="panel guide" data-nav="怎麼看">
            <h2>怎麼看這一頁</h2>
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

        <section v-if="hasPrev && comparable.length" class="panel holders-chart-panel" data-nav="分布圖">
            <div class="panel-head">
                <h2>籌碼流向分布</h2>
                <p class="panel-note">
                    一個點是一檔股票，紅漲綠跌是股價週漲跌，空心點代表數值超出畫面、貼在邊緣。左上是大戶收、散戶走，右下是大戶賣、散戶接。點一下可看該檔明細。
                </p>
            </div>
            <HoldersScatter
                :rows="comparable"
                :big-threshold="BIG_THRESHOLD"
                :retail-in="RETAIL_IN_PCT"
                :retail-out="RETAIL_OUT_PCT"
                @select="selectFromChart"
            />
        </section>

        <section v-if="hasPrev && industryRows.length" class="panel holders-chart-panel" data-nav="產業">
            <div class="panel-head">
                <h2>大戶在收哪些產業</h2>
                <p class="panel-note">
                    各產業千張大戶比例的平均週變化 (百分點)，只列可比較個股達 {{ INDUSTRY_MIN_STOCKS }} 檔以上的產業。
                </p>
            </div>
            <BarChart
                :rows="industryRows"
                :name-of="(row: IndustryRow) => `${row.industry} (${row.count})`"
                :value-of="(row: IndustryRow) => row.bigDiff"
                :tooltip="industryTooltip"
                :label-width="170"
                unit="百分點"
            />
        </section>

        <section v-if="hasPrev" ref="tablePanel" class="panel" data-nav="排行">
            <div class="panel-head">
                <h2>{{ searching ? "查詢結果" : BOARD_LABELS[board] }}</h2>
                <p class="panel-note">{{ panelNote }}</p>
            </div>
            <div v-if="!searching" class="controls controls-inline">
                <div class="tabs" role="tablist">
                    <button
                        v-for="(label, key) in BOARD_LABELS"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': board === key }"
                        role="tab"
                        @click="board = key as Board"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>

            <div class="table-wrap holders-table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>個股</th>
                            <th class="num">股價週漲跌</th>
                            <th class="num">股東人數變化</th>
                            <th class="num">千張大戶比例變化</th>
                            <th>解讀</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!visibleRows.length" class="empty-row">
                            <td colspan="5">沒有符合的個股</td>
                        </tr>
                        <template v-for="row in visibleRows" :key="row.code">
                            <tr class="clickable" :class="{ 'is-selected': openCode === row.code }" @click="toggle(row.code)">
                                <td>
                                    {{ row.code }} {{ row.name ?? "" }}
                                    <span class="muted">{{ row.industry ?? "" }}</span>
                                </td>
                                <td class="num" :class="polarity(row.price_pct)">{{ signedPct(row.price_pct, 1) }}</td>
                                <td class="num">
                                    {{ people(row.holders_diff) }}
                                    <span class="muted">（{{ signedPct(row.holders_pct, 1) }}）</span>
                                </td>
                                <td class="num" :class="polarity(row.big_diff)">
                                    {{ signed(row.big_diff) }}
                                    <span class="muted">（{{ row.big_pct.toFixed(1) }}%）</span>
                                </td>
                                <td class="verdict" :class="verdict(row).tone">{{ verdict(row).text }}</td>
                            </tr>
                            <tr v-if="openCode === row.code" class="detail-row">
                                <td colspan="5">
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
                千張大戶比例變化的單位是百分點，括號內是目前的比例。變化達 {{ BIG_THRESHOLD }} 個百分點才算大戶在收或在賣，
                股東人數一週增加 {{ RETAIL_IN_PCT }}% 以上算散戶湧入、減少 {{ -RETAIL_OUT_PCT }}% 以上算散戶離開。點選列可看逐週走勢與各級距的人數。
            </p>
        </section>
    </section>
</template>

<style scoped>
.guide {
    margin-bottom: 16px;
}

.guide h2 {
    margin: 0 0 8px;
    font-size: 16px;
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
