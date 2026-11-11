<script setup lang="ts">
/**
 * 個股各持股級距的橫向長條圖。
 *
 * 「變化」模式畫每個級距佔股份的週增減 (百分點)，散戶級距增加、千張級距減少，
 * 一眼看出股票往哪裡流；「分布」模式畫本週與前一週各級距佔股份的比例。
 * 第 16 級 (差異數調整) 與第 17 級 (合計) 不是持股級距，不畫。
 */
import { computed, ref } from "vue"
import VChart from "vue-echarts"

import type { HoldersLevel } from "@/types"
import { formatDate, signed } from "@/utils/format"
import { baseTooltip, colors, polarityColor } from "@/utils/theme"

type Mode = "diff" | "share"

const props = defineProps<{
    latest: { date: string; levels: HoldersLevel[] }
    previous: { date: string; levels: HoldersLevel[] } | null
}>()

/** 集保級距以股為單位，換成張比較好讀 */
const LOT_LABELS: Record<number, string> = {
    1: "未滿 1 張",
    2: "1-5 張",
    3: "5-10 張",
    4: "10-15 張",
    5: "15-20 張",
    6: "20-30 張",
    7: "30-40 張",
    8: "40-50 張",
    9: "50-100 張",
    10: "100-200 張",
    11: "200-400 張",
    12: "400-600 張",
    13: "600-800 張",
    14: "800-1000 張",
    15: "1000 張以上",
}

const LAST_LEVEL = 15

const mode = ref<Mode>("diff")
const activeMode = computed<Mode>(() => (props.previous ? mode.value : "share"))

const levels = computed(() => {
    const prevMap = new Map((props.previous?.levels ?? []).map((l) => [l.level, l]))
    return props.latest.levels
        .filter((l) => l.level <= LAST_LEVEL)
        .map((l) => {
            const prev = prevMap.get(l.level) ?? null
            return {
                label: LOT_LABELS[l.level] ?? l.label,
                now: l,
                prev,
                pctDiff: prev ? +(l.pct - prev.pct).toFixed(2) : null,
                peopleDiff: prev ? l.people - prev.people : null,
            }
        })
})

const height = computed(() => `${levels.value.length * 24 + 60}px`)

const option = computed(() => {
    const c = colors()
    // 由上而下是小級距到大級距，category 軸由下往上排，所以反轉
    const rows = levels.value.slice().reverse()
    const axis = {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: c.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        nameTextStyle: { color: c.muted, fontSize: 11 },
    }

    const tooltip = {
        ...baseTooltip(),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
            const row = rows[params[0].dataIndex]
            const lines = [
                `<strong>${row.label}</strong>`,
                `人數　${row.now.people.toLocaleString()}${row.peopleDiff === null ? "" : ` (${row.peopleDiff > 0 ? "+" : ""}${row.peopleDiff.toLocaleString()})`}`,
                `佔股份　${row.now.pct.toFixed(2)}%${row.pctDiff === null ? "" : ` (${signed(row.pctDiff)})`}`,
            ]
            return lines.join("<br>")
        },
    }

    const yAxis = {
        type: "category",
        data: rows.map((r) => r.label),
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
        axisLabel: { color: c.secondary, fontSize: 12 },
    }

    if (activeMode.value === "diff") {
        return {
            grid: { left: 90, right: 56, top: 10, bottom: 30 },
            tooltip,
            // 兩側各留 25% 空間給數值標籤，負值最長的那條標籤才不會壓到級距名稱
            xAxis: {
                ...axis,
                name: "百分點",
                min: (v: { min: number; max: number }) => (v.min < 0 ? +(v.min - (v.max - v.min) * 0.25).toFixed(1) : 0),
                max: (v: { min: number; max: number }) => (v.max > 0 ? +(v.max + (v.max - v.min) * 0.25).toFixed(1) : 0),
                axisLabel: { ...axis.axisLabel, showMinLabel: false, showMaxLabel: false },
            },
            yAxis,
            series: [
                {
                    type: "bar",
                    barWidth: 12,
                    data: rows.map((r) => {
                        const value = r.pctDiff ?? 0
                        return {
                            value,
                            itemStyle: {
                                color: polarityColor(value),
                                borderRadius: value >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
                            },
                            label: { position: value >= 0 ? "right" : "left" },
                        }
                    }),
                    label: {
                        show: true,
                        color: c.secondary,
                        fontSize: 11,
                        formatter: (p: any) => signed(p.data.value),
                    },
                },
            ],
        }
    }

    const series: any[] = [
        {
            name: formatDate(props.latest.date),
            type: "bar",
            barWidth: props.previous ? 8 : 12,
            itemStyle: { color: c.foreign, borderRadius: [0, 3, 3, 0] },
            data: rows.map((r) => r.now.pct),
        },
    ]
    if (props.previous) {
        series.push({
            name: formatDate(props.previous.date),
            type: "bar",
            barWidth: 8,
            itemStyle: { color: c.muted, opacity: 0.6, borderRadius: [0, 3, 3, 0] },
            data: rows.map((r) => r.prev?.pct ?? 0),
        })
    }
    return {
        grid: { left: 90, right: 24, top: props.previous ? 30 : 10, bottom: 30 },
        legend: props.previous
            ? {
                top: 0,
                icon: "roundRect",
                itemWidth: 10,
                itemHeight: 10,
                textStyle: { color: c.secondary, fontSize: 12 },
            }
            : undefined,
        tooltip,
        xAxis: { ...axis, name: "%" },
        yAxis,
        series,
    }
})
</script>

<template>
    <div>
        <div v-if="previous" class="chip-row level-modes">
            <button type="button" class="chip" :class="{ 'is-active': activeMode === 'diff' }" @click="mode = 'diff'">
                佔股份變化
            </button>
            <button type="button" class="chip" :class="{ 'is-active': activeMode === 'share' }" @click="mode = 'share'">
                持股分布
            </button>
        </div>
        <VChart class="level-chart" :style="{ height }" :option="option" autoresize />
    </div>
</template>

<style scoped>
.level-modes {
    display: flex;
    gap: 6px;
    margin-bottom: 6px;
}

.level-chart {
    width: 100%;
}
</style>
