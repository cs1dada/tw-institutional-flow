<script setup lang="ts">
/**
 * 個股逐週籌碼走勢。
 *
 * 「價格與大戶」：收盤價 (左軸) 對照千張大戶比例或股東人數 (右軸)，看價格和籌碼有沒有背離。
 * 「持股結構」：千張大戶、中間級距、50 張以下三塊堆疊成 100%，看股票在誰手上。
 */
import { computed, ref } from "vue"
import VChart from "vue-echarts"

import type { HoldersStock } from "@/types"
import { formatDate } from "@/utils/format"
import { baseTooltip, colors } from "@/utils/theme"

type Mode = "big" | "holders" | "structure"

const props = defineProps<{
    series: HoldersStock["series"]
}>()

const MODE_LABELS: Record<Mode, string> = {
    big: "股價與千張大戶",
    holders: "股價與股東人數",
    structure: "持股結構",
}

const mode = ref<Mode>("big")

const option = computed(() => {
    const c = colors()
    const items = props.series
    const dates = items.map((s) => formatDate(s.date).slice(5))
    const axisBase = {
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: c.muted, fontSize: 11 },
        nameTextStyle: { color: c.muted, fontSize: 11 },
    }
    const xAxis = {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
        axisLabel: { color: c.muted, fontSize: 11 },
    }
    const legend = {
        top: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 16,
        textStyle: { color: c.secondary, fontSize: 12 },
    }
    const line = (color: string) => ({
        type: "line",
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { width: 2, color },
        itemStyle: { color, borderColor: c.surface, borderWidth: 1.5 },
    })

    if (mode.value === "structure") {
        const area = (name: string, color: string, values: number[]) => ({
            ...line(color),
            name,
            stack: "share",
            areaStyle: { color, opacity: 0.35 },
            data: values.map((v) => +v.toFixed(2)),
        })
        return {
            grid: { left: 48, right: 20, top: 34, bottom: 28 },
            legend,
            tooltip: {
                ...baseTooltip(),
                trigger: "axis",
                valueFormatter: (v: number) => `${v.toFixed(2)}%`,
            },
            xAxis,
            yAxis: {
                ...axisBase,
                type: "value",
                min: 0,
                max: 100,
                name: "%",
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
            series: [
                area("50 張以下", c.trust, items.map((s) => s.small_pct)),
                area("50-1000 張", c.muted, items.map((s) => Math.max(0, 100 - s.small_pct - s.big_pct))),
                area("千張大戶", c.foreign, items.map((s) => s.big_pct)),
            ],
        }
    }

    const isBig = mode.value === "big"
    const rightName = isBig ? "千張大戶比例" : "股東人數"
    return {
        grid: { left: 56, right: 64, top: 34, bottom: 28 },
        legend,
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            formatter: (params: any[]) => {
                const lines = [`<strong>${params[0].axisValue}</strong>`]
                for (const p of params) {
                    if (p.value === null || p.value === undefined) {
                        continue
                    }
                    const text = p.seriesName === "千張大戶比例"
                        ? `${p.value.toFixed(2)}%`
                        : p.seriesName === "股東人數"
                            ? `${p.value.toLocaleString()} 人`
                            : `${p.value}`
                    lines.push(`${p.marker}${p.seriesName}　${text}`)
                }
                return lines.join("<br>")
            },
        },
        xAxis,
        yAxis: [
            {
                ...axisBase,
                type: "value",
                name: "收盤",
                scale: true,
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
            {
                ...axisBase,
                type: "value",
                name: isBig ? "%" : "人",
                scale: true,
                splitLine: { show: false },
                axisLabel: {
                    color: c.muted,
                    fontSize: 11,
                    formatter: (v: number) => (isBig ? v.toFixed(1) : v >= 10000 ? `${(v / 10000).toFixed(1)}萬` : `${v}`),
                },
            },
        ],
        series: [
            { ...line(c.secondary), name: "收盤", yAxisIndex: 0, data: items.map((s) => s.close) },
            {
                ...line(isBig ? c.foreign : c.trust),
                name: rightName,
                yAxisIndex: 1,
                data: items.map((s) => (isBig ? s.big_pct : s.holders)),
            },
        ],
    }
})
</script>

<template>
    <div>
        <div class="trend-modes">
            <button
                v-for="(label, key) in MODE_LABELS"
                :key="key"
                type="button"
                class="chip"
                :class="{ 'is-active': mode === key }"
                @click="mode = key as Mode"
            >
                {{ label }}
            </button>
        </div>
        <VChart class="trend-chart" :option="option" autoresize />
    </div>
</template>

<style scoped>
.trend-modes {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 6px;
}

.trend-chart {
    width: 100%;
    height: 280px;
}
</style>
