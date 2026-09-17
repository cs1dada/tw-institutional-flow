<script setup lang="ts">
/**
 * 共用的橫向長條圖，用於 ETF 買賣超與合計持股。
 *
 * 與 RankingChart 的差別：這裡不標名次，數值由 valueOf 決定
 * (可能是金額或市值)，顏色也允許外部指定。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import { baseTooltip, colors, polarityColor } from "@/utils/theme"

const props = defineProps<{
    rows: any[]
    nameOf: (row: any) => string
    /** 長條的數值，單位由 unit 標示 */
    valueOf: (row: any) => number
    tooltip: (row: any) => string
    colorOf?: ((row: any) => string) | null
    labelWidth?: number
    unit?: string
}>()

const height = computed(() => `${Math.max(320, props.rows.length * 22 + 60)}px`)

const option = computed(() => {
    const c = colors()
    const ordered = props.rows.slice().reverse()

    return {
        grid: { left: props.labelWidth ?? 150, right: 80, top: 10, bottom: 34 },
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                const row = params.data?.detail
                return row ? props.tooltip(row) : ""
            },
        },
        xAxis: {
            type: "value",
            name: props.unit ?? "億元",
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        yAxis: {
            type: "category",
            data: ordered.map(props.nameOf),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 12 },
        },
        series: [
            {
                type: "bar",
                barWidth: 14,
                barMaxWidth: 14,
                data: ordered.map((row) => {
                    const value = props.valueOf(row)
                    const positive = value >= 0
                    return {
                        value,
                        detail: row,
                        itemStyle: {
                            color: props.colorOf ? props.colorOf(row) : polarityColor(value),
                            borderRadius: positive ? [0, 4, 4, 0] : [4, 0, 0, 4],
                        },
                        label: { position: positive ? "right" : "left" },
                    }
                }),
                label: {
                    show: true,
                    formatter: (params: any) => {
                        const value = params.data.value as number
                        return (value > 0 ? "+" : "") + value.toFixed(2)
                    },
                    color: c.secondary,
                    fontSize: 12,
                },
            },
        ],
    }
})
</script>

<template>
    <VChart class="chart" :style="{ height }" :option="option" autoresize />
</template>
