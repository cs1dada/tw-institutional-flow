<script setup lang="ts">
/**
 * 流動性觀察走勢圖：美元指數、美元兌台幣、台幣偏離、美債 2Y／10Y 殖利率、10Y-2Y 利差五格上下排列，共用時間軸。
 *
 * 各格單位不同，各自一格、各自的 Y 軸 (不使用雙 Y 軸)。
 * 美元指數那一格的底色是每天以同樣回看天數判讀出的情境，看得出情境如何輪替；
 * 美元兌台幣緊貼在美元指數下方，方便比對全球美元強弱是否反映到台幣；
 * 台幣偏離把「美元指數推算不出來的台幣漲跌」單獨畫出，正值 (台幣偏弱) 與負值 (台幣偏強) 分色；
 * 淡色區塊標出目前判讀所比較的區間 (比較起點到最新一天)。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import { formatDate } from "@/utils/format"
import { REGIMES, type LiquidityPoint, type RegimeSpan } from "@/utils/liquidity"
import { baseTooltip, colors } from "@/utils/theme"

const props = defineProps<{
    points: LiquidityPoint[]
    spans: RegimeSpan[]
    /** 目前判讀的比較起點 (YYYYMMDD)，從這天到最新一天會標成「判讀區間」 */
    fromDate: string | null
    /** 台幣偏離 (百分點)，與 points 對齊 */
    twdGap: (number | null)[]
    /** 目前的回看期間名稱，例如「近 1 個月」 */
    periodLabel: string
}>()

/** 台幣偏弱 / 偏強的顏色，沿用情境色的緊縮紅與釋放藍 */
const GAP_WEAK = "#b42335"
const GAP_STRONG = "#2a78d6"

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
        { left: 56, right: 24, top: 36, height: "14%" },
        { left: 56, right: 24, top: "24%", height: "11%" },
        { left: 56, right: 24, top: "41%", height: "10%" },
        { left: 56, right: 24, top: "57%", height: "13%" },
        { left: 56, right: 24, top: "76%", height: "13%" },
    ]
    const titles = [
        "美元指數 (DXY)",
        "美元兌新台幣 (數字越大，台幣越弱)",
        `台幣偏離 (%，${props.periodLabel}；正值為台幣比美元指數推算的弱)`,
        "美債殖利率 (%)",
        "10Y-2Y 利差 (百分點)",
    ]
    const titleTops = [4, "20.5%", "37.5%", "53.5%", "72.5%"]

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

    function line(name: string, index: number, color: string, values: (number | null)[]) {
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
    // 判讀區間：每一格各加一條沒有資料的輔助序列來畫 markArea，
    // 美元指數那格已經用 markArea 畫情境底色，不能再疊一層，所以另外用序列承載
    const lastDate = points[points.length - 1]?.date
    const windowSeries = props.fromDate && lastDate
        ? grids.map((_, i) => ({
            name: "判讀區間",
            type: "line",
            xAxisIndex: i,
            yAxisIndex: i,
            data: [],
            silent: true,
            tooltip: { show: false },
            markArea: {
                silent: true,
                // 美元指數那格有情境底色，只畫虛線外框，其他格用淡灰底
                itemStyle: i === 0
                    ? { color: "transparent", borderColor: c.secondary, borderWidth: 1, borderType: "dashed" }
                    : { color: c.muted, opacity: 0.1 },
                label: i === 0
                    ? { show: true, position: "insideTopRight", formatter: `判讀區間 (${props.periodLabel})`, color: c.secondary, fontSize: 11 }
                    : { show: false },
                data: [[{ xAxis: formatDate(props.fromDate!) }, { xAxis: formatDate(lastDate) }]],
            },
        }))
        : []

    const dxyColor = c.text
    const twdColor = "#5f6b7a"
    const us2yColor = c.trust
    const us10yColor = c.foreign
    const spreadColor = "#5b5fa8"

    return {
        animation: false,
        title: titles.map((text, i) => ({
            text,
            left: 56,
            top: titleTops[i],
            textStyle: { color: c.secondary, fontSize: 12, fontWeight: 600 },
        })),
        legend: {
            data: ["2Y", "10Y"],
            top: "53.5%",
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
            { type: "inside", xAxisIndex: [0, 1, 2, 3, 4], start: startPct, end: 100 },
            {
                type: "slider",
                xAxisIndex: [0, 1, 2, 3, 4],
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
                if (p.usdtwd != null) {
                    lines.push(`美元兌台幣　${p.usdtwd.toFixed(3)}`)
                }
                const gap = props.twdGap[index]
                if (gap != null) {
                    lines.push(`台幣偏離　${signed(gap, 2)}% (${gap >= 0 ? "偏弱" : "偏強"})`)
                }
                lines.push(`2Y　${p.us2y.toFixed(2)}%　10Y　${p.us10y.toFixed(2)}%`)
                lines.push(`利差　${signed(p.spread * 100, 0)} bp${p.spread < 0 ? " (倒掛)" : ""}`)
                return lines.join("<br>")
            },
        },
        series: [
            {
                ...line("美元指數", 0, dxyColor, points.map((p) => p.dxy)),
                markArea: { silent: true, data: bands },
            },
            line("美元兌台幣", 1, twdColor, points.map((p) => p.usdtwd)),
            // 台幣偏離依正負拆成兩條，正值 (偏弱) 紅、負值 (偏強) 藍，面積都從 0 起算
            {
                ...line("台幣偏弱", 2, GAP_WEAK, props.twdGap.map((v) => (v == null ? null : Math.max(v, 0)))),
                lineStyle: { width: 1, color: GAP_WEAK },
                areaStyle: { color: GAP_WEAK, opacity: 0.35 },
            },
            {
                ...line("台幣偏強", 2, GAP_STRONG, props.twdGap.map((v) => (v == null ? null : Math.min(v, 0)))),
                lineStyle: { width: 1, color: GAP_STRONG },
                areaStyle: { color: GAP_STRONG, opacity: 0.35 },
                markLine: {
                    silent: true,
                    symbol: "none",
                    lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.7 },
                    label: { show: false },
                    data: [{ yAxis: 0 }],
                },
            },
            line("2Y", 3, us2yColor, points.map((p) => p.us2y)),
            line("10Y", 3, us10yColor, points.map((p) => p.us10y)),
            {
                ...line("10Y-2Y 利差", 4, spreadColor, points.map((p) => p.spread)),
                markLine: {
                    silent: true,
                    symbol: "none",
                    lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.7 },
                    label: { formatter: "0 (以下為倒掛)", color: c.muted, fontSize: 11, position: "insideEndTop" },
                    data: [{ yAxis: 0 }],
                },
            },
            // 放在最後，不影響前面序列的索引與 tooltip 取值
            ...windowSeries,
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
    height: 900px;
}
</style>
