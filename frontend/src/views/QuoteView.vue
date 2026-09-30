<script setup lang="ts">
/**
 * 即時行情。
 *
 * 預設常駐微型臺指期貨與加權指數，另可查詢單一個股。
 *
 * 兩個來源分工：加權指數與個股走富果 (需要金鑰，只能由後端代抓)，
 * 微台走期交所自己的看盤端點 (富果的期貨行情屬於付費方案)。
 * 兩者都沒有 CORS 標頭，因此這一頁只存在於本機模式。
 *
 * 後端對每一種資料各有一層快取，多個分頁同時開著不會加倍請求數；
 * 前端這裡則以「非交易時段自動停更」再省一層。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import VChart from "vue-echarts"

import type {
    QuoteFuture,
    QuoteIndex,
    QuoteOverview,
    QuoteSearchItem,
    QuoteStockData,
} from "@/types"
import { YI, signed } from "@/utils/format"
import { baseTooltip, buyColor, colors, sellColor } from "@/utils/theme"

/** 與後端快取時間一致，再短也只會拿到同一份快取 */
const INTERVAL = 10000
/** 搜尋輸入的去抖動延遲 */
const SEARCH_DELAY = 250

const overview = ref<QuoteOverview | null>(null)
const stock = ref<QuoteStockData | null>(null)
const overviewError = ref<string | null>(null)
const stockError = ref<string | null>(null)
const auto = ref(true)
const loading = ref(false)

const keyword = ref("")
const suggestions = ref<QuoteSearchItem[]>([])
const activeCode = ref<string>("")

let timer: number | null = null
let searchTimer: number | null = null

async function fetchJson<T>(url: string): Promise<T> {
    const resp = await fetch(url)
    if (!resp.ok) {
        const text = await resp.text()
        let detail = resp.statusText
        try {
            detail = (JSON.parse(text) as { detail?: string }).detail ?? text
        } catch {
            detail = text || resp.statusText
        }
        throw new Error(detail)
    }
    return resp.json() as Promise<T>
}

async function loadOverview(force = false) {
    try {
        overview.value = await fetchJson<QuoteOverview>(
            `/api/quote/overview${force ? "?force=true" : ""}`,
        )
        overviewError.value = null
    } catch (err) {
        overviewError.value = (err as Error).message
    }
}

async function loadStock(force = false) {
    if (!activeCode.value) {
        return
    }
    try {
        stock.value = await fetchJson<QuoteStockData>(
            `/api/quote/stock/${activeCode.value}${force ? "?force=true" : ""}`,
        )
        stockError.value = null
    } catch (err) {
        stockError.value = (err as Error).message
    }
}

async function loadAll(force = false) {
    if (loading.value) {
        return
    }
    loading.value = true
    try {
        await Promise.all([loadOverview(force), loadStock(force)])
        // 期貨收盤後行情不會再變，自動更新沒有意義也沒必要再送請求
        if (overview.value && !overview.value.session) {
            stopTimer()
        }
    } finally {
        loading.value = false
    }
}

function startTimer() {
    stopTimer()
    timer = window.setInterval(() => loadAll(), INTERVAL)
}

function stopTimer() {
    if (timer !== null) {
        window.clearInterval(timer)
        timer = null
    }
}

watch(auto, (on) => (on ? startTimer() : stopTimer()))

/* ---------------------------------------------------------------- */
/* 搜尋                                                              */
/* ---------------------------------------------------------------- */

watch(keyword, (text) => {
    if (searchTimer !== null) {
        window.clearTimeout(searchTimer)
    }
    const query = text.trim()
    if (!query) {
        suggestions.value = []
        return
    }
    // 只查本機資料庫，不會對外送出請求，但仍去抖動以免每個字都查一次
    searchTimer = window.setTimeout(async () => {
        try {
            const data = await fetchJson<{ items: QuoteSearchItem[] }>(
                `/api/quote/search?q=${encodeURIComponent(query)}`,
            )
            suggestions.value = data.items
        } catch {
            suggestions.value = []
        }
    }, SEARCH_DELAY)
})

function select(item: QuoteSearchItem) {
    activeCode.value = item.code
    keyword.value = ""
    suggestions.value = []
    stock.value = null
    stockError.value = null
    loadStock(true)
}

/** 直接輸入代號後按 Enter，不必等建議清單 */
function submit() {
    const query = keyword.value.trim()
    if (!query) {
        return
    }
    const exact = suggestions.value.find((item) => item.code === query)
    select(exact ?? { code: query.toUpperCase(), name: "", market: "", industry: "" })
}

function clearStock() {
    activeCode.value = ""
    stock.value = null
    stockError.value = null
}

/* ---------------------------------------------------------------- */
/* 顯示                                                              */
/* ---------------------------------------------------------------- */

const future = computed<QuoteFuture | null>(() => overview.value?.future ?? null)
const index = computed<QuoteIndex | null>(() => overview.value?.index ?? null)

const status = computed(() => {
    if (overviewError.value) {
        return `載入失敗：${overviewError.value}`
    }
    const payload = overview.value
    if (!payload) {
        return "載入中"
    }
    return `${payload.session ? "交易中" : "非交易時段"}　更新於 ${payload.updated_at}`
        // 來源暫時取不到時沿用前一份，必須明講，以免把過時的數字當成當下行情
        + (payload.stale ? "（來源忙碌，暫時沿用前一筆）" : "")
})

function tone(value: number | null | undefined): string {
    return (value ?? 0) >= 0 ? buyColor() : sellColor()
}

function fixed(value: number | null | undefined, digits = 2): string {
    return value === null || value === undefined ? "--" : value.toFixed(digits)
}

const basisLabel = computed(() => {
    const basis = overview.value?.basis
    if (basis === null || basis === undefined) {
        return ""
    }
    return basis > 0 ? "正價差" : basis < 0 ? "逆價差" : "持平"
})

/** 內外盤比：外盤 (以賣價成交) 佔比越高代表買方越積極 */
const askShare = computed(() => {
    const quote = stock.value?.quote
    if (!quote) {
        return null
    }
    const total = quote.at_bid + quote.at_ask
    return total ? (quote.at_ask / total) * 100 : null
})

/** 五檔以買賣並排呈現，檔數不足時補空列 */
const levels = computed(() => {
    const quote = stock.value?.quote
    if (!quote) {
        return []
    }
    const rows = []
    for (let i = 0; i < 5; i += 1) {
        rows.push({ bid: quote.bids[i] ?? null, ask: quote.asks[i] ?? null })
    }
    return rows
})

const trendOption = computed(() => {
    const candles = stock.value?.candles ?? []
    const quote = stock.value?.quote
    const c = colors()
    const prev = quote?.prev_close ?? null
    const last = candles.length ? candles[candles.length - 1].close : null
    // 以收盤價相對昨收決定線的顏色，與其他頁的紅漲綠跌一致
    const up = prev !== null && last !== null ? last >= prev : true

    return {
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "cross" },
        },
        // 上半部為價格，下半部為成交量，共用同一條時間軸。
        // 高度用百分比，圖才會填滿容器而不是在下方留一段空白
        grid: [
            { left: 56, right: 24, top: 12, height: "62%" },
            { left: 56, right: 24, top: "76%", height: "16%" },
        ],
        xAxis: [
            {
                type: "category",
                data: candles.map((row) => row.time),
                axisLabel: { color: c.secondary, fontSize: 11 },
                axisLine: { lineStyle: { color: c.border } },
            },
            {
                type: "category",
                gridIndex: 1,
                data: candles.map((row) => row.time),
                axisLabel: { show: false },
                axisLine: { lineStyle: { color: c.border } },
            },
        ],
        yAxis: [
            {
                type: "value",
                scale: true,
                axisLabel: { color: c.secondary, fontSize: 11 },
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
            {
                type: "value",
                gridIndex: 1,
                axisLabel: { show: false },
                splitLine: { show: false },
            },
        ],
        series: [
            {
                name: "成交價",
                type: "line",
                data: candles.map((row) => row.close),
                showSymbol: false,
                lineStyle: { width: 2, color: up ? buyColor() : sellColor() },
                itemStyle: { color: up ? buyColor() : sellColor() },
            },
            {
                name: "均價",
                type: "line",
                data: candles.map((row) => row.average),
                showSymbol: false,
                lineStyle: { width: 1, color: c.secondary, type: "dashed" },
                itemStyle: { color: c.secondary },
            },
            {
                name: "成交量",
                type: "bar",
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: candles.map((row) => row.volume),
                itemStyle: { color: c.neutral },
            },
        ],
    }
})

onMounted(() => {
    loadAll()
    if (auto.value) {
        startTimer()
    }
})

onUnmounted(() => {
    stopTimer()
    if (searchTimer !== null) {
        window.clearTimeout(searchTimer)
    }
})
</script>

<template>
    <section class="page">
        <div class="page-head">
            <h1>即時行情</h1>
            <p class="page-sub">{{ status }}</p>
        </div>

        <div class="controls">
            <div class="control control-search">
                <span class="control-label">查詢個股</span>
                <input
                    v-model="keyword"
                    class="search-input"
                    type="search"
                    placeholder="輸入代號或名稱，例如 2330 或 台積電"
                    @keyup.enter="submit"
                >
                <ul v-if="suggestions.length" class="suggest">
                    <li v-for="item in suggestions" :key="item.code">
                        <button type="button" class="suggest-item" @click="select(item)">
                            <span class="suggest-code">{{ item.code }}</span>
                            <span class="suggest-name">{{ item.name }}</span>
                            <span class="suggest-meta">{{ item.industry }}</span>
                        </button>
                    </li>
                </ul>
            </div>

            <div class="control control-inline">
                <button
                    type="button"
                    class="chip"
                    :class="{ 'is-active': auto }"
                    @click="auto = !auto"
                >
                    自動更新
                </button>
                <button type="button" class="chip" @click="loadAll(true)">立即更新</button>
            </div>
        </div>

        <p class="notice">
            微台為期交所的微型臺指期貨近月合約，每月結算後自動換約；加權指數與個股來自富果行情 API。
            期現價差是期貨減現貨，正價差代表期貨走在現貨前面。
            本頁只在本機模式提供，線上的靜態站沒有這一頁。
        </p>

        <section class="panel">
            <div class="panel-head">
                <h2>大盤與期貨</h2>
                <p class="panel-note">
                    微台報價時間 {{ future?.time || "--" }}　指數 {{ index?.time || "--" }}
                </p>
            </div>
            <div class="quote-grid">
                <div v-if="future" class="quote-card">
                    <div class="quote-name">
                        {{ future.name }}
                        <span class="quote-code">{{ future.code }}</span>
                        <span v-if="future.trial" class="tag">試撮</span>
                    </div>
                    <div class="quote-value" :style="{ color: tone(future.change) }">
                        {{ fixed(future.price, 0) }}
                    </div>
                    <div class="quote-change" :style="{ color: tone(future.change) }">
                        {{ signed(future.change, 0) }}（{{ signed(future.pct, 2) }}%）
                    </div>
                    <div class="quote-meta">
                        開 {{ fixed(future.open, 0) }}　高 {{ fixed(future.high, 0) }}　低 {{ fixed(future.low, 0) }}
                    </div>
                    <div class="quote-meta">
                        成交 {{ (future.volume ?? 0).toLocaleString() }} 口
                        買 {{ fixed(future.bids[0]?.price, 0) }} / 賣 {{ fixed(future.asks[0]?.price, 0) }}
                    </div>
                </div>

                <div v-if="index" class="quote-card">
                    <div class="quote-name">
                        {{ index.name }}
                        <span class="quote-code">{{ index.code }}</span>
                    </div>
                    <div class="quote-value" :style="{ color: tone(index.change) }">
                        {{ fixed(index.price) }}
                    </div>
                    <div class="quote-change" :style="{ color: tone(index.change) }">
                        {{ signed(index.change, 2) }}（{{ signed(index.pct, 2) }}%）
                    </div>
                    <div class="quote-meta">
                        開 {{ fixed(index.open) }}　高 {{ fixed(index.high) }}　低 {{ fixed(index.low) }}
                    </div>
                    <div class="quote-meta">
                        全市場成交 {{ ((index.amount ?? 0) / YI).toFixed(0) }} 億
                        {{ ((index.volume ?? 0) / 10000).toFixed(0) }} 萬張
                    </div>
                </div>

                <div v-if="overview && overview.basis !== null" class="quote-card">
                    <div class="quote-name">期現價差</div>
                    <div class="quote-value" :style="{ color: tone(overview.basis) }">
                        {{ signed(overview.basis, 2) }}
                    </div>
                    <div class="quote-change" :style="{ color: tone(overview.basis) }">
                        {{ basisLabel }}
                    </div>
                    <div class="quote-meta">微台減加權指數</div>
                </div>

                <p v-if="!future && !index" class="quote-meta">目前沒有報價</p>
            </div>
            <p v-if="overview?.error" class="notice">來源訊息：{{ overview.error }}</p>
        </section>

        <section v-if="activeCode" class="panel">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>
                        {{ stock?.quote.name || activeCode }}
                        <span class="panel-note">{{ activeCode }}</span>
                    </h2>
                    <p class="panel-note">
                        <template v-if="stock">
                            報價時間 {{ stock.quote.time || "--" }}
                            {{ stock.quote.continuous ? "" : "（非連續交易時段）" }}
                            {{ stock.stale ? "（暫時沿用前一筆）" : "" }}
                        </template>
                    </p>
                </div>
                <button type="button" class="chip" @click="clearStock">收起</button>
            </div>

            <p v-if="stockError" class="notice">載入失敗：{{ stockError }}</p>

            <template v-if="stock">
                <div class="quote-grid">
                    <div class="quote-card">
                        <div class="quote-name">成交價</div>
                        <div class="quote-value" :style="{ color: tone(stock.quote.change) }">
                            {{ fixed(stock.quote.price) }}
                        </div>
                        <div class="quote-change" :style="{ color: tone(stock.quote.change) }">
                            {{ signed(stock.quote.change, 2) }}（{{ signed(stock.quote.pct, 2) }}%）
                        </div>
                        <div class="quote-meta">昨收 {{ fixed(stock.quote.prev_close) }}</div>
                    </div>
                    <div class="quote-card">
                        <div class="quote-name">當日區間</div>
                        <div class="quote-meta">開盤 {{ fixed(stock.quote.open) }}</div>
                        <div class="quote-meta">最高 {{ fixed(stock.quote.high) }}</div>
                        <div class="quote-meta">最低 {{ fixed(stock.quote.low) }}</div>
                        <div class="quote-meta">
                            均價 {{ fixed(stock.quote.avg) }}　振幅 {{ fixed(stock.quote.amplitude) }}%
                        </div>
                    </div>
                    <div class="quote-card">
                        <div class="quote-name">成交統計</div>
                        <div class="quote-meta">成交量 {{ (stock.quote.volume ?? 0).toLocaleString() }} 張</div>
                        <div class="quote-meta">成交金額 {{ ((stock.quote.amount ?? 0) / YI).toFixed(2) }} 億</div>
                        <div class="quote-meta">筆數 {{ (stock.quote.transaction ?? 0).toLocaleString() }}</div>
                    </div>
                    <div v-if="askShare !== null" class="quote-card">
                        <div class="quote-name">內外盤</div>
                        <div class="quote-value" :style="{ color: tone(askShare - 50) }">
                            {{ askShare.toFixed(0) }}%
                        </div>
                        <div class="quote-change">外盤成交佔比</div>
                        <div class="quote-meta">
                            外盤 {{ stock.quote.at_ask.toLocaleString() }}　內盤 {{ stock.quote.at_bid.toLocaleString() }}
                        </div>
                    </div>
                </div>

                <div class="quote-split">
                    <div class="quote-split-main">
                        <h3 class="sub-head">分時走勢</h3>
                        <VChart
                            v-if="stock.candles.length"
                            class="chart"
                            :option="trendOption"
                            autoresize
                        />
                        <p v-else class="notice">今日尚無分時資料</p>
                    </div>

                    <div class="quote-split-side">
                        <h3 class="sub-head">五檔</h3>
                        <div class="table-wrap">
                            <table class="data-table">
                                <thead>
                                    <tr>
                                        <th class="num">買量</th><th class="num">買價</th>
                                        <th class="num">賣價</th><th class="num">賣量</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="(row, i) in levels" :key="i">
                                        <td class="num">{{ row.bid?.size?.toLocaleString() ?? "--" }}</td>
                                        <td class="num val-buy">{{ fixed(row.bid?.price) }}</td>
                                        <td class="num val-sell">{{ fixed(row.ask?.price) }}</td>
                                        <td class="num">{{ row.ask?.size?.toLocaleString() ?? "--" }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </template>
        </section>

        <p v-else class="notice">
            在上方輸入代號或名稱即可查看個股即時行情，包含五檔、內外盤與分時走勢。
        </p>
    </section>
</template>

<style scoped>
.control-search {
    position: relative;
    min-width: 280px;
}

/* 標籤與輸入框同一列，不讓「查詢個股」被擠成兩行 */
.control-search .control-label {
    white-space: nowrap;
}

.search-input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    color: var(--text-primary);
    font-size: 14px;
}

.search-input:focus {
    outline: none;
    border-color: var(--text-muted);
}

/* 建議清單浮在其他控制項之上，不把版面撐開 */
.suggest {
    position: absolute;
    z-index: 20;
    top: 100%;
    left: 0;
    right: 0;
    margin: 4px 0 0;
    padding: 4px;
    list-style: none;
    max-height: 280px;
    overflow-y: auto;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.suggest-item {
    display: flex;
    gap: 10px;
    align-items: baseline;
    width: 100%;
    padding: 7px 10px;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--text-primary);
    font-size: 13px;
    text-align: left;
    cursor: pointer;
}

.suggest-item:hover {
    background: var(--surface-0);
}

.suggest-code {
    font-weight: 600;
    min-width: 52px;
}

.suggest-name {
    flex: 1;
}

.suggest-meta {
    color: var(--text-secondary);
    font-size: 12px;
}

/* 代號附在名稱後面，以較淡的樣式避免搶走名稱的視覺重量 */
.quote-code {
    margin-left: 6px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
}

.tag {
    margin-left: 6px;
    padding: 1px 6px;
    border-radius: 4px;
    background: var(--neutral);
    color: var(--text-secondary);
    font-size: 11px;
    font-weight: 400;
}

/* 走勢圖與五檔並排，窄螢幕改為上下堆疊 */
.quote-split {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 260px;
    gap: 20px;
    margin-top: 16px;
}

.sub-head {
    margin: 0 0 8px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-secondary);
}

@media (max-width: 900px) {
    .quote-split {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
