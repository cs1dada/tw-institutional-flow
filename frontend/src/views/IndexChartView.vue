<script setup lang="ts">
/**
 * 大盤指數 K 線。
 *
 * 只向後端要日線，週線與月線由前端聚合而成，切換週期與區間都不必重新請求。
 * 頁首另有大盤指標卡 (櫃買、法人、融資、匯率、VIX)，K 線下方為大盤籌碼圖，
 * 兩者的資料來自 market.json，載入失敗時不影響 K 線。
 *
 * 「查看日期」可回看過去某天：總覽與籌碼圖改以那天為最後一天，K 線的起迄不受影響。
 */
import { computed, onMounted, ref } from "vue"
import VChart from "vue-echarts"

import { loadIndex, loadMarket } from "@/api/dataSource"
import MarketChipPanel from "@/components/MarketChipPanel.vue"
import MarketOverview from "@/components/MarketOverview.vue"
import type { Bar, IndexPayload, MarketPayload, Period, ZoomRange } from "@/types"
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
import { marketAsOf } from "@/utils/market"

const INDEX_TABLE_ROWS = 20

const payload = ref<IndexPayload | null>(null)
const error = ref<string | null>(null)
const market = ref<MarketPayload | null>(null)
const period = ref<Period>("daily")
const range = ref<RangeKey>("1y")
const customFrom = ref<string | null>(null)
const customTo = ref<string | null>(null)

const rows = computed(() => (payload.value ? expandRows(payload.value) : []))

/* ===== 查看日期 ===== */

/** 回看的日期 (YYYYMMDD)，null 代表最新 */
const asOf = ref<string | null>(null)

/** 有籌碼資料的交易日，查看日期只能落在這個範圍 */
const chipDates = computed(() => {
    if (!market.value) {
        return []
    }
    const at = market.value.chip.fields.indexOf("date")
    return market.value.chip.TWSE.map((row) => String(row[at]))
})

const asOfLimits = computed(() => {
    const dates = chipDates.value
    return dates.length
        ? { min: formatDate(dates[0]), max: formatDate(dates[dates.length - 1]) }
        : { min: "", max: "" }
})

const asOfValue = computed(() => formatDate(asOf.value ?? chipDates.value[chipDates.value.length - 1] ?? ""))

/** 選到假日時往前找最近的交易日；選到最新一天等同回到最新 */
function onAsOfChange(event: Event) {
    const picked = (event.target as HTMLInputElement).value.replace(/-/g, "")
    const dates = chipDates.value
    if (!picked || !dates.length || picked >= dates[dates.length - 1]) {
        asOf.value = null
        return
    }
    const day = [...dates].reverse().find((date) => date <= picked)
    asOf.value = day ?? dates[0]
}

const viewMarket = computed(() =>
    market.value && asOf.value ? marketAsOf(market.value, asOf.value) : market.value,
)

const viewTaiex = computed(() =>
    asOf.value ? rows.value.filter((row) => row.date <= asOf.value!) : rows.value,
)

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
    // 籌碼資料是附加資訊，失敗只在主控台記錄
    loadMarket()
        .then((data) => {
            market.value = data
        })
        .catch((err) => console.warn("大盤籌碼載入失敗", err))
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
                <h1>大盤指數</h1>
                <p class="subtitle">
                    加權與櫃買指數、三大法人、融資融券與維持率、匯率與恐慌指標，
                    以及加權指數的日週月 K 線
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ error ? `載入失敗：${error}` : headline }}</span>
                <!-- 回看過去某天：總覽與籌碼圖以那天為最後一天，K 線不受影響 -->
                <div
                    v-if="chipDates.length"
                    class="asof"
                    title="總覽與籌碼圖以選定的日期為最後一天，K 線的起迄不受影響"
                >
                    <label class="asof-label">
                        <span>{{ asOf ? "回看" : "查看日期" }}</span>
                        <input
                            type="date"
                            :value="asOfValue"
                            :min="asOfLimits.min"
                            :max="asOfLimits.max"
                            :class="{ 'is-past': asOf }"
                            @change="onAsOfChange"
                        >
                    </label>
                    <button v-if="asOf" type="button" class="asof-reset" @click="asOf = null">回到最新</button>
                </div>
            </div>
        </header>

        <MarketOverview :taiex="viewTaiex" :market="viewMarket" />

        <MarketChipPanel :taiex="viewTaiex" :market="viewMarket" />

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

<style scoped>
.head-meta {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
}

.asof {
    display: flex;
    align-items: center;
    gap: 6px;
}

.asof-label {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
    font-size: 12px;
}

/* 回看中時把日期框標成投信橘，提醒目前看的不是最新資料 */
.asof-label input.is-past {
    border-color: var(--series-trust);
    color: var(--series-trust);
}

.asof-reset {
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-1);
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
}
</style>
