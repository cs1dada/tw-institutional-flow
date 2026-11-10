<script setup lang="ts">
/**
 * 大盤籌碼圖：上方為指數收盤，下方為三大法人買賣超或融資融券，
 * 可切換上市／上櫃與指標。下方另列「融資餘額與今天相近的日子」，
 * 對照同樣的融資水位當時指數在哪裡。
 *
 * 官方全市場擔保維持率與追繳處分來自臺股儀表板，只有全市場合計，
 * 切換上市上櫃時畫的是同一條。
 */
import { computed, ref } from "vue"
import VChart from "vue-echarts"

import MarketChipInsight from "@/components/MarketChipInsight.vue"
import type { ChipRow, CreditRow, IndexRow, MarketPayload } from "@/types"
import { formatDate } from "@/utils/format"
import { expandRows } from "@/utils/indexBars"
import {
    CHIP_METRICS,
    MARKET_LABELS,
    VIX_PANIC,
    callPeaks,
    expandChip,
    expandCredit,
    maintenanceLows,
    similarMarginDays,
    vixHighs,
    vixLevel,
    type ChipMetric,
    type MarketKey,
} from "@/utils/market"
import { baseTooltip, buyColor, colors, sellColor } from "@/utils/theme"

const props = defineProps<{
    taiex: IndexRow[]
    market: MarketPayload | null
}>()

const RANGES = [
    { key: 63, label: "3 月" },
    { key: 125, label: "6 月" },
    { key: 250, label: "1 年" },
] as const

const marketKey = ref<MarketKey>("TWSE")
const metric = ref<ChipMetric>("total")
const span = ref<number>(125)

const metricInfo = computed(() => CHIP_METRICS.find((item) => item.key === metric.value)!)

const rows = computed<ChipRow[]>(() =>
    props.market ? expandChip(props.market, marketKey.value) : [],
)

const indexName = computed(() => (marketKey.value === "TWSE" ? "加權指數" : "櫃買指數"))

/** 對應市場的指數收盤，以日期查詢 */
const closes = computed(() => {
    const source = marketKey.value === "TWSE"
        ? props.taiex
        : props.market ? expandRows(props.market.tpex_index) : []
    return new Map(source.map((row) => [row.date, row.close]))
})

const visible = computed(() => rows.value.slice(-span.value))

/** 台指與美國 VIX，以日期查詢；美股休市的日子對不到就留空 */
const twVix = computed(() => new Map(props.market?.macro.TWVIX ?? []))
const usVix = computed(() => new Map(props.market?.macro.USVIX ?? []))

/** 官方全市場信用交易指標 */
const credit = computed<CreditRow[]>(() => (props.market ? expandCredit(props.market) : []))
const creditByDate = computed(() => new Map(credit.value.map((row) => [row.date, row])))

const similar = computed(() => similarMarginDays(rows.value, closes.value))

const coverage = computed(() => {
    const all = rows.value
    if (!all.length) {
        return ""
    }
    const margin = all.filter((row) => row.maintenance !== null).length
    return `共 ${all.length} 個交易日（${formatDate(all[0].date)} 起），其中 ${margin} 天有維持率`
})

/** 下方柱狀圖的配色說明：法人看買賣超正負，餘額類看較前一日增減 */
const colorNote = computed(() => {
    const info = metricInfo.value
    const officialSince = credit.value.length ? `官方資料從 ${formatDate(credit.value[0].date)} 起。` : ""
    if (info.key === "maintenance") {
        return "下方黑線為本站估算的民間版：各檔融資張數乘以收盤價的總市值，除以融資餘額，只看融資部位。"
            + `綠線為臺股儀表板公布的官方全市場擔保維持率，以投資人整戶融資融券合併計算，通常比民間版高，且不分上市上櫃。${officialSince}`
    }
    if (info.kind === "ratio") {
        return "下方為融資餘額占總市值的比重，比重越高代表市場使用融資槓桿越多。市值資料來自臺股儀表板，上櫃只有近兩個月。"
    }
    if (info.kind === "calls") {
        return "下方柱狀圖為整戶擔保維持率低於 130% 的戶數 (全市場，不分上市上櫃)，低於 130% 就會被券商追繳。"
            + `資料來自臺股儀表板，${officialSince}`
    }
    if (info.kind === "vix") {
        const first = props.market?.macro.TWVIX?.[0]?.[0]
        const since = first
            ? `期交所只保留約三個月的檔案，台指 VIX 從 ${formatDate(first)} 起，之後每天累積。`
            : ""
        return `下方橘線為台指 VIX，藍線為美國 VIX，虛線為恐慌門檻 (台指 ${VIX_PANIC.TW}、美國 ${VIX_PANIC.US})。${since}`
    }
    if (info.kind === "net") {
        return "下方柱狀圖：紅色為買超，綠色為賣超。"
    }
    return `下方柱狀圖：紅色為${info.label}較前一日增加，綠色為減少。`
})

function metricValue(row: ChipRow): number | null {
    if (metric.value === "vix") {
        return null
    }
    if (metric.value === "calls") {
        return creditByDate.value.get(row.date)?.below_acc ?? null
    }
    const value = row[metric.value]
    return typeof value === "number" ? value : null
}

function fmt(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return value.toLocaleString("zh-TW", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    })
}

function signedFmt(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return (value > 0 ? "+" : "") + fmt(value, digits)
}

function colored(value: number | null | undefined, text: string): string {
    if (!value) {
        return text
    }
    return `<span style="color:${value > 0 ? buyColor() : sellColor()}">${text}</span>`
}

const chartOption = computed(() => {
    const data = visible.value
    if (!data.length) {
        return {}
    }
    const c = colors()
    const info = metricInfo.value
    const labels = data.map((row) => formatDate(row.date).slice(5))
    const indexLine = data.map((row) => closes.value.get(row.date) ?? "-")
    const values = data.map(metricValue)
    const isNet = info.kind === "net"
    const isMaintenance = info.key === "maintenance"
    const isLine = isMaintenance || info.kind === "ratio"
    const isVix = info.kind === "vix"
    const isCalls = info.kind === "calls"

    /**
     * 圖上要標出的日子，與下方表格一致：融資餘額為相近日、維持率為最低的 5 天、
     * VIX 為台美各自最高的 3 天、追繳戶數暴增的日子。上方指數線一律標日期；維持率與 VIX 另外在下方的線上標數值。
     * 美股日期不一定是台股交易日，對到下一個台股交易日。
     */
    interface Mark {
        date: string
        color: string
        lower?: { value: number; text: string; below: boolean }
    }
    const tradingDates = rows.value.map((row) => row.date)
    const toTrading = (date: string) => tradingDates.find((day) => day >= date) ?? date
    let marks: Mark[] = []
    if (metric.value === "margin") {
        marks = (similar.value?.days ?? []).map((day) => ({ date: day.date, color: c.trust }))
    } else if (isCalls) {
        marks = callPeaks(credit.value).map((point) => ({
            date: point.date,
            color: c.trust,
            lower: { value: point.value, text: fmt(point.value, 0), below: false },
        }))
    } else if (isMaintenance) {
        marks = maintenanceLows(rows.value).map((point) => ({
            date: point.date,
            color: c.trust,
            lower: { value: point.value, text: `${fmt(point.value, 2)}%`, below: true },
        }))
    } else if (isVix) {
        marks = vixHighs(twVix.value, usVix.value, tradingDates[0] ?? "").map((point) => {
            const date = toTrading(point.date)
            const source = point.market === "TW" ? twVix.value : usVix.value
            return {
                date,
                color: point.market === "TW" ? c.trust : c.foreign,
                lower: { value: source.get(date) ?? point.value, text: fmt(point.value, 2), below: false },
            }
        })
    }
    const markByDate = new Map(marks.map((mark) => [mark.date, mark]))

    /** 三角形尖端指向標記的那一點：在線上方時朝下，在線下方時朝上 */
    const markerSeries = (lower: boolean) => ({
        name: "標記日",
        type: "scatter",
        ...(lower ? { xAxisIndex: 1, yAxisIndex: 1 } : {}),
        data: data.map((row, index) => {
            const mark = markByDate.get(row.date)
            if (!mark || (lower && !mark.lower)) {
                return "-"
            }
            const below = lower && mark.lower!.below
            return {
                value: lower ? mark.lower!.value : (closes.value.get(row.date) ?? "-"),
                symbolRotate: below ? 0 : 180,
                symbolOffset: [0, below ? 9 : -9],
                itemStyle: { color: mark.color },
                label: {
                    show: true,
                    position: below ? "bottom" : "top",
                    distance: 12,
                    color: mark.color,
                    fontSize: 11,
                    fontWeight: 600,
                    formatter: lower ? mark.lower!.text : labels[index],
                },
            }
        }),
        symbol: "triangle",
        symbolSize: [11, 9],
        tooltip: { show: false },
        z: 5,
    })

    /** 兩條門檻只差 2 點，標籤一上一下才不會疊在一起 */
    const panicLine = (value: number, color: string, label: string, position: string) => ({
        silent: true,
        symbol: "none",
        lineStyle: { type: "dashed", color, width: 1 },
        label: { formatter: `${label} ${value}`, color, fontSize: 11, position },
        data: [{ yAxis: value }],
    })
    const vixLine = (name: string, source: Map<string, number>, color: string, markLine: object) => ({
        name,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: data.map((row) => source.get(row.date) ?? "-"),
        symbol: "none",
        connectNulls: true,
        lineStyle: { width: 1.8, color },
        itemStyle: { color },
        markLine,
    })

    const metricSeries = isVix
        ? [
            vixLine("台指 VIX", twVix.value, c.trust, panicLine(VIX_PANIC.TW, c.trust, "台指恐慌", "insideEndTop")),
            vixLine("美國 VIX", usVix.value, c.foreign, panicLine(VIX_PANIC.US, c.foreign, "美國恐慌", "insideEndBottom")),
        ]
        : isLine
        ? [
            {
                name: isMaintenance ? "民間版維持率" : info.label,
                type: "line",
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: values.map((value) => value ?? "-"),
                symbol: "none",
                connectNulls: true,
                lineStyle: { width: 1.8, color: c.text },
                itemStyle: { color: c.text },
            },
            ...(isMaintenance
                ? [{
                    name: "官方全市場維持率",
                    type: "line",
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: data.map((row) => creditByDate.value.get(row.date)?.keep_rate ?? "-"),
                    symbol: "none",
                    connectNulls: true,
                    lineStyle: { width: 1.8, color: c.dealer },
                    itemStyle: { color: c.dealer },
                }]
                : []),
        ]
        : isCalls
        ? [{
            name: "追繳戶數",
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: values.map((value) => value ?? "-"),
            itemStyle: { color: c.dealer, opacity: 0.75 },
        }]
        : [{
            name: info.label,
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: values.map((value, index) => {
                if (value === null) {
                    return "-"
                }
                // 法人以正負上色；餘額類以較前一日增減上色
                const prev = index ? values[index - 1] : null
                const sign = isNet ? value : prev === null ? 0 : value - prev
                return {
                    value,
                    itemStyle: {
                        color: sign >= 0 ? buyColor() : sellColor(),
                        opacity: isNet ? 0.85 : 0.55,
                    },
                }
            }),
        }]

    return {
        animation: false,
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "line" },
            formatter: (params: any[]) => {
                const row = data[params[0]?.dataIndex]
                if (!row) {
                    return ""
                }
                const close = closes.value.get(row.date)
                const vixText = (value: number | undefined, market: "TW" | "US") =>
                    value === undefined ? "--" : `${fmt(value, 2)}（${vixLevel(value, market).label}）`
                const official = creditByDate.value.get(row.date)
                const pct = (value: number | null | undefined, digits = 2) =>
                    value === null || value === undefined ? "--" : `${fmt(value, digits)}%`
                return [
                    `<strong>${formatDate(row.date)}</strong>`,
                    `${indexName.value}　${close === undefined ? "--" : fmt(close, 2)}`,
                    `外資　${colored(row.foreign, signedFmt(row.foreign))} 億`,
                    `投信　${colored(row.trust, signedFmt(row.trust))} 億`,
                    `自營商　${colored(row.dealer, signedFmt(row.dealer))} 億`,
                    `合計　${colored(row.total, signedFmt(row.total))} 億`,
                    `融資餘額　${fmt(row.margin)} 億`,
                    `融資維持率　${pct(row.maintenance)}（官方全市場 ${pct(official?.keep_rate)}）`,
                    `融券餘額　${fmt(row.short_units, 0)} 張`,
                    `融資占市值　${pct(row.margin_ratio, 3)}　信用交易占成交　${pct(row.credit_ratio)}`,
                    `追繳戶數　${official?.below_acc == null ? "--" : `${fmt(official.below_acc, 0)} 戶`}`,
                    `台指 VIX　${vixText(twVix.value.get(row.date), "TW")}`,
                    `美國 VIX　${vixText(usVix.value.get(row.date), "US")}`,
                ].join("<br>")
            },
        },
        // 上下兩張圖各自加粗標題，下方再鋪淺底色，一眼分出指數與籌碼
        title: [
            {
                text: indexName.value,
                left: 64,
                top: 0,
                textStyle: { color: c.foreign, fontSize: 13, fontWeight: 600 },
            },
            {
                text: isVix
                    ? "恐慌指標 VIX（橘：台指、藍：美國）"
                    : isMaintenance
                    ? `${MARKET_LABELS[marketKey.value]}融資維持率（黑：民間版、綠：官方全市場）`
                    : isCalls
                    ? "全市場追繳戶數（維持率低於 130%）"
                    : info.kind === "ratio"
                    ? `${MARKET_LABELS[marketKey.value]}融資餘額占市值（%）`
                    : `${MARKET_LABELS[marketKey.value]}${info.label}（${info.unit}）`,
                left: 64,
                top: 250,
                textStyle: { color: c.text, fontSize: 13, fontWeight: 600 },
            },
        ],
        grid: [
            // 上方留白給標題與相近日的標記，否則最高點附近的標記會被裁掉
            { left: 64, right: 20, top: 40, height: 196 },
            {
                left: 64,
                right: 20,
                top: 274,
                height: 150,
                show: true,
                backgroundColor: c.surface0,
                borderWidth: 0,
            },
        ],
        xAxis: [
            {
                type: "category",
                data: labels,
                axisLine: { lineStyle: { color: c.border } },
                axisTick: { show: false },
                axisLabel: { show: false },
            },
            {
                type: "category",
                gridIndex: 1,
                data: labels,
                axisLine: { lineStyle: { color: c.border } },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
            },
        ],
        yAxis: [
            {
                scale: true,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
            {
                gridIndex: 1,
                scale: !isNet,
                splitNumber: 3,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
        ],
        series: [
            {
                name: indexName.value,
                type: "line",
                data: indexLine,
                symbol: "none",
                connectNulls: true,
                // 指數用藍線加漸層面積，和下方的紅綠柱狀圖明顯區隔
                lineStyle: { width: 2, color: c.foreign },
                itemStyle: { color: c.foreign },
                areaStyle: {
                    origin: "start",
                    color: {
                        type: "linear",
                        x: 0,
                        y: 0,
                        x2: 0,
                        y2: 1,
                        colorStops: [
                            { offset: 0, color: `${c.foreign}40` },
                            { offset: 1, color: `${c.foreign}05` },
                        ],
                    },
                },
            },
            markerSeries(false),
            ...metricSeries,
            ...(isMaintenance || isVix || isCalls ? [markerSeries(true)] : []),
        ],
    }
})
</script>

<template>
    <section class="panel" data-nav="大盤籌碼">
        <div class="panel-head panel-head-row">
            <div>
                <h2>{{ MARKET_LABELS[marketKey] }}{{ indexName }}＋{{ metricInfo.label }}</h2>
                <p class="panel-note">
                    三大法人為全市場買賣金額，融資融券為全市場餘額；
                    滑鼠移到圖上可看當天全部籌碼。{{ coverage }}
                </p>
            </div>
        </div>

        <div class="controls">
            <div class="tabs" role="tablist">
                <button
                    v-for="(label, key) in MARKET_LABELS"
                    :key="key"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': marketKey === key }"
                    @click="marketKey = key as MarketKey"
                >
                    {{ label }}
                </button>
            </div>
            <div class="tabs" role="tablist">
                <button
                    v-for="item in CHIP_METRICS"
                    :key="item.key"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': metric === item.key }"
                    @click="metric = item.key"
                >
                    {{ item.label }}
                </button>
            </div>
            <div class="tabs" role="tablist">
                <button
                    v-for="item in RANGES"
                    :key="item.key"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': span === item.key }"
                    @click="span = item.key"
                >
                    {{ item.label }}
                </button>
            </div>
        </div>

        <VChart v-if="visible.length" class="chart chip-chart" :option="chartOption" autoresize />
        <p v-else class="notice">尚無籌碼資料，請先執行 python scripts/ingest_market.py</p>
        <p v-if="visible.length" class="panel-note color-note">{{ colorNote }}</p>

        <!-- 相近日只跟融資餘額有關，切到其他指標時不顯示 -->
        <div v-if="metric === 'margin' && similar && similar.days.length" class="similar">
            <h3 class="table-title">
                {{ MARKET_LABELS[marketKey] }}融資餘額跟今天相近的日子
                <span class="similar-note">
                    近三個月內 (不含最近 5 天) 融資餘額最接近的 3 天，彼此至少相隔 5 個交易日；
                    也就是指數線上三角形標出的日子
                </span>
            </h3>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th class="num">融資餘額（億）</th>
                            <th class="num">和今天差</th>
                            <th class="num">{{ indexName }}收盤</th>
                            <th class="num">今天比當時</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr class="today-row">
                            <td>今天 {{ formatDate(similar.today.date).slice(5) }}</td>
                            <td class="num">{{ fmt(similar.today.value) }}</td>
                            <td class="num">--</td>
                            <td class="num">{{ fmt(closes.get(similar.today.date), 2) }}</td>
                            <td class="num">--</td>
                        </tr>
                        <tr v-for="day in similar.days" :key="day.date">
                            <td>{{ formatDate(day.date) }}</td>
                            <td class="num">{{ fmt(day.margin) }}</td>
                            <td class="num" :class="day.diff >= 0 ? 'val-buy' : 'val-sell'">
                                {{ signedFmt(day.diff) }}
                            </td>
                            <td class="num">{{ fmt(day.close, 2) }}</td>
                            <td
                                class="num"
                                :class="day.pct === null ? '' : day.pct >= 0 ? 'val-buy' : 'val-sell'"
                            >
                                {{ day.pct === null ? "--" : `${signedFmt(day.pct, 1)}%` }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p class="panel-note">
                同樣的融資水位，指數卻比當時低，代表散戶槓桿沒有跟著退場；反之則是籌碼相對乾淨。
            </p>
        </div>

        <!-- 其他指標的摘要與對照表，內容跟著上方選的指標換 -->
        <MarketChipInsight
            v-if="metric !== 'margin'"
            :rows="rows"
            :closes="closes"
            :metric="metric"
            :metric-label="metricInfo.label"
            :market-label="MARKET_LABELS[marketKey]"
            :index-name="indexName"
            :tw-vix="twVix"
            :us-vix="usVix"
            :credit="credit"
            :credit-history="market?.credit_history"
            :market-key="marketKey"
        />
    </section>
</template>

<style scoped>
.controls {
    margin-bottom: 8px;
}

/* 指標有十個，手機寬度下換行而不是把每個字擠成直排 */
.controls .tabs {
    flex-wrap: wrap;
}

.controls .tab {
    white-space: nowrap;
}

.chip-chart {
    height: 450px;
}

.color-note {
    margin-top: 0;
}

.similar {
    margin-top: 12px;
}

.similar-note {
    margin-left: 8px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
}

.today-row td {
    font-weight: 600;
}
</style>
