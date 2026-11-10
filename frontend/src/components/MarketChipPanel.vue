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
    OFFICIAL_ZONES,
    VIX_PANIC,
    VIX_ZONES,
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

/** 指數均線，與 K 線圖的日線相同 */
const MA_SIZES = [5, 20, 60] as const

/**
 * 各均線以日期查詢。用指數的完整日線計算 (closes 依日期由舊到新)，
 * 不是只算畫面上的區間，否則區間開頭的 60 日線會空一段
 */
const maByDate = computed(() => {
    const entries = [...closes.value]
    return MA_SIZES.map((size) => {
        const result = new Map<string, number>()
        let sum = 0
        entries.forEach(([date, close], index) => {
            sum += close
            if (index >= size) {
                sum -= entries[index - size][1]
            }
            if (index >= size - 1) {
                result.set(date, +(sum / size).toFixed(2))
            }
        })
        return result
    })
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
        return "下方綠線為本站估算的民間版：各檔融資張數乘以收盤價的總市值，除以融資餘額，只看融資部位。"
            + `彩色線為臺股儀表板公布的官方全市場擔保維持率，以投資人整戶融資融券合併計算，通常比民間版高，且不分上市上櫃。${officialSince}`
            + "彩色線依玉山證券投顧對官方維持率的分區上色，虛線為各分區的門檻，配色參考 TradingView 技術分析的總結儀表："
            + "150% 以下恐慌 (深紅)、150% 到 160% 偏低 (紅)、160% 到 180% 正常 (灰)、"
            + "180% 到 200% 偏熱與高熱 (藍)、200% 以上極度樂觀 (深藍)。"
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
        return "下方彩色線為台指 VIX，依所在分區分段上色，綠線為美國 VIX。配色參考 TradingView 技術分析的總結儀表："
            + `18 以下平靜 (藍)、18 到 25 正常 (灰)、25 以上警戒 (紅)、${VIX_PANIC.TW} 以上恐慌 (深紅)；`
            + `虛線為台指的門檻；美國 VIX 門檻較低 (恐慌 ${VIX_PANIC.US})，只畫線供對照。${since}`
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
                color: point.market === "TW" ? c.text : c.secondary,
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
                    // 下方的數值可能和線條、門檻虛線交疊，加淺色底才讀得到
                    ...(lower ? { backgroundColor: `${c.surface}e6`, padding: [1, 3], borderRadius: 3 } : {}),
                    formatter: lower ? mark.lower!.text : labels[index],
                },
            }
        }),
        symbol: "triangle",
        symbolSize: [11, 9],
        tooltip: { show: false },
        z: 5,
    })

    /**
     * 分區的呈現方式：背景維持乾淨，和上方指數圖同樣是白底加線條；
     * 主線依所在分區分段上色 (見 option 的 visualMap)，門檻只畫淡色虛線並標上分區名稱。
     * 維持率與 VIX 共用
     */
    type Zone = { from: number; to: number; label: string; tone: string }
    const zoneColors: Record<string, string> = {
        // 深紅畫成線太暗，調亮一點，仍比偏低、警戒的紅色深
        "strong-sell": "#cc1f36",
        sell: c.zoneSell,
        // 中立的淺灰畫成線太淡，也會和民間版的灰線混在一起，線條改用主要文字色
        neutral: c.text,
        buy: c.zoneBuy,
        "strong-buy": c.zoneStrongBuy,
    }
    /** visualMap 的分段，線落在哪一區就用那一區的顏色 */
    const zonePieces = (zones: readonly Zone[]) =>
        zones.map((zone) => ({
            gte: zone.from,
            ...(Number.isFinite(zone.to) ? { lt: zone.to } : {}),
            color: zoneColors[zone.tone],
        }))
    /** 各分區下緣的門檻虛線，分區名稱放在圖的右側外面，不會壓到線條與最新資料 */
    const zoneLines = (zones: readonly Zone[]) => ({
        silent: true,
        symbol: "none",
        data: zones.slice(1).map((zone) => ({
            yAxis: zone.from,
            lineStyle: { type: "dashed", width: 1, color: `${zoneColors[zone.tone]}80` },
            label: {
                formatter: zone.label,
                position: "end",
                distance: 4,
                color: zoneColors[zone.tone],
                fontSize: 11,
            },
        })),
    })
    const vixLine = (name: string, source: Map<string, number>, color: string, extra: object) => ({
        name,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: data.map((row) => source.get(row.date) ?? "-"),
        symbol: "none",
        connectNulls: true,
        lineStyle: { width: 1.8, color },
        itemStyle: { color },
        ...extra,
    })

    const metricSeries = isVix
        ? [
            // 台指 VIX 依分區分段上色並畫門檻線；美國 VIX 門檻較低，畫成灰色細線只供對照
            vixLine("台指 VIX", twVix.value, c.text, { markLine: zoneLines(VIX_ZONES.TW), lineStyle: { width: 2.6 } }),
            // 對照線用綠色，和分區的紅、黑、藍都不同色
            vixLine("美國 VIX", usVix.value, c.dealer, { lineStyle: { width: 1.8, color: c.dealer } }),
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
                // 維持率頁籤的民間版是對照線，用綠色，和官方線分區的紅、黑、藍都不同色
                lineStyle: { width: 1.8, color: isMaintenance ? c.dealer : c.text },
                itemStyle: { color: isMaintenance ? c.dealer : c.text },
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
                    // 依分區分段上色 (visualMap)，門檻畫淡色虛線
                    lineStyle: { width: 2.6 },
                    markLine: zoneLines(OFFICIAL_ZONES),
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

    /**
     * 依分區分段上色的主線 (台指 VIX、官方維持率)。series 依序為指數線、各均線、
     * 指數上的標記，接著才是 metricSeries，因此索引要加上前面的數量
     */
    const zonedIndex = metricSeries.findIndex((item) => item.name === "台指 VIX" || item.name === "官方全市場維持率")
    // 有分區門檻時右側多留空間放分區名稱，上下兩張圖一起調整，x 軸才會對齊
    const gridRight = zonedIndex < 0 ? 20 : 58
    const visualMap = zonedIndex < 0
        ? []
        : [{
            show: false,
            type: "piecewise",
            seriesIndex: 1 + MA_SIZES.length + 1 + zonedIndex,
            pieces: zonePieces(isVix ? VIX_ZONES.TW : OFFICIAL_ZONES),
        }]

    return {
        animation: false,
        visualMap,
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
                    MA_SIZES.map((size, index) => `MA${size} ${fmt(maByDate.value[index].get(row.date), 0)}`).join("　"),
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
        // 均線圖例放在指數圖右上角，和左邊的指數標題同一列
        legend: {
            data: MA_SIZES.map((size) => `MA${size}`),
            top: 0,
            right: gridRight,
            icon: "roundRect",
            itemWidth: 10,
            itemHeight: 10,
            itemGap: 14,
            textStyle: { color: c.secondary, fontSize: 12 },
        },
        title: [
            {
                text: indexName.value,
                left: 64,
                top: 0,
                textStyle: { color: c.foreign, fontSize: 13, fontWeight: 600 },
            },
            {
                text: isVix
                    ? "恐慌指標 VIX（彩色：台指依分區上色、綠：美國）"
                    : isMaintenance
                    ? `${MARKET_LABELS[marketKey.value]}融資維持率（彩色：官方全市場依分區上色、綠：民間版）`
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
            { left: 64, right: gridRight, top: 40, height: 196 },
            {
                left: 64,
                right: gridRight,
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
                // 縱軸只依線的資料決定範圍，對齊整數刻度
                ...(isVix
                    ? {
                        min: (range: { min: number }) => Math.max(0, Math.floor((range.min - 2) / 5) * 5),
                        max: (range: { max: number }) => Math.ceil((range.max + 2) / 5) * 5,
                    }
                    : {}),
                ...(isMaintenance
                    ? {
                        min: (range: { min: number }) => Math.floor((range.min - 5) / 20) * 20,
                        max: (range: { max: number }) => Math.ceil((range.max + 5) / 20) * 20,
                        // 刻度固定每 20% 一格，150、180、200 等分區界線附近才好對照
                        interval: 20,
                    }
                    : {}),
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                // 有分區門檻虛線時不畫格線，避免兩種虛線混在一起
                splitLine: { show: !(isMaintenance || isVix), lineStyle: { color: c.border, type: "dashed" } },
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
            // 均線避開指數線的藍色與標記的橘色：MA5 紅、MA20 綠、MA60 灰色虛線
            ...MA_SIZES.map((size, index) => ({
                name: `MA${size}`,
                type: "line",
                data: data.map((row) => maByDate.value[index].get(row.date) ?? "-"),
                symbol: "none",
                smooth: true,
                connectNulls: true,
                lineStyle: {
                    width: 1.2,
                    color: [c.buy, c.dealer, c.secondary][index],
                    type: index === 2 ? "dashed" : "solid",
                },
                itemStyle: { color: [c.buy, c.dealer, c.secondary][index] },
                z: 3,
            })),
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
