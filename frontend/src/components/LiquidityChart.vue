<script setup lang="ts">
/**
 * 流動性觀察走勢圖：美元指數、美債 2Y／10Y 殖利率、10Y-2Y 利差三格上下排列，共用時間軸。
 *
 * 三者單位不同，各自一格、各自的 Y 軸 (不使用雙 Y 軸)。
 * 美元指數那一格的底色是每天以同樣回看天數判讀出的情境，看得出情境如何輪替；
 * 虛線標出目前判讀所比較的起點。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import { formatDate } from "@/utils/format"
import { REGIMES, type LiquidityPoint, type RegimeSpan } from "@/utils/liquidity"
import { baseTooltip, colors } from "@/utils/theme"

const props = defineProps<{
    points: LiquidityPoint[]
    spans: RegimeSpan[]
    /** 目前判讀的比較起點 (YYYYMMDD) */
    fromDate: string | null
}>()

const REGIME_BY_ID = Object.fromEntries(REGIMES.map((r) => [r.id, r]))
/** 預設顯示最近約一年，其餘可拖動下方縮放條查看 */
const DEFAULT_VISIBLE = 250

function signed(value: number, digits: number): string {
    const text = value.toFixed(digits)
    return value > 0 ? `+${text}` : text
}

const option = computed(() => {
    const c = colors()
    const points = props.points
    const dates = points.map((p) => p.date)
    const labels = dates.map((d) => formatDate(d))
    const startPct = points.length > DEFAULT_VISIBLE ? (1 - DEFAULT_VISIBLE / points.length) * 100 : 0

    const grids = [
        { left: 56, right: 24, top: 36, height: "22%" },
        { left: 56, right: 24, top: "38%", height: "22%" },
        { left: 56, right: 24, top: "70%", height: "16%" },
    ]
    const titles = ["美元指數 (DXY)", "美債殖利率 (%)", "10Y-2Y 利差 (百分點)"]

    const xAxes = grids.map((_, i) => ({
        type: "category",
        gridIndex: i,
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
        axisLabel: { show: i === grids.length - 1, color: c.muted, fontSize: 11 },
    }))
    const yAxes = grids.map((_, i) => ({
        type: "value",
        gridIndex: i,
        scale: true,
        splitNumber: 3,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: c.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
    }))

    function line(name: string, index: number, color: string, values: number[]) {
        return {
            name,
            type: "line",
            xAxisIndex: index,
            yAxisIndex: index,
            symbol: "none",
            lineStyle: { width: 2, color },
            itemStyle: { color },
            data: values,
        }
    }

    // 情境底色：同一情境的連續日子合併成一段
    const bands = props.spans.map((span) => {
        const regime = REGIME_BY_ID[span.id]
        return [
            { xAxis: formatDate(span.start), itemStyle: { color: regime.color, opacity: 0.14 } },
            { xAxis: formatDate(span.end) },
        ]
    })
    const fromLine = props.fromDate
        ? {
            silent: true,
            symbol: "none",
            lineStyle: { color: c.secondary, type: "dashed", width: 1 },
            label: { formatter: "比較起點", color: c.secondary, fontSize: 11 },
            data: [{ xAxis: formatDate(props.fromDate) }],
        }
        : undefined

    const dxyColor = c.text
    const us2yColor = c.trust
    const us10yColor = c.foreign
    const spreadColor = "#5b5fa8"

    return {
        animation: false,
        title: titles.map((text, i) => ({
            text,
            left: 56,
            top: i === 0 ? 4 : `${[0, 34, 66][i]}%`,
            textStyle: { color: c.secondary, fontSize: 12, fontWeight: 600 },
        })),
        legend: {
            data: ["2Y", "10Y"],
            top: "34%",
            right: 24,
            icon: "roundRect",
            itemWidth: 10,
            itemHeight: 10,
            textStyle: { color: c.secondary, fontSize: 12 },
        },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: c.secondary } },
        dataZoom: [
            { type: "inside", xAxisIndex: [0, 1, 2], start: startPct, end: 100 },
            {
                type: "slider",
                xAxisIndex: [0, 1, 2],
                start: startPct,
                end: 100,
                bottom: 8,
                height: 20,
                borderColor: c.border,
                textStyle: { color: c.muted, fontSize: 11 },
            },
        ],
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "line" },
            formatter: (params: any[]) => {
                const index = params[0]?.dataIndex
                const p = points[index]
                if (!p) {
                    return ""
                }
                const span = props.spans.find((s) => s.start <= p.date && p.date <= s.end)
                const regime = span ? REGIME_BY_ID[span.id] : null
                const lines = [`<strong>${formatDate(p.date)}</strong>`]
                if (regime) {
                    lines.push(
                        `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;`
                        + `background:${regime.color};margin-right:6px"></span>${regime.label}`,
                    )
                }
                lines.push(`美元指數　${p.dxy.toFixed(2)}`)
                lines.push(`2Y　${p.us2y.toFixed(2)}%　10Y　${p.us10y.toFixed(2)}%`)
                lines.push(`利差　${signed(p.spread * 100, 0)} bp${p.spread < 0 ? " (倒掛)" : ""}`)
                return lines.join("<br>")
            },
        },
        series: [
            {
                ...line("美元指數", 0, dxyColor, points.map((p) => p.dxy)),
                markArea: { silent: true, data: bands },
                markLine: fromLine,
            },
            {
                ...line("2Y", 1, us2yColor, points.map((p) => p.us2y)),
                // 文字只在美元那格顯示一次，這裡會和圖例重疊
                markLine: fromLine && { ...fromLine, label: { show: false } },
            },
            line("10Y", 1, us10yColor, points.map((p) => p.us10y)),
            {
                ...line("10Y-2Y 利差", 2, spreadColor, points.map((p) => p.spread)),
                markLine: {
                    silent: true,
                    symbol: "none",
                    lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.7 },
                    label: { formatter: "0 (以下為倒掛)", color: c.muted, fontSize: 11, position: "insideStartTop" },
                    data: [{ yAxis: 0 }],
                },
            },
        ],
    }
})
</script>

<template>
    <VChart class="liquidity-chart" :option="option" autoresize />
</template>

<style scoped>
.liquidity-chart {
    width: 100%;
    height: 620px;
}
</style>
