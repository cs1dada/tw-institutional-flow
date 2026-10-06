<script setup lang="ts">
/**
 * 永豐即時行情。
 *
 * 與富果那一頁看的是同一批標的，差別在於資料全部來自永豐 Shioaji，
 * 而且大台、加權指數與個股是**一次批次查詢**取回的 —— Shioaji 的
 * snapshots 接受多個合約，一次呼叫只算一次額度。
 *
 * Shioaji 是需要登入的 SDK，金鑰不可能放進前端，必須由後端持有連線，
 * 因此這一頁只存在於本機模式。
 *
 * 用量是這一頁特別要盯的東西 (每日流量 500 MB、盤中 K 線 270 次)，
 * 所以直接顯示在畫面上，不必另外去查。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import VChart from "vue-echarts"

import type {
    Bar,
    StockHistory,
    SinoPeriod,
    SinoQuoteData,
    SinoSearchItem,
    SinoSnapshot,
    SinoUsage,
} from "@/types"
import { buildCandleOption } from "@/utils/candleChart"
import { YI, signed } from "@/utils/format"
import {
    DEFAULT_RANGE,
    PERIOD_LABELS,
    PERIOD_MA,
    aggregate,
    expandRows,
    rangeBounds,
    visibleRange,
    withChange,
} from "@/utils/indexBars"
import { baseTooltip, buyColor, colors, sellColor } from "@/utils/theme"

/**
 * 前端輪詢間隔。快照在後端快取 10 秒，再短也只會拿到同一份；
 * 但訂閱中的期貨每次都會套上最新的逐筆成交，因此這裡比快照頻繁，
 * 問的是本機後端，不消耗永豐的查詢額度
 */
const INTERVAL = 2000
/** 用量變化很慢，不需要跟報價一樣頻繁 */
const USAGE_INTERVAL = 60000
const SEARCH_DELAY = 250

/** 訂閱中的期貨，分時可切換日盤、夜盤，或把最近兩段依時間接起來 */
type SessionView = "day" | "night" | "all"
const SESSION_TABS: { key: SessionView; label: string }[] = [
    { key: "day", label: "日盤" },
    { key: "night", label: "夜盤" },
    { key: "all", label: "全日" },
]

/** 走勢圖的週期。當日為分時，其餘為 K 線 */
const PERIOD_TABS: { key: SinoPeriod; label: string }[] = [
    { key: "intraday", label: "當日" },
    { key: "daily", label: PERIOD_LABELS.daily },
    { key: "weekly", label: PERIOD_LABELS.weekly },
    { key: "monthly", label: PERIOD_LABELS.monthly },
]

/**
 * 各週期需要的資料長度 (月)。
 *
 * 歷史資料要由 1 分 K 聚合，成本與區間成正比 (約 60 bytes/根，一年約 4 MB)，
 * 因此只在切到月線時才拉三年，日線與週線共用同一份一年的資料。
 */
/** 價格軸的名稱。個股是股價、期貨是點數、指數就叫指數 */
const PRICE_AXIS: Record<string, string> = {
    TAIFEX: "點數",
    INDEX: "指數",
}

const PERIOD_MONTHS: Record<Exclude<SinoPeriod, "intraday">, number> = {
    daily: 12,
    weekly: 12,
    monthly: 36,
}

const data = ref<SinoQuoteData | null>(null)
const usage = ref<SinoUsage | null>(null)
const error = ref<string | null>(null)
const auto = ref(true)
const loading = ref(false)

const keyword = ref("")
const suggestions = ref<SinoSearchItem[]>([])
const activeCode = ref("")

const period = ref<SinoPeriod>("intraday")
/** 使用者選的時段；null 代表跟著目前所在的時段 */
const sessionChoice = ref<SessionView | null>(null)
const history = ref<StockHistory | null>(null)
const historyMonths = ref(0)
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
/**
 * 待確認的 Shioaji 歷史查詢。
 *
 * 本日行情 (即時報價與當日分時) 本來就只能向 Shioaji 要，照常查；
 * 但歷史 K 線是可以從盤後資料庫讀的，一旦資料庫不夠而要回頭打 Shioaji，
 * 就會消耗每日流量，因此一律先問過使用者再送出。
 */
const pending = ref<{
    months: number
    available: number
    needed: number
    /** notInDb 為期貨、指數這類盤後資料庫本來就沒有的商品 */
    reason: "notInDb" | "insufficient"
} | null>(null)

let timer: number | null = null
let usageTimer: number | null = null
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

async function load(force = false) {
    if (loading.value) {
        return
    }
    loading.value = true
    try {
        const params = new URLSearchParams()
        if (activeCode.value) {
            params.set("code", activeCode.value)
        }
        if (force) {
            params.set("force", "true")
        }
        const query = params.toString()
        data.value = await fetchJson<SinoQuoteData>(`/api/sino/quote${query ? `?${query}` : ""}`)
        error.value = null
    } catch (err) {
        error.value = (err as Error).message
    } finally {
        loading.value = false
    }
}

async function loadUsage() {
    try {
        usage.value = await fetchJson<SinoUsage>("/api/sino/usage")
    } catch {
        // 用量查不到不影響行情顯示
    }
}

function startTimer() {
    stopTimer()
    timer = window.setInterval(() => load(), INTERVAL)
    usageTimer = window.setInterval(() => loadUsage(), USAGE_INTERVAL)
}

function stopTimer() {
    if (timer !== null) {
        window.clearInterval(timer)
        timer = null
    }
    if (usageTimer !== null) {
        window.clearInterval(usageTimer)
        usageTimer = null
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
    // 查的是登入時下載的合約清單，不會送出行情查詢，但仍去抖動
    searchTimer = window.setTimeout(async () => {
        try {
            const result = await fetchJson<{ items: SinoSearchItem[] }>(
                `/api/sino/search?q=${encodeURIComponent(query)}`,
            )
            suggestions.value = result.items
        } catch {
            suggestions.value = []
        }
    }, SEARCH_DELAY)
})

/**
 * 確保手上的歷史資料夠長。
 *
 * 已載入的區間若已涵蓋需求就直接沿用，不再向後端要一次 ——
 * 這是這一頁最貴的查詢，能省則省。
 */
async function ensureHistory(months: number) {
    if (!activeCode.value) {
        return
    }
    if (history.value && historyMonths.value >= months) {
        return
    }
    if (historyLoading.value) {
        return
    }
    historyLoading.value = true
    historyError.value = null
    pending.value = null
    const code = activeCode.value
    try {
        // 先讀本機資料庫：盤後匯入的資料不消耗任何行情額度，讀取也快得多
        const fromDb = await fetchJson<StockHistory>(
            `/api/history/${code}?months=${months}`,
        )
        history.value = fromDb
        historyMonths.value = months

        if (!covers(fromDb, months)) {
            // 不足就先畫資料庫有的那段，同時問使用者要不要花額度補齊，
            // 不自作主張送出查詢。
            //
            // 盤後資料庫只有上市櫃個股的收盤行情，期貨與指數完全不在裡面，
            // 那和「回補得不夠久」是兩回事，要分開講清楚，
            // 否則畫面會顯示「資料庫只有 0 個交易日」這種誤導的說法。
            const notInDb = fromDb.items.length === 0 && !fromDb.name
            pending.value = {
                months,
                available: fromDb.items.length,
                needed: Math.round(months * 19 * 0.7),
                reason: notInDb ? "notInDb" : "insufficient",
            }
        }
    } catch (err) {
        historyError.value = (err as Error).message
    } finally {
        historyLoading.value = false
    }
}

/** 使用者確認後才向 Shioaji 要歷史 K 線 */
async function confirmFallback() {
    const request = pending.value
    if (!request || !activeCode.value) {
        return
    }
    pending.value = null
    historyLoading.value = true
    historyError.value = null
    try {
        history.value = await fetchJson<StockHistory>(
            `/api/sino/history/${activeCode.value}?months=${request.months}`,
        )
        historyMonths.value = request.months
        loadUsage()
    } catch (err) {
        historyError.value = (err as Error).message
    } finally {
        historyLoading.value = false
    }
}

/** 估算這次查詢要花多少流量。實測一年約 2.6 MB、三年約 3.7 MB */
function estimateMb(months: number): string {
    const mb = months <= 12 ? (months / 12) * 2.6 : 2.6 + ((months - 12) / 24) * 1.1
    return mb.toFixed(1)
}

/**
 * 資料庫的資料夠不夠畫這個區間。
 *
 * 一個月約 19 到 20 個交易日，取七成當門檻：新股上市不久或中間有停牌
 * 都會讓筆數偏少，但只要涵蓋大部分期間就足以看出走勢，不必為了幾天
 * 去消耗行情額度。
 */
function covers(payload: StockHistory, months: number): boolean {
    const expected = months * 19 * 0.7
    return payload.items.length >= expected
}

watch(period, (value) => {
    if (value !== "intraday") {
        ensureHistory(PERIOD_MONTHS[value])
    }
})

function select(item: SinoSearchItem) {
    activeCode.value = item.code
    sessionChoice.value = null
    keyword.value = ""
    suggestions.value = []
    // 換一檔就得重新拉歷史，舊的不能沿用
    history.value = null
    historyMonths.value = 0
    historyError.value = null
    pending.value = null
    load(true)
    if (period.value !== "intraday") {
        ensureHistory(PERIOD_MONTHS[period.value])
    }
}

/**
 * 從上方的常駐卡片帶入下方明細。
 *
 * 大台與加權指數的即時報價本來就在每一輪的批次查詢裡，點下去只是把它
 * 展開成完整的明細與走勢，不會多送任何一次行情查詢。
 */
function selectCard(code: string | undefined) {
    if (!code || code === activeCode.value) {
        return
    }
    select({ code, name: "", exchange: "" })
}

function submit() {
    const query = keyword.value.trim()
    if (!query) {
        return
    }
    const exact = suggestions.value.find((item) => item.code === query)
    select(exact ?? { code: query.toUpperCase(), name: "", exchange: "" })
}

function clearStock() {
    activeCode.value = ""
    history.value = null
    historyMonths.value = 0
    historyError.value = null
    pending.value = null
    load(true)
}

/* ---------------------------------------------------------------- */
/* 顯示                                                              */
/* ---------------------------------------------------------------- */

const future = computed<SinoSnapshot | null>(() => data.value?.future ?? null)
const index = computed<SinoSnapshot | null>(() => data.value?.index ?? null)
const stock = computed<SinoSnapshot | null>(() => data.value?.stock ?? null)

const status = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    if (!data.value) {
        return "載入中"
    }
    return `更新於 ${data.value.updated_at}`
        + (data.value.stale ? "（查詢已達節流上限，暫時沿用前一筆）" : "")
})

/**
 * 目前查的是不是期貨。
 *
 * 期貨與個股的單位不同（口 vs 張），成交金額的定義也不一樣，
 * 畫面上要跟著換，不能一律寫「張」。
 */
const FUTURE_PREFIXES = ["TMF", "TXF", "MXF", "MTX", "TX"]
const isFuture = computed(() =>
    FUTURE_PREFIXES.some((prefix) => activeCode.value.startsWith(prefix)),
)
/** 指數的成交統計是全市場合計，不是這個商品自己的 */
const isIndex = computed(() => activeCode.value.startsWith("IX") || activeCode.value.startsWith("IR"))
const lotUnit = computed(() => (isFuture.value ? "口" : "張"))

const basisLabel = computed(() => {
    const basis = data.value?.basis
    if (basis === null || basis === undefined) {
        return ""
    }
    return basis > 0 ? "正價差" : basis < 0 ? "逆價差" : "持平"
})

function tone(value: number | null | undefined): string {
    return (value ?? 0) >= 0 ? buyColor() : sellColor()
}

function fixed(value: number | null | undefined, digits = 2): string {
    return value === null || value === undefined ? "--" : value.toFixed(digits)
}

const sessions = computed(() => data.value?.sessions ?? null)

const sessionView = computed<SessionView>(
    () => sessionChoice.value ?? data.value?.current_session ?? "day",
)

/**
 * 走勢圖實際要畫的分時。
 *
 * 一般個股就是 candles；訂閱中的期貨依選定的時段取出，「全日」把最近兩段
 * 依時間接起來，並記下接縫的位置畫分隔線。中間的休市不留空白。
 */
const intraday = computed(() => {
    const all = sessions.value
    if (!all) {
        return { candles: data.value?.candles ?? [], separator: null, session: null }
    }
    if (sessionView.value === "all") {
        const filled = all.filter((item) => item.candles.length)
        const later = filled.length > 1 ? filled[filled.length - 1] : null
        return {
            candles: filled.flatMap((item) => item.candles),
            separator: later
                ? { index: filled[0].candles.length, label: `${later.label} ${later.start.slice(11)}` }
                : null,
            session: null,
        }
    }
    const one = all.find((item) => item.kind === sessionView.value) ?? null
    return { candles: one?.candles ?? [], separator: null, session: one }
})

const trendOption = computed(() => {
    const candles = intraday.value.candles
    const separator = intraday.value.separator
    const quote = stock.value
    const c = colors()
    const first = candles.length ? candles[0].close : null
    const last = candles.length ? candles[candles.length - 1].close : null
    // 以最新價相對開盤決定線的顏色，與其他頁的紅漲綠跌一致
    const up = quote?.change !== null && quote?.change !== undefined
        ? quote.change >= 0
        : (first !== null && last !== null ? last >= first : true)

    return {
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "cross" },
        },
        // 上半部為價格，下半部為成交量，共用同一條時間軸
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
                // 全日時標出夜盤與日盤的接縫。圖表每 2 秒更新一次，
                // 不關掉動畫的話分隔線每次都會重新長出來，看起來一直在跳
                markLine: separator
                    ? {
                        silent: true,
                        animation: false,
                        symbol: "none",
                        lineStyle: { color: c.muted, type: "dashed", width: 1 },
                        label: { formatter: separator.label, color: c.secondary, fontSize: 11 },
                        data: [{ xAxis: candles[separator.index]?.time }],
                    }
                    : undefined,
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

/** 日線聚合成該週期的 K 棒。週線與月線的規則與大盤指數頁完全一致 */
const bars = computed<Bar[]>(() => {
    const current = period.value
    if (current === "intraday" || !history.value) {
        return []
    }
    return withChange(aggregate(expandRows(history.value), current))
})

const candleOption = computed(() => {
    const current = period.value
    if (current === "intraday" || !history.value || !bars.value.length) {
        return {}
    }
    const rows = expandRows(history.value)
    // K 棒本身仍是全部資料，只縮放顯示範圍，均線才不會在區間起點斷頭
    const bounds = rangeBounds(rows, DEFAULT_RANGE[current], null, null)
    return buildCandleOption(bars.value, {
        maSizes: PERIOD_MA[current],
        zoom: visibleRange(bars.value, bounds),
        // 三種商品的價格軸名稱不同
        priceName: PRICE_AXIS[history.value.market ?? ""] ?? "股價",
        turnoverLabel: history.value.turnover_label,
        turnoverUnit: history.value.turnover_unit,
    })
})

const chartNote = computed(() => {
    const current = period.value
    if (current === "intraday") {
        const count = intraday.value.candles.length
        if (!sessions.value) {
            return `一分 K，共 ${count} 根`
        }
        const session = intraday.value.session
        const range = session
            ? `${session.label}（${session.start} ~ ${session.end}）`
            : "全日：最近的兩個時段依時間接起來，虛線為接縫"
        return `${range}，一分 K 共 ${count} 根，逐筆成交即時更新`
    }
    const ma = PERIOD_MA[current].map((size) => `MA${size}`).join("、")
    const source = history.value?.source === "db" ? "盤後資料庫" : "Shioaji"
    return `${bars.value.length} 根${PERIOD_LABELS[current]} K 棒，均線 ${ma}`
        + `（${historyMonths.value} 個月，來源：${source}）`
})

onMounted(() => {
    load()
    loadUsage()
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
            <h1>永豐即時行情</h1>
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
                            <span class="suggest-meta">{{ item.exchange }}</span>
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
                <button type="button" class="chip" @click="load(true)">立即更新</button>
            </div>
        </div>

        <p class="notice">
            資料來自永豐 Shioaji，大台、加權指數與個股是一次批次查詢取回的。
            點下方「大盤與期貨」的大台或加權指數卡片，可展開它的明細與走勢。
            Shioaji 的快照只提供最佳一檔，沒有完整五檔 (五檔需要另外訂閱串流)，
            但多了量比與均價。本頁只在本機模式提供。
        </p>

        <div v-if="usage" class="usage-bar">
            <div class="usage-item">
                <span class="usage-label">今日流量</span>
                <span class="usage-value">{{ usage.used_mb }} / {{ usage.limit_mb }} MB</span>
                <span class="usage-track">
                    <span class="usage-fill" :style="{ width: Math.min(usage.percent, 100) + '%' }" />
                </span>
                <span class="usage-note">{{ usage.percent }}%</span>
            </div>
            <div class="usage-item">
                <span class="usage-label">K 線查詢</span>
                <span class="usage-value">{{ usage.kbar_used }} / {{ usage.kbar_limit }} 次</span>
                <span class="usage-track">
                    <span
                        class="usage-fill"
                        :style="{ width: Math.min(usage.kbar_used / usage.kbar_limit * 100, 100) + '%' }"
                    />
                </span>
                <span class="usage-note">官方盤中上限 270 次</span>
            </div>
            <div class="usage-item">
                <span class="usage-label">連線</span>
                <span class="usage-value">{{ usage.connections }} / 5</span>
            </div>
        </div>

        <section class="panel" data-nav="大盤與期貨">
            <div class="panel-head">
                <h2>大盤與期貨</h2>
                <p class="panel-note">
                    大台報價時間 {{ future?.time || "--" }}
                    （{{ data?.future_streaming ? "逐筆成交即時更新" : "快照，每 10 秒" }}）
                    　指數 {{ index?.time || "--" }}
                </p>
            </div>
            <div class="quote-grid">
                <div
                    v-if="future"
                    class="quote-card is-clickable"
                    :class="{ 'is-selected': activeCode === future.code }"
                    role="button"
                    tabindex="0"
                    @click="selectCard(future.code)"
                    @keydown.enter="selectCard(future.code)"
                    @keydown.space.prevent="selectCard(future.code)"
                >
                    <div class="quote-name">
                        {{ data?.future_name || "臺股期貨" }}
                        <span class="quote-code">{{ future.code }}</span>
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
                        買 {{ fixed(future.bid, 0) }} / 賣 {{ fixed(future.ask, 0) }}
                    </div>
                </div>

                <div
                    v-if="index"
                    class="quote-card is-clickable"
                    :class="{ 'is-selected': activeCode === index.code }"
                    role="button"
                    tabindex="0"
                    @click="selectCard(index.code)"
                    @keydown.enter="selectCard(index.code)"
                    @keydown.space.prevent="selectCard(index.code)"
                >
                    <div class="quote-name">
                        台灣加權指數
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
                        量比 {{ fixed(index.volume_ratio) }}
                    </div>
                </div>

                <div v-if="data && data.basis !== null" class="quote-card">
                    <div class="quote-name">期現價差</div>
                    <div class="quote-value" :style="{ color: tone(data.basis) }">
                        {{ signed(data.basis, 2) }}
                    </div>
                    <div class="quote-change" :style="{ color: tone(data.basis) }">
                        {{ basisLabel }}
                    </div>
                    <div class="quote-meta">大台減加權指數</div>
                </div>

                <p v-if="!future && !index" class="quote-meta">目前沒有報價</p>
            </div>
            <p v-if="data?.error" class="notice">來源訊息：{{ data.error }}</p>
        </section>

        <section v-if="activeCode" class="panel" data-nav="個股報價">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>
                        {{ data?.stock_name || activeCode }}
                        <span class="panel-note">{{ activeCode }}</span>
                    </h2>
                    <p class="panel-note">報價時間 {{ stock?.time || "--" }}</p>
                </div>
                <button type="button" class="chip" @click="clearStock">收起</button>
            </div>

            <template v-if="stock">
                <div class="quote-grid">
                    <div class="quote-card">
                        <div class="quote-name">成交價</div>
                        <div class="quote-value" :style="{ color: tone(stock.change) }">
                            {{ fixed(stock.price) }}
                        </div>
                        <div class="quote-change" :style="{ color: tone(stock.change) }">
                            {{ signed(stock.change, 2) }}（{{ signed(stock.pct, 2) }}%）
                        </div>
                        <div v-if="!isIndex" class="quote-meta">均價 {{ fixed(stock.avg) }}</div>
                    </div>
                    <div class="quote-card">
                        <div class="quote-name">當日區間</div>
                        <div class="quote-meta">開盤 {{ fixed(stock.open) }}</div>
                        <div class="quote-meta">最高 {{ fixed(stock.high) }}</div>
                        <div class="quote-meta">最低 {{ fixed(stock.low) }}</div>
                    </div>
                    <div class="quote-card">
                        <div class="quote-name">
                            成交統計
                            <span v-if="isIndex" class="quote-code">全市場合計</span>
                        </div>
                        <div class="quote-meta">
                            成交量 {{ (stock.volume ?? 0).toLocaleString() }} {{ lotUnit }}
                        </div>
                        <!-- 期貨的成交金額定義與個股不同 (要乘上契約乘數)，不顯示以免誤導 -->
                        <div v-if="!isFuture" class="quote-meta">
                            成交金額 {{ ((stock.amount ?? 0) / YI).toFixed(2) }} 億
                        </div>
                        <div class="quote-meta">
                            昨量 {{ (stock.yesterday_volume ?? 0).toLocaleString() }} {{ lotUnit }}
                        </div>
                    </div>
                    <div class="quote-card">
                        <div class="quote-name">量比</div>
                        <div
                            class="quote-value"
                            :style="{ color: tone((stock.volume_ratio ?? 1) - 1) }"
                        >
                            {{ fixed(stock.volume_ratio) }}
                        </div>
                        <div class="quote-change">與昨日同時間相比</div>
                        <template v-if="!isIndex">
                            <div class="quote-meta">
                                買 {{ fixed(stock.bid) }} x{{ (stock.bid_volume ?? 0).toLocaleString() }}
                            </div>
                            <div class="quote-meta">
                                賣 {{ fixed(stock.ask) }} x{{ (stock.ask_volume ?? 0).toLocaleString() }}
                            </div>
                        </template>
                    </div>
                </div>

                <div class="chart-head">
                    <div>
                        <h3 class="sub-head">走勢</h3>
                        <p class="panel-note">{{ chartNote }}</p>
                    </div>
                    <div class="chart-tabs">
                        <div v-if="sessions && period === 'intraday'" class="tabs" role="tablist">
                            <button
                                v-for="tab in SESSION_TABS"
                                :key="tab.key"
                                type="button"
                                class="tab"
                                :class="{ 'is-active': sessionView === tab.key }"
                                role="tab"
                                @click="sessionChoice = tab.key"
                            >
                                {{ tab.label }}
                            </button>
                        </div>
                        <div class="tabs" role="tablist">
                            <button
                                v-for="tab in PERIOD_TABS"
                                :key="tab.key"
                                type="button"
                                class="tab"
                                :class="{ 'is-active': period === tab.key }"
                                role="tab"
                                @click="period = tab.key"
                            >
                                {{ tab.label }}
                            </button>
                        </div>
                    </div>
                </div>

                <p v-if="historyError" class="notice">K 線載入失敗：{{ historyError }}</p>
                <p v-else-if="historyLoading" class="notice">正在取得歷史資料。</p>

                <div v-if="pending" class="confirm">
                    <div class="confirm-body">
                        <strong class="confirm-title">要向 Shioaji 取得歷史資料嗎？</strong>
                        <p v-if="pending.reason === 'notInDb'" class="confirm-text">
                            {{ activeCode }} 不在盤後資料庫裡 —— 那裡只有證交所與櫃買的
                            上市櫃個股收盤行情，期貨與指數都不在其中，
                            歷史 K 線只能向 Shioaji 取得。
                        </p>
                        <p v-else class="confirm-text">
                            盤後資料庫目前只有 {{ pending.available }} 個交易日，
                            畫這個區間需要約 {{ pending.needed }} 個。
                            下方圖表先以資料庫現有的資料呈現。
                        </p>
                        <p class="confirm-text">
                            改用 Shioaji 會消耗每日流量，估計約
                            <strong>{{ estimateMb(pending.months) }} MB</strong>
                            <template v-if="usage">
                                （今日已用 {{ usage.used_mb }} / {{ usage.limit_mb }} MB）
                            </template>
                            ，並佔用每日 20 次的歷史查詢額度。
                        </p>
                    </div>
                    <div class="confirm-actions">
                        <button type="button" class="chip is-active" @click="confirmFallback">
                            改用 Shioaji
                        </button>
                        <button type="button" class="chip" @click="pending = null">
                            {{ pending.reason === "notInDb" ? "不要查" : "維持資料庫的資料" }}
                        </button>
                    </div>
                </div>

                <template v-if="period === 'intraday'">
                    <VChart
                        v-if="intraday.candles.length"
                        class="chart"
                        :option="trendOption"
                        autoresize
                    />
                    <p v-else class="notice">
                        今日尚無分時資料，或 K 線查詢次數已達上限（見上方用量）。
                    </p>
                </template>
                <VChart
                    v-else-if="bars.length"
                    class="chart chart-candle"
                    :option="candleOption"
                    autoresize
                />
            </template>
        </section>

        <p v-else class="notice">
            在上方輸入代號或名稱即可查看個股即時行情與分時走勢。
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

/* 用量列：每日流量與 K 線次數都有硬上限，直接顯示免得要另外查 */
.usage-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
    margin-bottom: 20px;
    padding: 12px 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    font-size: 12px;
}

.usage-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.usage-label {
    color: var(--text-secondary);
}

.usage-value {
    color: var(--text-primary);
    font-weight: 600;
}

.usage-track {
    display: inline-block;
    width: 90px;
    height: 6px;
    border-radius: 3px;
    background: var(--neutral);
    overflow: hidden;
}

.usage-fill {
    display: block;
    height: 100%;
    background: var(--text-muted);
}

.usage-note {
    color: var(--text-muted);
}

.sub-head {
    margin: 0 0 4px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-secondary);
}

/* 常駐卡片可點開明細，用游標與邊框提示，不另外加按鈕破壞版面 */
.quote-card.is-clickable {
    cursor: pointer;
    transition: border-color 0.12s, box-shadow 0.12s;
}

.quote-card.is-clickable:hover,
.quote-card.is-clickable:focus-visible {
    border-color: var(--text-muted);
    outline: none;
}

.quote-card.is-selected {
    border-color: var(--text-primary);
    box-shadow: inset 0 0 0 1px var(--text-primary);
}

/* 要花額度的查詢一律先問過，不自作主張送出 */
.confirm {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    padding: 14px 16px;
    border: 1px solid var(--text-muted);
    border-radius: 8px;
    background: var(--surface-0);
}

.confirm-body {
    flex: 1;
    min-width: 280px;
}

.confirm-title {
    display: block;
    margin-bottom: 6px;
    font-size: 14px;
    color: var(--text-primary);
}

.confirm-text {
    margin: 0 0 4px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--text-secondary);
}

.confirm-actions {
    display: flex;
    gap: 8px;
}

/* 標題與週期切換同一列，窄螢幕改為上下堆疊 */
.chart-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.chart-head {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: flex-start;
    justify-content: space-between;
    margin: 20px 0 8px;
}
</style>
