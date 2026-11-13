<script setup lang="ts">
/**
 * 題材輪動熱力圖：橫軸是週，縱軸是題材，格子是該題材個股千張大戶比例的平均變化。
 *
 * 紅色代表大戶在收、綠色代表大戶在賣，顏色越深變化越大。
 * period 跟著頁面上方的比較期間：1 週畫單週變化，4 週、12 週畫「到這週為止」的累計。
 * 單週格子常常一紅一綠，累計後色塊才會連成一片，輪動比較看得出來。
 * 色階分段而非連續，期間越長門檻越寬，變化不明顯的畫成底色。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import type { HoldersAnalysis } from "@/types"
import { formatDate, signed } from "@/utils/format"
import { baseTooltip, buyColor, colors, sellColor } from "@/utils/theme"

const props = withDefaults(defineProps<{
    heatmap: HoldersAnalysis["heatmap"]
    /** 累計的週數，1 為單週 */
    period?: number
}>(), { period: 1 })

/** 各期間色階的三個分界 (百分點)：不明顯、中等、明顯 */
const STEPS: Record<number, [number, number, number]> = {
    1: [0.2, 0.5, 1],
    4: [0.5, 1, 2],
    12: [1, 2, 4],
}

/**
 * 每格的數值：k 週內單週平均變化的合計，約等於這段期間千張大戶比例的平均變化。
 * 這 k 週要每週都有資料才計算，否則畫成無資料，避免缺週造成的偏差。
 */
function rolling(values: (number | null)[], k: number): (number | null)[] {
    if (k <= 1) {
        return values
    }
    return values.map((_, i) => {
        if (i < k - 1) {
            return null
        }
        const window = values.slice(i - k + 1, i + 1)
        if (window.some((v) => v === null)) {
            return null
        }
        return +(window as number[]).reduce((sum, v) => sum + v, 0).toFixed(2)
    })
}

const emit = defineEmits<{ select: [date: string] }>()

/** #rrggbb 依比例混入底色，產生同一色系的深淺 */
function mix(color: string, base: string, ratio: number): string {
    const parse = (hex: string) => {
        const value = hex.replace("#", "")
        const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value
        return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
    }
    const a = parse(color)
    const b = parse(base)
    const rgb = a.map((v, i) => Math.round(v * ratio + b[i] * (1 - ratio)))
    return `rgb(${rgb.join(",")})`
}

const ROW_HEIGHT = 22

const height = computed(() => `${props.heatmap.themes.length * ROW_HEIGHT + 90}px`)

const option = computed(() => {
    const c = colors()
    const weeks = props.heatmap.weeks
    // 由上而下依題材設定的順序，category 軸由下往上排，所以反轉
    const themes = props.heatmap.themes.slice().reverse()
    const k = props.period
    const data: [number, number, number | string][] = []
    themes.forEach((theme, y) => {
        rolling(theme.values, k).forEach((value, x) => {
            data.push([x, y, value === null ? "-" : value])
        })
    })
    const buy = buyColor()
    const sell = sellColor()
    const base = c.surface || "#ffffff"
    const [low, mid, high] = STEPS[k] ?? STEPS[1]
    const span = k === 1 ? "單週" : `${k} 週合計`

    return {
        grid: { left: 150, right: 16, top: 8, bottom: 64 },
        tooltip: {
            ...baseTooltip(),
            formatter: (params: any) => {
                const [x, y, value] = params.data
                const theme = themes[y]
                if (value === "-") {
                    const reason = k > 1 && x < k - 1 ? `往前不足 ${k} 週` : "無資料"
                    return `<strong>${theme.name}</strong><br>${formatDate(weeks[x])}　${reason}`
                }
                return [
                    `<strong>${theme.name}</strong>`,
                    k === 1
                        ? `${formatDate(weeks[x])}　千張大戶平均 ${signed(value as number)} 百分點`
                        : `${formatDate(weeks[x - k + 1])} ~ ${formatDate(weeks[x])}`,
                    ...(k === 1 ? [] : [`千張大戶平均 ${signed(value as number)} 百分點 (${span})`]),
                    `${theme.counts[x]} 檔平均`,
                ].join("<br>")
            },
        },
        xAxis: {
            type: "category",
            data: weeks.map((d) => formatDate(d).slice(2).replace(/-/g, "/")),
            splitArea: { show: false },
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 10, interval: 3, rotate: 0 },
        },
        yAxis: {
            type: "category",
            data: themes.map((t) => t.name),
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 12 },
        },
        visualMap: {
            type: "piecewise",
            orient: "horizontal",
            left: "center",
            bottom: 0,
            itemWidth: 14,
            itemHeight: 10,
            textStyle: { color: c.secondary, fontSize: 11 },
            pieces: [
                { lt: -high, label: `賣 ${high} 以上`, color: mix(sell, base, 1) },
                { gte: -high, lt: -mid, label: `賣 ${mid}~${high}`, color: mix(sell, base, 0.65) },
                { gte: -mid, lt: -low, label: `賣 ${low}~${mid}`, color: mix(sell, base, 0.3) },
                { gte: -low, lte: low, label: "不明顯", color: mix(c.muted, base, 0.12) },
                { gt: low, lte: mid, label: `收 ${low}~${mid}`, color: mix(buy, base, 0.3) },
                { gt: mid, lte: high, label: `收 ${mid}~${high}`, color: mix(buy, base, 0.65) },
                { gt: high, label: `收 ${high} 以上`, color: mix(buy, base, 1) },
            ],
        },
        series: [
            {
                type: "heatmap",
                data,
                cursor: "pointer",
                itemStyle: { borderColor: base, borderWidth: 1 },
                emphasis: { itemStyle: { borderColor: c.text, borderWidth: 1 } },
            },
        ],
    }
})

function onClick(params: any) {
    const x = params.data?.[0]
    if (typeof x === "number") {
        emit("select", props.heatmap.weeks[x])
    }
}
</script>

<template>
    <div class="heatmap-scroll">
        <VChart class="heatmap" :style="{ height }" :option="option" autoresize @click="onClick" />
    </div>
</template>

<style scoped>
/* 51 週擠在手機寬度看不清楚，窄螢幕時改為橫向捲動 */
.heatmap-scroll {
    overflow-x: auto;
}

.heatmap {
    min-width: 760px;
    width: 100%;
}
</style>
