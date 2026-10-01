<script setup lang="ts">
/**
 * 大盤指數 K 線。
 *
 * 只向後端要日線，週線與月線由前端聚合而成，切換週期與區間都不必重新請求。
 */
import { computed, onMounted, ref } from "vue"
import VChart from "vue-echarts"

import { loadIndex } from "@/api/dataSource"
import type { Bar, IndexPayload, Period, ZoomRange } from "@/types"
import { formatDate, signed, toCompactDate } from "@/utils/format"
import {
    DEFAULT_RANGE,
    PERIOD_LABELS,
    PERIOD_MA,
    RANGE_PRESETS,
    aggregate,
    expandRows,
    rangeBounds,
    visibleRange,
    withChange,
    type RangeKey,
} from "@/utils/indexBars"
import { buildCandleOption } from "@/utils/candleChart"

const INDEX_TABLE_ROWS = 20

const payload = ref<IndexPayload | null>(null)
const error = ref<string | null>(null)
const period = ref<Period>("daily")
const range = ref<RangeKey>("1y")
const customFrom = ref<string | null>(null)
const customTo = ref<string | null>(null)

const rows = computed(() => (payload.value ? expandRows(payload.value) : []))

const bars = computed<Bar[]>(() =>
    rows.value.length ? withChange(aggregate(rows.value, period.value)) : [],
)

const bounds = computed(() =>
    rows.value.length
        ? rangeBounds(rows.value, range.value, customFrom.value, customTo.value)
        : null,
)

const zoom = computed<ZoomRange | null>(() =>
    bars.value.length && bounds.value ? visibleRange(bars.value, bounds.value) : null,
)

const latest = computed(() => (zoom.value ? bars.value[zoom.value.end] : null))

/** 表格只列出區間內最後幾根，與圖上看到的範圍一致 */
const tableRows = computed(() => {
    if (!zoom.value) {
        return []
    }
    return bars.value
        .slice(zoom.value.start, zoom.value.end + 1)
        .slice(-INDEX_TABLE_ROWS)
        .reverse()
})

/** 日期輸入框顯示目前區間，並限制在有資料的範圍內 */
const dateLimits = computed(() => {
    if (!rows.value.length) {
        return { min: "", max: "" }
    }
    return {
        min: formatDate(rows.value[0].date),
        max: formatDate(rows.value[rows.value.length - 1].date),
    }
})

const fromValue = computed(() => (bounds.value ? formatDate(bounds.value.from) : ""))
const toValue = computed(() => (bounds.value ? formatDate(bounds.value.to) : ""))

const chartOption = computed(() => {
    if (!zoom.value || !bars.value.length) {
        return {}
    }
    // 圖表設定與個股 K 線共用，改配色或版面只要改 utils/candleChart.ts
    return buildCandleOption(bars.value, {
        maSizes: PERIOD_MA[period.value],
        zoom: zoom.value,
        priceName: "指數",
    })
})

const headline = computed(() => {
    if (!latest.value) {
        return "載入中"
    }
    const bar = latest.value
    return `${formatDate(bar.date)}　收盤 ${bar.close.toFixed(2)}　${signed(bar.diff)}（${signed(bar.pct)}%）`
})

const chartNote = computed(() => {
    if (!zoom.value || !latest.value) {
        return ""
    }
    const count = zoom.value.end - zoom.value.start + 1
    const ma = PERIOD_MA[period.value].map((size) => `MA${size}`).join("、")
    return `顯示 ${formatDate(bars.value[zoom.value.start].start_date)} ~ ${formatDate(latest.value.date)}，`
        + `共 ${count} 根${PERIOD_LABELS[period.value]} K 棒`
        + `（資料自 ${formatDate(rows.value[0].date)} 起，可拖曳下方滑桿或以滾輪縮放）；均線為 ${ma}`
})

function setPeriod(next: Period) {
    period.value = next
    // 自訂區間是使用者明確指定的，切換週期時保留；
    // 否則套用該週期的預設區間，避免月線只剩幾根 K 棒
    if (range.value !== "custom") {
        range.value = DEFAULT_RANGE[next]
    }
}

function setRange(next: RangeKey) {
    range.value = next
    customFrom.value = null
    customTo.value = null
}

function onDateChange(which: "from" | "to", event: Event) {
    const value = toCompactDate((event.target as HTMLInputElement).value)
    if (!value) {
        return
    }
    // 切到自訂區間時，另一端沿用目前顯示的範圍
    const current = bounds.value
    customFrom.value = which === "from" ? value : (customFrom.value ?? current?.from ?? null)
    customTo.value = which === "to" ? value : (customTo.value ?? current?.to ?? null)
    range.value = "custom"
}

onMounted(async () => {
    try {
        payload.value = await loadIndex()
    } catch (err) {
        error.value = (err as Error).message
    }
})
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>加權指數 K 線</h1>
                <p class="subtitle">
                    發行量加權股價指數的開高低收與成交金額，週線與月線由日線聚合而成
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ error ? `載入失敗：${error}` : headline }}</span>
            </div>
        </header>

        <div class="controls">
            <div class="control">
                <span class="control-label">週期</span>
                <div class="tabs" role="tablist">
                    <button
                        v-for="(label, key) in PERIOD_LABELS"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': period === key }"
                        role="tab"
                        @click="setPeriod(key as Period)"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>

            <div class="control">
                <span class="control-label">區間</span>
                <div class="tabs" role="tablist">
                    <button
                        v-for="preset in RANGE_PRESETS"
                        :key="preset.key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': range === preset.key }"
                        role="tab"
                        @click="setRange(preset.key)"
                    >
                        {{ preset.label }}
                    </button>
                </div>
            </div>

            <label class="control">
                <span class="control-label">起</span>
                <input
                    type="date"
                    :value="fromValue"
                    :min="dateLimits.min"
                    :max="dateLimits.max"
                    @change="onDateChange('from', $event)"
                >
            </label>

            <label class="control">
                <span class="control-label">迄</span>
                <input
                    type="date"
                    :value="toValue"
                    :min="dateLimits.min"
                    :max="dateLimits.max"
                    @change="onDateChange('to', $event)"
                >
            </label>
        </div>

        <section class="panel" data-nav="K 線圖">
            <div class="panel-head">
                <h2>{{ payload?.name ?? "加權指數" }}{{ PERIOD_LABELS[period] }}</h2>
                <p class="panel-note">{{ chartNote || "載入中" }}</p>
            </div>
            <VChart v-if="bars.length" class="chart chart-candle" :option="chartOption" autoresize />
            <p v-else class="notice">
                尚無指數資料，請先執行 python scripts/ingest_index.py 120
            </p>
        </section>

        <section class="panel" data-nav="近期行情">
            <div class="panel-head">
                <h2>近期行情</h2>
                <p class="panel-note">
                    區間內最後 {{ tableRows.length }} 根{{ PERIOD_LABELS[period] }} K 棒，漲跌以前一根收盤價計算
                </p>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>期間</th>
                            <th class="num">開盤</th>
                            <th class="num">最高</th>
                            <th class="num">最低</th>
                            <th class="num">收盤</th>
                            <th class="num">漲跌</th>
                            <th class="num">漲跌幅</th>
                            <th class="num">成交金額（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!tableRows.length" class="empty-row">
                            <td colspan="8">無資料</td>
                        </tr>
                        <tr v-for="bar in tableRows" :key="bar.key">
                            <td>{{ bar.label }}</td>
                            <td class="num">{{ bar.open.toFixed(2) }}</td>
                            <td class="num">{{ bar.high.toFixed(2) }}</td>
                            <td class="num">{{ bar.low.toFixed(2) }}</td>
                            <td class="num">{{ bar.close.toFixed(2) }}</td>
                            <td class="num" :class="bar.diff === null || bar.diff >= 0 ? 'val-buy' : 'val-sell'">
                                {{ signed(bar.diff) }}
                            </td>
                            <td class="num" :class="bar.diff === null || bar.diff >= 0 ? 'val-buy' : 'val-sell'">
                                {{ signed(bar.pct) }}%
                            </td>
                            <td class="num">{{ bar.turnover.toFixed(0) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>
