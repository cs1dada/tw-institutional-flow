<script setup lang="ts">
/**
 * 類股資金流向。
 *
 * 後端只給當日原始資料，類股組成、排行、下鑽明細全部在前端算 (utils/flow.ts)，
 * 因此切換法人別、納入 ETF 等操作都不需要重新請求。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadDay, loadHistory, loadMeta, loadThemeHistory, loadThemes } from "@/api/dataSource"
import FlowTreemap from "@/components/FlowTreemap.vue"
import RankingChart from "@/components/RankingChart.vue"
import TrendChart from "@/components/TrendChart.vue"
import type {
    DateItem,
    DayData,
    FlowChild,
    HistoryData,
    IndustryFlow,
    Investor,
    StockFlow,
    ThemesData,
} from "@/types"
import {
    FIELD_OF,
    INVESTOR_LABELS,
    LARGE_INDUSTRIES,
    LARGE_TOP_STOCKS,
    MARKET_LABELS,
    OTHER_MAX_RATIO,
    SMALL_TOP_STOCKS,
    TOOLTIP_STOCKS,
    TREND_DAYS,
    expandStocks,
    industryFlow,
    industryStocks,
    limitChildren,
    marketNote,
    splitLimits,
    stockRanking,
} from "@/utils/flow"
import { themeFlow, themeStocks, themeStreak } from "@/utils/themeFlow"
import { formatDate, toYi } from "@/utils/format"
import { colors, cvdMode } from "@/utils/theme"

/** 分組維度：產業別或題材分類 */
type GroupMode = "industry" | "theme"

const RANKING_LIMIT = 20
/** 排行圖只取買超與賣超金額最大的各 N 個類股 */
const RANK_EACH_SIDE = 10

const dates = ref<DateItem[]>([])
const dateMeta = ref<Record<string, DateItem>>({})
const selectedDate = ref<string>("")
const investor = ref<Investor>("all")
const groupMode = ref<GroupMode>("industry")
const includeEtf = ref(false)
const showStocks = ref(true)
const drill = ref<string | null>(null)
const selected = ref<string | null>(null)

const day = ref<DayData | null>(null)
const history = ref<HistoryData | null>(null)
const themes = ref<ThemesData | null>(null)
const themeHistory = ref<HistoryData | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

/** 題材模式時為 true */
const isTheme = computed(() => groupMode.value === "theme")
/** 分組單位的中文稱呼，標題與說明文字共用 */
const unitLabel = computed(() => (isTheme.value ? "題材" : "類股"))

const stocks = computed(() => (day.value ? expandStocks(day.value) : []))

const flowItems = computed<IndustryFlow[]>(() => {
    if (!day.value) {
        return []
    }
    if (isTheme.value) {
        return themes.value ? themeFlow(stocks.value, themes.value, investor.value) : []
    }
    return industryFlow(day.value, stocks.value, investor.value, includeEtf.value)
})

/** 下鑽中的個股。當日個股已隨當日資料載入，不需再向伺服器要 */
const drillStocks = computed<StockFlow[]>(() => {
    if (!drill.value) {
        return []
    }
    if (isTheme.value) {
        return themes.value ? themeStocks(stocks.value, themes.value, drill.value, investor.value) : []
    }
    return industryStocks(stocks.value, drill.value, investor.value)
})

const tradedDrillStocks = computed(() =>
    drillStocks.value.filter((row) => Math.abs(row.amount) > 0).sort((a, b) => b.amount - a.amount),
)

/* ===== treemap ===== */

const limits = computed(() => splitLimits(flowItems.value))

/** treemap 已關閉自動排序，這裡先依面積由大到小排好 */
const treemapRows = computed(() => {
    const rows = drill.value ? tradedDrillStocks.value : flowItems.value
    return rows.slice().sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
})

const treemapTitle = computed(() =>
    drill.value ? `${drill.value}　個股資金分布` : `${unitLabel.value}資金分布`,
)

const treemapNote = computed(() => {
    if (drill.value) {
        return `面積為買賣超金額規模，<span class="swatch swatch-buy"></span>買超　`
            + `<span class="swatch swatch-sell"></span>賣超。共 ${drillStocks.value.length} 檔，`
            + `其中 ${tradedDrillStocks.value.length} 檔有買賣超。`
    }
    const coverage = isTheme.value ? "僅涵蓋題材分類表收錄的個股，一檔可同時計入多個題材。" : ""
    if (showStocks.value) {
        return `外框面積為${unitLabel.value}買賣超淨額規模，內部依同方向個股的佔比切分：前 ${LARGE_INDUSTRIES} 大`
            + `${unitLabel.value}切 ${LARGE_TOP_STOCKS} 檔，其餘切 ${SMALL_TOP_STOCKS} 檔，更後面的合併為右下角的「其他」`
            + `（面積最多佔 ${Math.round(OTHER_MAX_RATIO * 100)}%）。`
            + `<span class="swatch swatch-buy"></span>買超　`
            + `<span class="swatch swatch-sell"></span>賣超。點擊可下鑽至該${unitLabel.value}全部個股。${coverage}`
    }
    return `面積為買賣超金額規模，<span class="swatch swatch-buy"></span>買超　`
        + `<span class="swatch swatch-sell"></span>賣超。點擊${unitLabel.value}可下鑽至個股。${coverage}`
})

/* ===== 排行圖 ===== */

const rankingRows = computed(() => {
    if (drill.value) {
        return tradedDrillStocks.value
    }
    // 只取買超與賣超金額最大的各 10 個，避免中間大量接近零的類股佔版面
    const sorted = flowItems.value.slice().sort((a, b) => b.amount - a.amount)
    const top = sorted.slice(0, RANK_EACH_SIDE)
    const bottom = sorted.slice(-RANK_EACH_SIDE).filter((row) => !top.includes(row))
    return [...top, ...bottom]
})

const rankingTitle = computed(() =>
    drill.value ? `${drill.value}　個股買賣超排名` : `${unitLabel.value}資金流向排行`,
)

const rankingNote = computed(() =>
    drill.value
        ? `第 1 名至第 ${tradedDrillStocks.value.length} 名，依買賣超金額排序`
        : `買超與賣超金額最大的各 ${RANK_EACH_SIDE} 個${unitLabel.value}`,
)

/* ===== 表格 ===== */

const buyRanking = computed(() =>
    day.value ? stockRanking(stocks.value, investor.value, "buy", RANKING_LIMIT) : [],
)

const sellRanking = computed(() =>
    day.value ? stockRanking(stocks.value, investor.value, "sell", RANKING_LIMIT) : [],
)

/** 顯示全部連續 2 天以上的類股/題材，避免截斷後只剩買超側 */
const streakRows = computed(() => {
    if (isTheme.value) {
        if (!themeHistory.value) {
            return []
        }
        const days = day.value?.streak_days ?? 10
        return themeStreak(themeHistory.value, investor.value, days).filter((row) => row.streak_days >= 2)
    }
    return (day.value?.streak?.[FIELD_OF[investor.value]] ?? []).filter((row) => row.streak_days >= 2)
})

const detailStocks = computed<StockFlow[]>(() => {
    if (!selected.value) {
        return []
    }
    if (isTheme.value) {
        return themes.value ? themeStocks(stocks.value, themes.value, selected.value, investor.value) : []
    }
    return industryStocks(stocks.value, selected.value, investor.value)
})

const trendItems = computed(() => {
    const source = isTheme.value ? themeHistory.value : history.value
    if (!selected.value || !source) {
        return []
    }
    return (source.industries[selected.value] ?? []).slice(-TREND_DAYS)
})

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    if (!day.value) {
        return "載入中"
    }
    const note = marketNote(dateMeta.value[day.value.date])
    return `${formatDate(day.value.date)}　${INVESTOR_LABELS[investor.value]}`
        + (note ? `　⚠ ${note}，資料尚未齊全` : "")
})

/* ===== tooltip ===== */

function leadersHtml(row: IndustryFlow): string {
    const leaders = (row.children ?? []).filter((kid) => !kid.is_other).slice(0, TOOLTIP_STOCKS)
    if (!leaders.length) {
        return ""
    }
    const c = colors()
    const lines = leaders.map((kid) => `${kid.code} ${kid.name}　${toYi(kid.amount, 2)} 億`)
    return `<div style="margin-top:6px;padding-top:6px;border-top:1px solid ${c.border}">`
        + `<span style="color:${c.muted}">主要個股</span><br>${lines.join("<br>")}</div>`
}

function industryTooltip(row: IndustryFlow): string {
    const c = colors()
    return `<strong>${row.industry}</strong><br>`
        + `三大法人　${toYi(row.total_amt)} 億<br>`
        + `外資　　　${toYi(row.foreign_amt)} 億<br>`
        + `投信　　　${toYi(row.trust_amt)} 億<br>`
        + `自營商　　${toYi(row.dealer_amt)} 億<br>`
        + `<span style="color:${c.muted}">買超 ${row.buy_count} 檔 / 賣超 ${row.sell_count} 檔，`
        + `共 ${row.stock_count} 檔</span>${leadersHtml(row)}`
}

function stockTooltip(row: StockFlow, rank?: number): string {
    const c = colors()
    const market = MARKET_LABELS[row.market] ?? row.market
    return `<strong>${rank ? `第 ${rank} 名　` : ""}${row.code} ${row.name}</strong><br>`
        + `買賣超　${toYi(row.amount, 2)} 億<br>`
        + `外資　　${toYi(row.foreign_amt, 2)} 億<br>`
        + `投信　　${toYi(row.trust_amt, 2)} 億<br>`
        + `自營商　${toYi(row.dealer_amt, 2)} 億<br>`
        + `<span style="color:${c.muted}">${market}　收盤 `
        + `${row.close === null ? "--" : row.close.toFixed(2)}</span>`
}

/** 類股區塊內的個股節點 tooltip */
function compositionTooltip(row: FlowChild | IndustryFlow): string {
    const kid = row as FlowChild
    if (!kid.code && !kid.is_other) {
        return industryTooltip(row as IndustryFlow)
    }
    const c = colors()
    if (kid.is_other) {
        return `<strong>${kid.name}</strong><br>所屬類股　${kid.industry}<br>`
            + `合計買賣超　${toYi(kid.amount, 2)} 億`
            + (kid.areaCapped
                ? `<br><span style="color:${c.muted}">格子面積上限 `
                  + `${Math.round(OTHER_MAX_RATIO * 100)}%，實際佔比更高</span>`
                : "")
    }
    return `<strong>${kid.code} ${kid.name}</strong><br>所屬類股　${kid.industry}<br>`
        + `買賣超　　${toYi(kid.amount, 2)} 億<br>`
        + `<span style="color:${c.muted}">${MARKET_LABELS[kid.market ?? ""] ?? kid.market}　收盤 `
        + `${kid.close === null || kid.close === undefined ? "--" : kid.close.toFixed(2)}</span>`
}

/* ===== 互動 ===== */

function enterDrill(row: IndustryFlow | StockFlow) {
    const industry = (row as IndustryFlow).industry
    if (!industry) {
        return
    }
    drill.value = industry
    selected.value = industry
}

function exitDrill() {
    drill.value = null
}

async function load(date: string) {
    loading.value = true
    error.value = null
    try {
        day.value = await loadDay(date)
        selectedDate.value = day.value.date
        // 切換日期後原本下鑽或選取的類股可能不存在
        if (drill.value && !flowItems.value.some((row) => row.industry === drill.value)) {
            drill.value = null
        }
        if (!selected.value || !flowItems.value.some((row) => row.industry === selected.value)) {
            selected.value = flowItems.value.length ? flowItems.value[0].industry : null
        }
    } catch (err) {
        error.value = (err as Error).message
    } finally {
        loading.value = false
    }
}

watch(selectedDate, (date) => {
    if (date && date !== day.value?.date) {
        load(date)
    }
})

/** 題材模式所需的分類結構與歷史，第一次切換時才載入 */
async function ensureThemeData() {
    if (!themes.value) {
        themes.value = await loadThemes()
    }
    if (!themeHistory.value) {
        themeHistory.value = await loadThemeHistory()
    }
}

watch(groupMode, async (mode) => {
    // 切換分組維度後，原本下鑽/選取的名稱在另一種分組未必存在
    drill.value = null
    if (mode === "theme") {
        try {
            await ensureThemeData()
        } catch (err) {
            error.value = (err as Error).message
            return
        }
    }
    selected.value = flowItems.value.length ? flowItems.value[0].industry : null
})

onMounted(async () => {
    try {
        const meta = await loadMeta()
        dates.value = meta.dates ?? []
        for (const item of dates.value) {
            dateMeta.value[item.date] = item
        }
        // 優先選資料齊全的最新交易日
        const preferred = dates.value.find((item) => item.complete) ?? dates.value[0]
        if (preferred) {
            selectedDate.value = preferred.date
            await load(preferred.date)
        } else {
            loading.value = false
        }
    } catch (err) {
        error.value = (err as Error).message
        loading.value = false
    }

    // 趨勢圖的資料與當日無關，載入一次即可
    loadHistory()
        .then((data) => {
            history.value = data
        })
        .catch((err) => console.error(err))
})

function dateLabel(item: DateItem): string {
    const note = marketNote(item)
    return formatDate(item.date) + (note ? `（${note}）` : "")
}
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>台股三大法人類股資金流向</h1>
                <p class="subtitle">
                    上市 + 上櫃合併統計，金額為<strong>估算值</strong>（買賣超股數 × 當日收盤價），單位億元
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div class="controls">
            <label class="control">
                <span class="control-label">交易日</span>
                <select v-model="selectedDate">
                    <option v-for="item in dates" :key="item.date" :value="item.date">
                        {{ dateLabel(item) }}
                    </option>
                </select>
            </label>

            <div class="control">
                <span class="control-label">法人別</span>
                <div class="tabs" role="tablist">
                    <button
                        v-for="(label, key) in INVESTOR_LABELS"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': investor === key }"
                        role="tab"
                        @click="investor = key as Investor"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>

            <div class="control">
                <span class="control-label">分組方式</span>
                <div class="tabs" role="tablist">
                    <button
                        v-for="opt in ([
                            { key: 'industry', label: '產業別' },
                            { key: 'theme', label: '題材分類' },
                        ] as const)"
                        :key="opt.key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': groupMode === opt.key }"
                        role="tab"
                        @click="groupMode = opt.key"
                    >
                        {{ opt.label }}
                    </button>
                </div>
            </div>

            <label class="control control-inline">
                <input v-model="cvdMode" type="checkbox">
                <span>色盲友善配色</span>
            </label>

            <label v-if="!isTheme" class="control control-inline">
                <input v-model="includeEtf" type="checkbox">
                <span>納入 ETF</span>
            </label>

            <label class="control control-inline">
                <input v-model="showStocks" type="checkbox">
                <span>{{ unitLabel }}內顯示個股</span>
            </label>
        </div>

        <section class="panel" data-nav="類股資金分布">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>{{ treemapTitle }}</h2>
                    <!-- eslint-disable-next-line vue/no-v-html -->
                    <p class="panel-note" v-html="treemapNote"></p>
                </div>
                <button v-if="drill" type="button" class="back-btn" @click="exitDrill">
                    返回全{{ unitLabel }}
                </button>
            </div>
            <FlowTreemap
                :rows="treemapRows"
                :name-of="(row: any) => (drill ? `${row.code} ${row.name}` : row.industry)"
                :children-of="!drill && showStocks ? (row: any) => limitChildren(row, limits[row.industry]) : null"
                :child-name-of="(kid: any) => (kid.is_other ? kid.name : `${kid.code} ${kid.name}`)"
                :tooltip="drill ? stockTooltip : compositionTooltip"
                :digits="drill ? 2 : undefined"
                :height="!drill && showStocks ? '620px' : undefined"
                @select="enterDrill"
            />
        </section>

        <section class="panel" data-nav="資金流向排行">
            <div class="panel-head">
                <h2>{{ rankingTitle }}</h2>
                <p class="panel-note">{{ rankingNote }}</p>
            </div>
            <RankingChart
                :rows="rankingRows"
                :name-of="(row: any, rank: number) => (drill ? `${rank}. ${row.code} ${row.name}` : row.industry)"
                :tooltip="drill ? stockTooltip : industryTooltip"
                :digits="drill ? 2 : undefined"
                :label-width="drill ? 150 : 110"
                @select="enterDrill"
            />
        </section>

        <section class="panel" data-nav="類股細節">
            <div class="panel-head">
                <h2>{{ selected ? `${selected}　${unitLabel}細節` : `${unitLabel}細節` }}</h2>
                <p class="panel-note">於上方點選{{ unitLabel }}後顯示近 20 個交易日趨勢與個股明細</p>
            </div>
            <div class="detail-grid">
                <TrendChart
                    v-if="selected && trendItems.length"
                    :industry="selected"
                    :items="trendItems"
                />
                <div v-else class="chart"></div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>代號</th><th>名稱</th>
                                <th class="num">收盤</th><th class="num">買賣超（億）</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="!detailStocks.length" class="empty-row">
                                <td colspan="4">無資料</td>
                            </tr>
                            <tr v-for="row in detailStocks" :key="row.code">
                                <td>{{ row.code }}</td>
                                <td>{{ row.name }}</td>
                                <td class="num">{{ row.close === null ? "--" : row.close.toFixed(2) }}</td>
                                <td class="num" :class="row.amount >= 0 ? 'val-buy' : 'val-sell'">
                                    {{ toYi(row.amount, 2) }}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <section class="panel" data-nav="連續買賣超">
            <div class="panel-head">
                <h2>連續買賣超{{ unitLabel }}</h2>
                <p class="panel-note">
                    近 10 個交易日中，資金持續同方向流動的{{ unitLabel }}，依期間累計金額的絕對值由大到小排序
                </p>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>{{ unitLabel }}</th><th>方向</th>
                            <th class="num">連續天數</th><th class="num">期間累計（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!streakRows.length" class="empty-row">
                            <td colspan="4">無資料</td>
                        </tr>
                        <tr v-for="row in streakRows" :key="row.industry">
                            <td>{{ row.industry }}</td>
                            <td :class="row.direction === 'buy' ? 'val-buy' : 'val-sell'">
                                {{ row.direction === "buy" ? "連續買超" : "連續賣超" }}
                            </td>
                            <td class="num">{{ row.streak_days }}</td>
                            <td class="num" :class="row.total_amt >= 0 ? 'val-buy' : 'val-sell'">
                                {{ toYi(row.total_amt, 2) }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel" data-nav="個股買賣超排行">
            <div class="panel-head">
                <h2>個股買賣超排行</h2>
                <p class="panel-note">當日買超與賣超金額前 20 名（不含 ETF）</p>
            </div>
            <div class="detail-grid">
                <div v-for="side in ([
                    { title: '買超前 20', rows: buyRanking },
                    { title: '賣超前 20', rows: sellRanking },
                ] as const)" :key="side.title" class="table-wrap">
                    <h3 class="table-title">{{ side.title }}</h3>
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>代號</th><th>名稱</th><th>類股</th><th class="num">金額（億）</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="!side.rows.length" class="empty-row">
                                <td colspan="4">無資料</td>
                            </tr>
                            <tr v-for="row in side.rows" :key="row.code">
                                <td>{{ row.code }}</td>
                                <td>{{ row.name }}</td>
                                <td>{{ row.industry }}</td>
                                <td class="num" :class="row.amount >= 0 ? 'val-buy' : 'val-sell'">
                                    {{ toYi(row.amount, 2) }}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    </section>
</template>
