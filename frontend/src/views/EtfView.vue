<script setup lang="ts">
/**
 * 主動式 ETF 動向。
 *
 * 兩件不同的事放在同一頁：ETF 自己被法人買賣的情形 (來自當日資料)，
 * 以及這些 ETF 持有哪些股票 (來自各投信的持股快照)。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadDay, loadEtf, loadMeta } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import type { DateItem, DayData, EtfData, EtfTopStock, Investor, StockFlow } from "@/types"
import { INVESTOR_LABELS, etfFlowList, expandStocks, marketNote } from "@/utils/flow"
import { YI, formatDate, toYi } from "@/utils/format"
import { colors } from "@/utils/theme"

const TOP_CHART_ROWS = 15

const CHANGE_LABELS: Record<string, string> = {
    new: "新進",
    removed: "移除",
    changed: "調整",
}

const dates = ref<DateItem[]>([])
const dateMeta = ref<Record<string, DateItem>>({})
const selectedDate = ref<string>("")
const investor = ref<Investor>("all")
const etfCode = ref<string | null>(null)

const day = ref<DayData | null>(null)
const etf = ref<EtfData | null>(null)
const error = ref<string | null>(null)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    if (!day.value) {
        return "載入中"
    }
    return `${formatDate(day.value.date)}　${INVESTOR_LABELS[investor.value]}`
})

/* ===== ETF 自身的法人買賣超 ===== */

const flowRows = computed<StockFlow[]>(() => {
    if (!day.value) {
        return []
    }
    return etfFlowList(expandStocks(day.value), investor.value)
        .filter((row) => Math.abs(row.amount) > 0)
})

const flowNote = computed(() => {
    if (!day.value) {
        return ""
    }
    const total = etfFlowList(expandStocks(day.value), investor.value).length
    return `${formatDate(day.value.date)} ${INVESTOR_LABELS[investor.value]}買賣這些 ETF 本身的金額排行，`
        + `共 ${total} 檔。自營商多為造市部位，不宜視為看多看空訊號`
})

/* ===== 合計持股 ===== */

const topStocks = computed<EtfTopStock[]>(() => etf.value?.top_stocks ?? [])

const topNote = computed(() => {
    const dateText = (etf.value?.dates ?? []).map(formatDate).join("、")
    return "已介接的主動式 ETF 合計持有最多的個股，市值以收盤價估算。"
        + `各投信的持股基準日不同，各檔皆取自己的最新快照（${dateText}）`
})

/* ===== 持股變動 ===== */

const changes = computed(() => etf.value?.changes ?? [])

const changeNote = computed(() => {
    if (!changes.value.length) {
        const count = etf.value?.dates?.length ?? 0
        return `持股變動需要每檔 ETF 各有兩個快照，目前只有 ${count} 個日期的資料，明日再執行一次即可比對`
    }
    // 各檔 ETF 的持股基準日不同，因此不標示單一的日期區間
    return `各 ETF 與自己前一個快照相比的持股變動，共 ${changes.value.length} 筆`
})

/* ===== 持股明細 ===== */

const etfs = computed(() => etf.value?.etfs ?? [])

const currentEtf = computed(() => etfs.value.find((e) => e.etf_code === etfCode.value) ?? null)

const holdings = computed(() =>
    (etf.value?.holdings ?? []).filter((row) => row.etf_code === etfCode.value),
)

const holdingNote = computed(() => {
    const current = currentEtf.value
    if (!current) {
        return ""
    }
    return `${current.etf_code} ${current.etf_name ?? ""}　${formatDate(current.date)}`
        + `　規模 ${((current.aum ?? 0) / YI).toFixed(1)} 億`
        + `　淨值 ${current.nav === null ? "--" : current.nav}`
        + `　持股 ${current.holding_count} 檔`
})

/* ===== tooltip ===== */

function flowTooltip(row: StockFlow): string {
    return `<strong>${row.code} ${row.name}</strong><br>`
        + `買賣超　${toYi(row.amount, 2)} 億<br>`
        + `外資　　${toYi(row.foreign_amt, 2)} 億<br>`
        + `投信　　${toYi(row.trust_amt, 2)} 億<br>`
        + `自營商　${toYi(row.dealer_amt, 2)} 億`
}

function topTooltip(row: EtfTopStock): string {
    const c = colors()
    return `<strong>${row.stock_code} ${row.stock_name ?? ""}</strong><br>`
        + `合計市值　${((row.market_value ?? 0) / YI).toFixed(2)} 億<br>`
        + `合計股數　${(row.total_shares ?? 0).toLocaleString()} 股<br>`
        + `持有檔數　${row.etf_count} 檔 ETF<br>`
        + `<span style="color:${c.muted}">${row.industry ?? ""}</span>`
}

async function load(date: string) {
    error.value = null
    try {
        const [dayData, etfData] = await Promise.all([loadDay(date), loadEtf()])
        day.value = dayData
        etf.value = etfData
        selectedDate.value = dayData.date
        if (!etfCode.value || !etfData.etfs.some((e) => e.etf_code === etfCode.value)) {
            etfCode.value = etfData.etfs[0]?.etf_code ?? null
        }
    } catch (err) {
        error.value = (err as Error).message
    }
}

watch(selectedDate, (date) => {
    if (date && date !== day.value?.date) {
        load(date)
    }
})

onMounted(async () => {
    try {
        const meta = await loadMeta()
        dates.value = meta.dates ?? []
        for (const item of dates.value) {
            dateMeta.value[item.date] = item
        }
        const preferred = dates.value.find((item) => item.complete) ?? dates.value[0]
        if (preferred) {
            selectedDate.value = preferred.date
            await load(preferred.date)
        }
    } catch (err) {
        error.value = (err as Error).message
    }
})

function dateLabel(item: DateItem): string {
    const note = marketNote(item)
    return formatDate(item.date) + (note ? `（${note}）` : "")
}
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>主動式 ETF 動向</h1>
                <p class="subtitle">
                    主動式 ETF 依規定每日揭露完整持股，本頁彙整這些 ETF 買了哪些股票，以及它們自己被法人買賣的情形
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div class="controls">
            <label class="control">
                <span class="control-label">交易日</span>
                <select v-model="selectedDate">
                    <option v-for="item in dates" :key="item.date" :value="item.date">
                        {{ dateLabel(item) }}
                    </option>
                </select>
            </label>

            <div class="control">
                <span class="control-label">法人別</span>
                <div class="tabs" role="tablist">
                    <button
                        v-for="(label, key) in INVESTOR_LABELS"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': investor === key }"
                        role="tab"
                        @click="investor = key as Investor"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>
        </div>

        <section class="panel">
            <div class="panel-head">
                <h2>ETF 持股變動</h2>
                <p class="panel-note">{{ changeNote }}</p>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>ETF</th><th>代號</th><th>個股</th><th>異動</th>
                            <th class="num">股數變動</th><th class="num">估算金額（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!changes.length" class="empty-row">
                            <td colspan="6">無資料</td>
                        </tr>
                        <tr
                            v-for="(row, i) in changes"
                            :key="`${row.etf_code}-${row.stock_code}-${i}`"
                        >
                            <td>{{ row.etf_code }}</td>
                            <td>{{ row.stock_code }}</td>
                            <td>{{ row.stock_name ?? "" }}</td>
                            <td :class="row.share_change >= 0 ? 'val-buy' : 'val-sell'">
                                {{ CHANGE_LABELS[row.change_type] ?? row.change_type }}
                            </td>
                            <td class="num" :class="row.share_change >= 0 ? 'val-buy' : 'val-sell'">
                                {{ (row.share_change > 0 ? "+" : "") + row.share_change.toLocaleString() }}
                            </td>
                            <td class="num" :class="row.share_change >= 0 ? 'val-buy' : 'val-sell'">
                                {{ toYi(row.value_change ?? 0, 2) }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>ETF 合計持股</h2>
                <p class="panel-note">{{ topNote }}</p>
            </div>
            <div class="detail-grid">
                <BarChart
                    v-if="topStocks.length"
                    :rows="topStocks.slice(0, TOP_CHART_ROWS)"
                    :label-width="170"
                    :name-of="(row: EtfTopStock) => `${row.stock_code} ${row.stock_name ?? ''}`"
                    :value-of="(row: EtfTopStock) => (row.market_value ?? 0) / YI"
                    :color-of="() => colors().foreign"
                    :tooltip="topTooltip"
                />
                <div v-else class="chart"></div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>代號</th><th>名稱</th><th>類股</th>
                                <th class="num">ETF 檔數</th><th class="num">市值（億）</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="!topStocks.length" class="empty-row">
                                <td colspan="5">無資料</td>
                            </tr>
                            <tr v-for="row in topStocks" :key="row.stock_code">
                                <td>{{ row.stock_code }}</td>
                                <td>{{ row.stock_name ?? "" }}</td>
                                <td>{{ row.industry ?? "" }}</td>
                                <td class="num">{{ row.etf_count }}</td>
                                <td class="num">{{ ((row.market_value ?? 0) / YI).toFixed(2) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>ETF 的法人買賣超</h2>
                <p class="panel-note">{{ flowNote }}</p>
            </div>
            <div class="chart-scroll">
                <BarChart
                    v-if="flowRows.length"
                    :rows="flowRows"
                    :name-of="(row: StockFlow) => `${row.code} ${row.name}`"
                    :value-of="(row: StockFlow) => row.amount / YI"
                    :tooltip="flowTooltip"
                />
                <p v-else class="notice">當日這些 ETF 沒有法人買賣超</p>
            </div>
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>已介接 ETF 持股明細</h2>
                <p class="panel-note">{{ holdingNote || "各檔 ETF 的完整持股，依權重排序" }}</p>
            </div>
            <div v-if="etfs.length" class="controls controls-inline">
                <button
                    v-for="item in etfs"
                    :key="item.etf_code"
                    type="button"
                    class="chip"
                    :class="{ 'is-active': item.etf_code === etfCode }"
                    @click="etfCode = item.etf_code"
                >
                    {{ item.etf_code }} {{ item.etf_name ?? "" }}
                </button>
            </div>
            <p v-else class="notice">尚無持股資料，請先執行 scripts/ingest_etf.py</p>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>名稱</th><th class="num">股數</th>
                            <th class="num">權重（%）</th><th class="num">收盤</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!holdings.length" class="empty-row">
                            <td colspan="5">無資料</td>
                        </tr>
                        <tr v-for="row in holdings" :key="row.stock_code">
                            <td>{{ row.stock_code }}</td>
                            <td>{{ row.stock_name ?? "" }}</td>
                            <td class="num">{{ (row.shares ?? 0).toLocaleString() }}</td>
                            <td class="num">{{ row.weight === null ? "--" : row.weight.toFixed(2) }}</td>
                            <td class="num">{{ row.close === null || row.close === undefined ? "--" : row.close.toFixed(2) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>
