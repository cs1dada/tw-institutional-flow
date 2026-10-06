<script setup lang="ts">
/**
 * 主動式 ETF 每日榜單：今天的錢往哪裡去。
 *
 * 被買最兇、被賣最重的買方與賣方分開加總，同一檔股票可能同時出現在兩張榜單；
 * 最擁擠是被最多檔 ETF 同時持有的個股。方法見 notes/ETF_STRATEGY.md 第二節。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadEtfDaily, loadEtfDailyDates } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import type { EtfDailyCrowdedRow, EtfDailyData, EtfDailyDateItem, EtfDailySideRow } from "@/types"
import { YI, formatDate, toYi } from "@/utils/format"

type Board = "buys" | "sells" | "crowded"

const BOARD_LABELS: Record<Board, string> = {
    buys: "被買最兇",
    sells: "被賣最重",
    crowded: "最擁擠",
}

const BOARD_NOTES: Record<Board, string> = {
    buys: "當日加碼與新進的金額合計，出手家數越多，共識越強",
    sells: "當日減碼與出清的金額合計，留意經理人正在撤出的族群",
    crowded: "被最多檔 ETF 同時持有的個股。共識太強時，反轉的賣壓也可能集中，這是觀察假設",
}

const TYPE_LABELS: Record<string, string> = {
    new: "新進",
    add: "加碼",
    reduce: "減碼",
    removed: "出清",
}

// 預設顯示的名次，其餘收在「展開全部」
const COLLAPSED_ROWS = 10

const dates = ref<EtfDailyDateItem[]>([])
const selectedDate = ref("")
const daily = ref<EtfDailyData | null>(null)
const board = ref<Board>("buys")
const expanded = ref(false)
const openCode = ref<string | null>(null)
const error = ref<string | null>(null)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    return daily.value ? formatDate(daily.value.date) : "載入中"
})

const etfNames = computed(() => {
    const names: Record<string, string> = {}
    for (const item of daily.value?.etfs ?? []) {
        names[item.etf_code] = item.etf_name ?? ""
    }
    return names
})

const reportedCount = computed(() => daily.value?.etfs.filter((e) => e.reported).length ?? 0)

/** 當日尚未公布或無法比對的 ETF */
const missingEtfs = computed(() => daily.value?.etfs.filter((e) => !e.reported) ?? [])

const sideRows = computed<EtfDailySideRow[]>(() => {
    if (!daily.value || board.value === "crowded") {
        return []
    }
    return daily.value[board.value]
})

const crowdedRows = computed<EtfDailyCrowdedRow[]>(() => daily.value?.crowded ?? [])

const totalRows = computed(() => (board.value === "crowded" ? crowdedRows.value.length : sideRows.value.length))

const visibleSide = computed(() => (expanded.value ? sideRows.value : sideRows.value.slice(0, COLLAPSED_ROWS)))

const visibleCrowded = computed(() =>
    expanded.value ? crowdedRows.value : crowdedRows.value.slice(0, COLLAPSED_ROWS),
)

const sideLabel = computed(() => (board.value === "sells" ? "賣" : "買"))

const boardNote = computed(() => {
    if (!daily.value) {
        return ""
    }
    return `${formatDate(daily.value.date)}，${reportedCount.value} 檔以台股為主的主動式 ETF。${BOARD_NOTES[board.value]}`
})

function lots(shares: number): string {
    return Math.round(shares / 1000).toLocaleString()
}

function signedLots(value: number | null): string {
    if (value === null) {
        return "--"
    }
    return (value > 0 ? "+" : "") + value.toLocaleString()
}

function polarity(value: number | null): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

function etfLabel(code: string): string {
    return `${code} ${etfNames.value[code] ?? ""}`
}

function holderChange(row: EtfDailyCrowdedRow): string {
    const diff = row.holders - row.prev_holders
    return diff ? `${diff > 0 ? "+" : ""}${diff}` : ""
}

function toggle(code: string) {
    openCode.value = openCode.value === code ? null : code
}

function sideTooltip(row: EtfDailySideRow): string {
    const opposite = row.opposite_count
        ? `同日反向　${row.opposite_count} 家，${toYi(row.opposite_amount, 2)} 億<br>`
        : ""
    return `<strong>${row.code} ${row.name ?? ""}</strong><br>`
        + `推估金額　${toYi(row.amount, 2)} 億<br>`
        + `出手家數　${row.etf_count} 家<br>`
        + `ETF 張數　${lots(Math.abs(row.shares))} 張<br>`
        + opposite
        + `外資　　　${signedLots(row.foreign_lots)} 張<br>`
        + `投信　　　${signedLots(row.trust_lots)} 張`
}

function dateLabel(item: EtfDailyDateItem): string {
    const note = item.reported < item.listed ? `（已公布 ${item.reported}/${item.listed} 檔）` : ""
    return formatDate(item.date) + note
}

async function load(date: string) {
    error.value = null
    try {
        daily.value = await loadEtfDaily(date)
        selectedDate.value = daily.value.date
        openCode.value = null
    } catch (err) {
        error.value = (err as Error).message
    }
}

watch(selectedDate, (date) => {
    if (date && date !== daily.value?.date) {
        load(date)
    }
})

watch(board, () => {
    expanded.value = false
    openCode.value = null
})

onMounted(async () => {
    try {
        dates.value = (await loadEtfDailyDates()).dates
        // 預設顯示最近一個全部公布的日子，盤後陸續公布期間不會先看到不完整的榜單
        const preferred = dates.value.find((item) => item.reported === item.listed) ?? dates.value[0]
        if (preferred) {
            selectedDate.value = preferred.date
            await load(preferred.date)
        }
    } catch (err) {
        error.value = (err as Error).message
    }
})
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>ETF 每日榜單</h1>
                <p class="subtitle">
                    今天的資金去哪了：依主動式 ETF 每日揭露的持股，聚合當日加減碼，金額以當日成交均價 (VWAP) 推估
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div class="controls">
            <label class="control">
                <span class="control-label">揭露日</span>
                <select v-model="selectedDate">
                    <option v-for="item in dates" :key="item.date" :value="item.date">
                        {{ dateLabel(item) }}
                    </option>
                </select>
            </label>
        </div>

        <p v-if="missingEtfs.length" class="notice daily-notice">
            已公布 {{ reportedCount }}/{{ daily?.etfs.length }} 檔，未含
            {{ missingEtfs.map((e) => e.etf_code).join("、") }}。這是暫時榜單，資料進來後重新整理即可更新
        </p>

        <div v-if="daily" class="quote-grid daily-tiles">
            <div class="quote-card">
                <div class="quote-name">全體買進</div>
                <div class="quote-value val-buy">{{ toYi(daily.buy_amt, 1) }} 億</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">全體賣出</div>
                <div class="quote-value val-sell">{{ toYi(-daily.sell_amt, 1) }} 億</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">淨買賣</div>
                <div class="quote-value" :class="daily.buy_amt >= daily.sell_amt ? 'val-buy' : 'val-sell'">
                    {{ toYi(daily.buy_amt - daily.sell_amt, 1) }} 億
                </div>
            </div>
        </div>

        <section class="panel" data-nav="每日榜單">
            <div class="panel-head">
                <h2>{{ BOARD_LABELS[board] }}</h2>
                <p class="panel-note">{{ boardNote }}</p>
            </div>
            <div class="controls controls-inline">
                <div class="tabs" role="tablist">
                    <button
                        v-for="(label, key) in BOARD_LABELS"
                        :key="key"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': board === key }"
                        role="tab"
                        @click="board = key as Board"
                    >
                        {{ label }}
                    </button>
                </div>
            </div>

            <template v-if="board !== 'crowded'">
                <div class="chart-scroll">
                    <BarChart
                        v-if="visibleSide.length"
                        :rows="visibleSide"
                        :name-of="(row: EtfDailySideRow) => `${row.code} ${row.name ?? ''}`"
                        :value-of="(row: EtfDailySideRow) => row.amount / YI"
                        :tooltip="sideTooltip"
                    />
                </div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>代號</th><th>名稱</th>
                                <th class="num">幾家{{ sideLabel }}</th>
                                <th class="num">ETF 張數</th>
                                <th class="num">推估金額（億）</th>
                                <th class="num">同日反向</th>
                                <th class="num">外資（張）</th>
                                <th class="num">投信（張）</th>
                                <th>ETF</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="!visibleSide.length" class="empty-row">
                                <td colspan="9">無資料</td>
                            </tr>
                            <template v-for="row in visibleSide" :key="row.code">
                                <tr class="clickable" :class="{ 'is-selected': openCode === row.code }" @click="toggle(row.code)">
                                    <td>{{ row.code }}</td>
                                    <td>{{ row.name ?? "" }}</td>
                                    <td class="num">
                                        {{ row.etf_count }}
                                        <span v-if="row.new_count" class="muted">
                                            （{{ board === "buys" ? "新進" : "出清" }} {{ row.new_count }}）
                                        </span>
                                    </td>
                                    <td class="num">{{ lots(Math.abs(row.shares)) }}</td>
                                    <td class="num" :class="polarity(row.amount)">{{ toYi(row.amount, 2) }}</td>
                                    <td class="num" :class="polarity(row.opposite_amount)">
                                        {{ row.opposite_count ? `${row.opposite_count} 家 ${toYi(row.opposite_amount, 2)}` : "" }}
                                    </td>
                                    <td class="num" :class="polarity(row.foreign_lots)">{{ signedLots(row.foreign_lots) }}</td>
                                    <td class="num" :class="polarity(row.trust_lots)">{{ signedLots(row.trust_lots) }}</td>
                                    <td class="etf-list">
                                        <span v-for="item in row.etfs" :key="item.etf_code" :title="etfLabel(item.etf_code)">
                                            {{ item.etf_code }}
                                        </span>
                                    </td>
                                </tr>
                                <tr v-if="openCode === row.code" class="detail-row">
                                    <td colspan="9">
                                        <table class="data-table detail-table">
                                            <thead>
                                                <tr>
                                                    <th>ETF</th><th>動作</th>
                                                    <th class="num">股數</th><th class="num">推估金額（億）</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                <tr v-for="item in row.etfs" :key="item.etf_code">
                                                    <td>{{ etfLabel(item.etf_code) }}</td>
                                                    <td :class="polarity(item.shares)">{{ TYPE_LABELS[item.type] }}</td>
                                                    <td class="num" :class="polarity(item.shares)">
                                                        {{ (item.shares > 0 ? "+" : "") + item.shares.toLocaleString() }}
                                                    </td>
                                                    <td class="num" :class="polarity(item.amount)">{{ toYi(item.amount, 2) }}</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
            </template>

            <div v-else class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>名稱</th><th>類股</th>
                            <th class="num">幾家持有</th>
                            <th class="num">合計張數</th>
                            <th class="num">市值（億）</th>
                            <th class="num">外資（張）</th>
                            <th class="num">投信（張）</th>
                            <th>ETF</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!visibleCrowded.length" class="empty-row">
                            <td colspan="9">無資料</td>
                        </tr>
                        <tr v-for="row in visibleCrowded" :key="row.code">
                            <td>{{ row.code }}</td>
                            <td>{{ row.name ?? "" }}</td>
                            <td>{{ row.industry ?? "" }}</td>
                            <td class="num">
                                {{ row.holders }}
                                <span v-if="holderChange(row)" :class="polarity(row.holders - row.prev_holders)">
                                    （{{ holderChange(row) }}）
                                </span>
                            </td>
                            <td class="num">{{ lots(row.shares) }}</td>
                            <td class="num">{{ row.market_value === null ? "--" : (row.market_value / YI).toFixed(1) }}</td>
                            <td class="num" :class="polarity(row.foreign_lots)">{{ signedLots(row.foreign_lots) }}</td>
                            <td class="num" :class="polarity(row.trust_lots)">{{ signedLots(row.trust_lots) }}</td>
                            <td class="etf-list">
                                <span v-for="code in row.etfs" :key="code" :title="etfLabel(code)">{{ code }}</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div v-if="totalRows > COLLAPSED_ROWS" class="more-wrap">
                <button type="button" class="chip" @click="expanded = !expanded">
                    {{ expanded ? `收合為前 ${COLLAPSED_ROWS} 名` : `展開全部 ${totalRows} 名` }}
                </button>
            </div>

            <p class="panel-note daily-foot">
                <template v-if="board !== 'crowded'">
                    「ETF 張數」「推估金額」為主動式 ETF 的持股變化，點選列可看各檔 ETF 的明細；
                </template>
                外資、投信為全市場買賣超張數，「投信」包含所有投信，不只主動式 ETF，兩者不可加總。
                金額以當日 VWAP 推估，未扣除申購贖回造成的被動買賣。
            </p>
        </section>
    </section>
</template>

<style scoped>
.daily-notice {
    margin-bottom: 16px;
}

.daily-tiles {
    margin-bottom: 16px;
}

.clickable {
    cursor: pointer;
}

.is-selected td {
    background: var(--neutral);
    font-weight: 600;
}

.muted {
    color: var(--text-secondary);
    font-size: 12px;
}

.etf-list {
    color: var(--text-secondary);
    font-size: 12px;
}

.etf-list span + span {
    margin-left: 6px;
}

.detail-row > td {
    padding: 8px 12px 12px 32px;
    background: var(--surface-0);
}

.detail-table {
    width: auto;
    min-width: 420px;
}

.more-wrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
}

.daily-foot {
    margin-top: 12px;
}
</style>
