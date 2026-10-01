<script setup lang="ts">
/**
 * 經理人成本三層疊圖。
 *
 * 第一層：收盤價
 * 第二層：各 ETF 的持倉成本線 (灰色細線) 與全體加權成本 (虛線)
 * 第三層：觀察期間的買點 (圓點大小代表金額) 與共識價帶
 *
 * ETF 多達十餘檔，超過可辨識的分類色數量，因此成本線一律用灰色，
 * 只有使用者指定的那一檔上色，其餘靠 tooltip 辨識。
 */
import { computed } from "vue"
import VChart from "vue-echarts"

import type { EtfCostDetail } from "@/types"
import { YI, formatDate } from "@/utils/format"
import { baseTooltip, buyColor, colors } from "@/utils/theme"

const props = defineProps<{
    detail: EtfCostDetail
    /** 要上色強調的 ETF，null 表示不強調 */
    highlight: string | null
}>()

const BUY_SERIES = "買點"

function price(value: number | null | undefined): string {
    return value === null || value === undefined ? "--" : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

const option = computed(() => {
    const c = colors()
    const d = props.detail
    const labels = d.dates.map((date) => formatDate(date).slice(5))
    const index = new Map(d.dates.map((date, i) => [date, i]))

    // 同一天同一檔 ETF 只會有一筆，圓點大小依金額開根號縮放，避免大單把小單壓到看不見
    const buys = d.trades.filter((t) => t[2] > 0)
    const maxAmt = Math.max(1, ...buys.map((t) => t[2] * t[3]))
    const buyPoints = buys.map(([date, etf, shares, p]) => ({
        value: [index.get(date) ?? 0, p],
        etf,
        shares,
        amount: shares * p,
        symbolSize: 8 + 16 * Math.sqrt((shares * p) / maxAmt),
    }))

    const costSeries = Object.entries(d.cost_lines).map(([etf, line]) => {
        const active = etf === props.highlight
        return {
            name: etf,
            type: "line",
            data: line,
            symbol: "none",
            connectNulls: false,
            z: active ? 4 : 2,
            lineStyle: {
                width: active ? 2 : 1,
                color: active ? c.trust : c.muted,
                opacity: active ? 1 : 0.45,
            },
            emphasis: { focus: "series", lineStyle: { width: 2, opacity: 1 } },
        }
    })

    const consensus = d.consensus
    const closeMarks: Record<string, unknown> = {}
    if (consensus) {
        closeMarks.markArea = {
            silent: true,
            itemStyle: { color: c.trust, opacity: 0.1 },
            data: [[{ yAxis: consensus.band[0] }, { yAxis: consensus.band[1] }]],
        }
    }
    const lines: unknown[] = []
    if (consensus) {
        lines.push(
            {
                yAxis: consensus.equal,
                lineStyle: { color: c.trust, type: "solid", width: 1 },
                label: { formatter: `等權 ${price(consensus.equal)}`, color: c.secondary, position: "insideEndTop" },
            },
            {
                yAxis: consensus.weighted,
                lineStyle: { color: c.trust, type: "dotted", width: 1 },
                label: { formatter: `資金加權 ${price(consensus.weighted)}`, color: c.secondary, position: "insideEndBottom" },
            },
        )
    }
    for (const event of d.events) {
        const i = index.get(event.date)
        if (i === undefined) {
            continue
        }
        lines.push({
            xAxis: i,
            lineStyle: { color: c.muted, type: "dashed", width: 1 },
            label: {
                formatter: `除權 / 股本變動 ×${event.factor.toFixed(2)}`,
                color: c.secondary,
                position: "insideEndTop",
            },
        })
    }
    if (lines.length) {
        closeMarks.markLine = { silent: true, symbol: "none", data: lines }
    }

    return {
        grid: { left: 64, right: 24, top: 44, bottom: 34 },
        legend: {
            data: ["收盤價", "全體持倉成本", BUY_SERIES],
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
            axisPointer: { type: "line", lineStyle: { color: c.muted } },
            formatter: (params: any[]) => {
                const i = params[0]?.dataIndex ?? 0
                const date = d.dates[i]
                const rows = [`<strong>${d.code} ${d.name ?? ""}　${formatDate(date)}</strong>`]
                rows.push(`收盤價　${price(d.close[i])}`)
                rows.push(`全體持倉成本　${price(d.overall_cost[i])}`)
                if (props.highlight && d.cost_lines[props.highlight]) {
                    rows.push(`${props.highlight} 成本　${price(d.cost_lines[props.highlight][i])}`)
                }
                const trades = d.trades.filter((t) => t[0] === date)
                if (trades.length) {
                    rows.push(`<span style="color:${c.muted}">當日 ETF 買賣 (股數 × 推估價)</span>`)
                    for (const [, etf, shares, p] of trades) {
                        const lots = (shares / 1000).toLocaleString(undefined, { maximumFractionDigits: 0 })
                        rows.push(`${etf}　${shares > 0 ? "+" : ""}${lots} 張 @ ${price(p)}`
                            + `　${((shares * p) / YI).toFixed(2)} 億`)
                    }
                }
                return rows.join("<br>")
            },
        },
        xAxis: {
            type: "category",
            data: labels,
            boundaryGap: false,
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
        },
        yAxis: {
            type: "value",
            scale: true,
            name: "元",
            nameTextStyle: { color: c.muted, fontSize: 11 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        series: [
            ...costSeries,
            {
                name: "全體持倉成本",
                type: "line",
                data: d.overall_cost,
                symbol: "none",
                z: 3,
                lineStyle: { width: 2, type: "dashed", color: c.foreign },
                itemStyle: { color: c.foreign },
            },
            {
                name: "收盤價",
                type: "line",
                data: d.close,
                symbol: "circle",
                symbolSize: 6,
                showSymbol: false,
                z: 5,
                lineStyle: { width: 2, color: c.text },
                itemStyle: { color: c.text, borderColor: c.surface, borderWidth: 2 },
                ...closeMarks,
            },
            {
                name: BUY_SERIES,
                type: "scatter",
                data: buyPoints,
                z: 6,
                itemStyle: {
                    color: buyColor(),
                    opacity: 0.75,
                    borderColor: c.surface,
                    borderWidth: 2,
                },
            },
        ],
    }
})
</script>

<template>
    <VChart class="chart chart-tall" :option="option" autoresize />
</template>
