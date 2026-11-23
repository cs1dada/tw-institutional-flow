<script setup lang="ts">
/**
 * 對資產的影響：由上而下為情境色帶、各資產漲跌、美元指數漲跌、10Y-2Y 利差，共用時間軸。
 *
 * - 美股、台股、比特幣、黃金價位差很多 (黃金幾千、比特幣幾萬)，都換算成「從區間起點算漲跌幾 %」
 *   才能放在同一個 Y 軸上比較；線尾直接標出名稱與漲跌幅，不必對照圖例。
 * - 美元指數也換算成漲跌幅，和資產用同一種算法，方便對照；它的幅度小很多，另外一格。
 * - 利差單位不同，另外一格，不使用雙 Y 軸。
 * - 情境 (象限) 用最上方一條細色帶呈現，不鋪在資產線後面：
 *   資產線和情境用的是同一組色相，疊在一起容易看混；美元與利差那兩格則鋪淡色底。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import { formatDate } from "@/utils/format"
import { ASSETS, REGIMES, type LiquidityPoint, type RegimeSpan } from "@/utils/liquidity"
import { baseTooltip, colors } from "@/utils/theme"

const props = defineProps<{
    /** 已依選定區間切好的資料點 */
    points: LiquidityPoint[]
    /** 全部期間的情境區段，畫圖時只取落在區間內的部分 */
    spans: RegimeSpan[]
}>()

const REGIME_BY_ID = Object.fromEntries(REGIMES.map((r) => [r.id, r]))
const SPREAD_COLOR = "#5b5fa8"

function signed(value: number, digits = 1): string {
    const text = value.toFixed(digits)
    return value > 0 ? `+${text}` : text
}

/** 以區間內第一個有值的日子為基準，換算成漲跌幅 (%) */
function toChange(values: (number | null)[]): (number | null)[] {
    const base = values.find((v) => v != null) ?? null
    return values.map((v) => (base == null || v == null ? null : +(((v - base) / base) * 100).toFixed(2)))
}

const changes = computed(() =>
    Object.fromEntries(ASSETS.map((a) => [a.id, toChange(props.points.map((p) => p.assets[a.id]))])),
)
const dxyChange = computed(() => toChange(props.points.map((p) => p.dxy)))

/** 落在目前區間內的情境區段，起訖日裁切到區間範圍 */
const visibleSpans = computed(() => {
    const first = props.points[0]?.date
    const last = props.points[props.points.length - 1]?.date
    if (!first || !last) {
        return []
    }
    return props.spans
        .filter((s) => s.end >= first && s.start <= last)
        .map((s) => ({ ...s, start: s.start < first ? first : s.start, end: s.end > last ? last : s.end }))
})

const option = computed(() => {
    const c = colors()
    const points = props.points
    const labels = points.map((p) => formatDate(p.date))

    function bands(opacity: number) {
        return visibleSpans.value.map((span) => [
            { xAxis: formatDate(span.start), itemStyle: { color: REGIME_BY_ID[span.id].color, opacity } },
            { xAxis: formatDate(span.end) },
        ])
    }

    const side = { left: 56, right: 92 }
    const grids = [
        // 0：情境色帶
        { ...side, top: 26, height: 10 },
        // 1：各資產漲跌
        { ...side, top: 44, height: "50%" },
        // 2：美元指數漲跌
        { ...side, top: "66%", height: "10%" },
        // 3：利差
        { ...side, top: "83%", height: "9%" },
    ]
    const titles = [
        // 色帶的說明在頁面上的圖例，這裡不另外標，避免窄螢幕和標題重疊
        { text: "各資產漲跌 (%，從區間起點算)", top: 4, left: 56 },
        { text: "美元指數 (%，從區間起點算)", top: "62%", left: 56 },
        { text: "10Y-2Y 利差 (bp)", top: "79%", left: 56 },
    ]

    function lineSeries(name: string, index: number, color: string, data: (number | null)[]) {
        return {
            name,
            type: "line",
            xAxisIndex: index,
            yAxisIndex: index,
            symbol: "none",
            lineStyle: { width: 2, color },
            itemStyle: { color },
            data,
            connectNulls: true,
        }
    }

    function zeroLine(index: number) {
        return {
            name: `zero-${index}`,
            type: "line",
            xAxisIndex: index,
            yAxisIndex: index,
            data: [],
            silent: true,
            markLine: {
                silent: true,
                symbol: "none",
                lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.6 },
                label: { show: false },
                data: [{ yAxis: 0 }],
            },
        }
    }

    const percentLabel = (v: number) => `${v > 0 ? "+" : ""}${v}%`

    return {
        animation: false,
        title: titles.map((t) => ({
            text: t.text,
            left: t.left,
            top: t.top,
            textStyle: { color: c.secondary, fontSize: 12, fontWeight: 600 },
        })),
        grid: grids,
        xAxis: grids.map((_, i) => ({
            type: "category",
            gridIndex: i,
            data: labels,
            boundaryGap: false,
            axisLine: { show: i > 0, lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { show: i === grids.length - 1, color: c.muted, fontSize: 11 },
        })),
        yAxis: grids.map((_, i) => ({
            type: "value",
            gridIndex: i,
            show: i > 0,
            scale: i === 3,
            splitNumber: i === 1 ? 5 : 2,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11, formatter: i === 1 || i === 2 ? percentLabel : undefined },
            splitLine: { show: i > 0, lineStyle: { color: c.border, type: "dashed" } },
        })),
        axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: c.secondary } },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "line" },
            formatter: (params: any[]) => {
                const index = params.find((x) => x.dataIndex != null)?.dataIndex
                const p = points[index]
                if (!p) {
                    return ""
                }
                const lines = [`<strong>${formatDate(p.date)}</strong>`]
                const span = visibleSpans.value.find((s) => s.start <= p.date && p.date <= s.end)
                if (span) {
                    const regime = REGIME_BY_ID[span.id]
                    lines.push(
                        `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;`
                        + `background:${regime.color};margin-right:6px"></span>${regime.label}`,
                    )
                }
                // 依當天漲跌幅由高到低排列，方便看出誰領先
                const rows = ASSETS
                    .map((a) => ({ asset: a, value: changes.value[a.id][index] }))
                    .filter((r): r is { asset: (typeof ASSETS)[number]; value: number } => r.value != null)
                    .sort((a, b) => b.value - a.value)
                for (const { asset, value } of rows) {
                    lines.push(
                        `<span style="display:inline-block;width:10px;height:3px;background:${asset.color};`
                        + `vertical-align:middle;margin-right:6px"></span>${asset.label}　${signed(value)}%`,
                    )
                }
                const dxy = dxyChange.value[index]
                if (dxy != null) {
                    lines.push(`美元指數　${signed(dxy)}%`)
                }
                lines.push(`利差　${signed(p.spread * 100, 0)} bp`)
                return lines.join("<br>")
            },
        },
        series: [
            // 情境色帶：沒有資料的序列只用來承載 markArea
            {
                name: "情境",
                type: "line",
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [],
                silent: true,
                markArea: { silent: true, data: bands(0.8) },
            },
            ...ASSETS.map((asset) => ({
                ...lineSeries(asset.label, 1, asset.color, changes.value[asset.id]),
                // 線尾直接標名稱與最新漲跌幅
                endLabel: {
                    show: true,
                    color: c.text,
                    fontSize: 12,
                    formatter: (p: { value: number | null }) =>
                        p.value == null ? asset.short : `${asset.short} ${signed(p.value)}%`,
                },
                labelLayout: { moveOverlap: "shiftY" },
                emphasis: { focus: "series" },
            })),
            zeroLine(1),
            {
                ...lineSeries("美元指數", 2, c.text, dxyChange.value),
                markArea: { silent: true, data: bands(0.14) },
                endLabel: {
                    show: true,
                    color: c.text,
                    fontSize: 12,
                    formatter: (p: { value: number | null }) => (p.value == null ? "" : `${signed(p.value)}%`),
                },
            },
            zeroLine(2),
            {
                ...lineSeries("10Y-2Y 利差", 3, SPREAD_COLOR, points.map((p) => Math.round(p.spread * 100))),
                markArea: { silent: true, data: bands(0.14) },
                endLabel: {
                    show: true,
                    color: c.text,
                    fontSize: 12,
                    formatter: (p: { value: number | null }) => (p.value == null ? "" : `${p.value} bp`),
                },
            },
        ],
    }
})
</script>

<template>
    <VChart class="asset-chart" :option="option" autoresize />
</template>

<style scoped>
.asset-chart {
    width: 100%;
    height: 640px;
}
</style>
