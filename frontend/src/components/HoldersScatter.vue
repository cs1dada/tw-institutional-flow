<script setup lang="ts">
/**
 * 籌碼分布散佈圖：一個點是一檔股票。
 *
 * X 軸是股東人數週變化 (%)，Y 軸是千張大戶比例週變化 (百分點)，
 * 門檻虛線把畫面切成四區，左上是「大戶收、散戶走」，右下是「大戶賣、散戶接」。
 * 點的顏色是股價週漲跌，點一下會通知外層展開該檔明細。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import type { HoldersRow } from "@/types"
import { signed, signedPct } from "@/utils/format"
import { baseTooltip, buyColor, colors, polarityColor, sellColor } from "@/utils/theme"

const props = defineProps<{
    rows: HoldersRow[]
    bigThreshold: number
    retailIn: number
    retailOut: number
}>()

const emit = defineEmits<{ select: [code: string] }>()

/** 少數極端值 (例如新上市股東人數翻倍) 會把其他點擠成一團，座標軸只涵蓋 2% 到 98% 的範圍 */
const CLIP_RATIO = 0.02

function quantile(sorted: number[], ratio: number): number {
    if (!sorted.length) {
        return 0
    }
    const index = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * ratio)))
    return sorted[index]
}

/** 依分位數與門檻決定座標軸範圍，門檻線一定落在畫面內 */
function extent(values: number[], low: number, high: number): [number, number] {
    const sorted = values.slice().sort((a, b) => a - b)
    const min = Math.min(quantile(sorted, CLIP_RATIO), low)
    const max = Math.max(quantile(sorted, 1 - CLIP_RATIO), high)
    const pad = (max - min) * 0.08 || 1
    return [+(min - pad).toFixed(2), +(max + pad).toFixed(2)]
}

const option = computed(() => {
    const c = colors()
    const rows = props.rows
    const [xMin, xMax] = extent(rows.map((r) => r.holders_pct), props.retailOut, props.retailIn)
    const [yMin, yMax] = extent(rows.map((r) => r.big_diff), -props.bigThreshold, props.bigThreshold)
    const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

    const data = rows.map((row) => {
        const x = clamp(row.holders_pct, xMin, xMax)
        const y = clamp(row.big_diff, yMin, yMax)
        // 超出範圍的點貼在邊緣，用空心圓表示真實數值在畫面外
        const clipped = x !== row.holders_pct || y !== row.big_diff
        // 沒有股價或平盤用灰色，不歸到漲或跌
        const color = !row.price_pct ? c.muted : polarityColor(row.price_pct)
        return {
            value: [x, y],
            detail: row,
            itemStyle: clipped
                ? { color: "transparent", borderColor: color, borderWidth: 1.5 }
                : { color, opacity: 0.75 },
        }
    })

    const guide = { color: c.muted, type: "dashed", width: 1 }
    const zoneLabel = (text: string, position: string) => ({
        show: true,
        position,
        color: c.secondary,
        fontSize: 12,
        formatter: text,
    })

    return {
        grid: { left: 64, right: 24, top: 16, bottom: 48 },
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                const row = params.data?.detail as HoldersRow | undefined
                if (!row) {
                    return ""
                }
                return [
                    `<strong>${row.code} ${row.name ?? ""}</strong>`,
                    `股價週漲跌　${signedPct(row.price_pct, 1)}`,
                    `股東人數　${signedPct(row.holders_pct, 1)} (${row.holders_diff.toLocaleString()} 人)`,
                    `千張大戶　${signed(row.big_diff)} 百分點 (${row.big_pct.toFixed(1)}%)`,
                ].join("<br>")
            },
        },
        xAxis: {
            type: "value",
            min: xMin,
            max: xMax,
            name: "股東人數變化 (%)",
            nameLocation: "middle",
            nameGap: 28,
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            // 邊界是依資料算出的零碎數字，只顯示中間的整數刻度
            axisLabel: { color: c.muted, fontSize: 11, showMinLabel: false, showMaxLabel: false },
            splitLine: { show: false },
        },
        yAxis: {
            type: "value",
            min: yMin,
            max: yMax,
            name: "千張大戶比例變化 (百分點)",
            // 名稱直排貼在 Y 軸旁，與 X 軸名稱的擺法一致
            nameLocation: "middle",
            nameRotate: 90,
            nameGap: 36,
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            // 邊界是依資料算出的零碎數字，只顯示中間的整數刻度
            axisLabel: { color: c.muted, fontSize: 11, showMinLabel: false, showMaxLabel: false },
            splitLine: { show: false },
        },
        series: [
            {
                type: "scatter",
                symbolSize: 8,
                cursor: "pointer",
                data,
                emphasis: { scale: 1.6 },
                markLine: {
                    silent: true,
                    symbol: "none",
                    label: { show: false },
                    lineStyle: guide,
                    data: [
                        { yAxis: props.bigThreshold },
                        { yAxis: -props.bigThreshold },
                        { xAxis: props.retailIn },
                        { xAxis: props.retailOut },
                    ],
                },
                markArea: {
                    silent: true,
                    data: [
                        [
                            {
                                coord: [xMin, props.bigThreshold],
                                itemStyle: { color: buyColor(), opacity: 0.06 },
                                label: zoneLabel("大戶收、散戶走", "insideTopLeft"),
                            },
                            { coord: [0, yMax] },
                        ],
                        [
                            {
                                coord: [1, yMin],
                                itemStyle: { color: sellColor(), opacity: 0.06 },
                                label: zoneLabel("大戶賣、散戶接", "insideBottomRight"),
                            },
                            { coord: [xMax, -props.bigThreshold] },
                        ],
                    ],
                },
            },
        ],
    }
})

function onClick(params: any) {
    const row = params.data?.detail as HoldersRow | undefined
    if (row) {
        emit("select", row.code)
    }
}
</script>

<template>
    <VChart class="chart chart-tall" :option="option" autoresize @click="onClick" />
</template>
