<script setup lang="ts">
/** 單一類股近 N 個交易日的三法人資金流向 */
import { computed } from "vue"
import VChart from "vue-echarts"

import type { HistoryPoint } from "@/types"
import { YI, formatDate } from "@/utils/format"
import { baseTooltip, colors } from "@/utils/theme"

const props = defineProps<{
    industry: string
    items: HistoryPoint[]
}>()

const option = computed(() => {
    const c = colors()
    const items = props.items
    const dates = items.map((row) => formatDate(row.date).slice(5))

    function series(name: string, key: keyof HistoryPoint, color: string) {
        return {
            name,
            type: "line",
            smooth: false,
            symbol: "circle",
            symbolSize: 8,
            showSymbol: items.length <= 30,
            lineStyle: { width: 2, color },
            itemStyle: { color, borderColor: c.surface, borderWidth: 2 },
            data: items.map((row) => +((row[key] as number) / YI).toFixed(2)),
        }
    }

    const zeroLine = {
        silent: true,
        symbol: "none",
        lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.7 },
        data: [{ yAxis: 0 }],
        label: { show: false },
    }

    return {
        grid: { left: 56, right: 20, top: 40, bottom: 34 },
        legend: {
            data: ["外資", "投信", "自營商"],
            top: 0,
            icon: "roundRect",
            itemWidth: 10,
            itemHeight: 10,
            itemGap: 18,
            textStyle: { color: c.secondary, fontSize: 12 },
        },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "cross", label: { backgroundColor: c.secondary } },
            formatter: (params: any[]) => {
                const lines = [`<strong>${props.industry}　${params[0].axisValue}</strong>`]
                for (const item of params) {
                    const value = item.data > 0 ? `+${item.data.toFixed(1)}` : item.data.toFixed(1)
                    lines.push(`${item.marker}${item.seriesName}　${value} 億`)
                }
                return lines.join("<br>")
            },
        },
        xAxis: {
            type: "category",
            data: dates,
            boundaryGap: false,
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
        },
        yAxis: {
            type: "value",
            name: "億元",
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        series: [
            { ...series("外資", "foreign_amt", c.foreign), markLine: zeroLine },
            series("投信", "trust_amt", c.trust),
            series("自營商", "dealer_amt", c.dealer),
        ],
    }
})
</script>

<template>
    <VChart class="chart" :option="option" autoresize />
</template>
