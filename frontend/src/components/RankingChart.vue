<script setup lang="ts">
/**
 * 通用橫向排行圖：由上而下為第一名到最後一名，於長條末端直接標示金額。
 * rows 需已由大到小排序，圖表高度隨筆數增加，超出時由外層容器捲動。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import { YI, toYi } from "@/utils/format"
import { baseTooltip, colors, polarityColor } from "@/utils/theme"

const props = defineProps<{
    rows: { amount: number }[]
    /** 軸上顯示的名稱，第二個參數是名次 */
    nameOf: (row: any, rank: number) => string
    tooltip: (row: any, rank: number) => string
    digits?: number
    /** 左側名稱欄的寬度 */
    labelWidth?: number
}>()

const emit = defineEmits<{ select: [row: any] }>()

const height = computed(() => `${Math.max(360, props.rows.length * 22 + 60)}px`)

const option = computed(() => {
    const c = colors()
    const total = props.rows.length
    // ECharts 的類別軸由下往上排，因此反轉後最大值會落在最上方
    const ordered = props.rows.slice().reverse()

    return {
        grid: { left: props.labelWidth ?? 110, right: 80, top: 10, bottom: 34 },
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                const row = params.data?.detail
                return row ? props.tooltip(row, params.data.rank) : ""
            },
        },
        xAxis: {
            type: "value",
            name: "億元",
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        yAxis: {
            type: "category",
            data: ordered.map((row, index) => props.nameOf(row, total - index)),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 12 },
        },
        series: [
            {
                type: "bar",
                barWidth: 14,
                barMaxWidth: 14,
                data: ordered.map((row, index) => {
                    const positive = row.amount >= 0
                    return {
                        value: row.amount / YI,
                        detail: row,
                        rank: total - index,
                        itemStyle: {
                            color: polarityColor(row.amount),
                            // 圓角只加在資料端，基準線端保持平整
                            borderRadius: positive ? [0, 4, 4, 0] : [4, 0, 0, 4],
                        },
                        label: { position: positive ? "right" : "left" },
                    }
                }),
                label: {
                    show: true,
                    formatter: (params: any) => toYi(params.data.detail.amount, props.digits),
                    color: c.secondary,
                    fontSize: 12,
                },
            },
        ],
    }
})

function onClick(params: any) {
    if (params.data?.detail) {
        emit("select", params.data.detail)
    }
}
</script>

<template>
    <div class="chart-scroll">
        <VChart
            class="chart"
            :style="{ height }"
            :option="option"
            autoresize
            @click="onClick"
        />
    </div>
</template>
