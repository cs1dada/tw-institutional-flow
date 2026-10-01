<script setup lang="ts">
/**
 * 主動式 ETF 動向。
 *
 * 兩件不同的事放在同一頁：ETF 自己被法人買賣的情形 (來自當日資料)，
 * 以及這些 ETF 持有哪些股票 (來自各投信的持股快照)。
 * 經理人成本區塊由持股快照推估各 ETF 的買進價位，方法見 notes/ETF_STRATEGY.md。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadDay, loadEtf, loadEtfCost, loadEtfCostDetail, loadMeta } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import EtfCostChart from "@/components/EtfCostChart.vue"
import type {
    DateItem,
    DayData,
    EtfCostDetail,
    EtfCostItem,
    EtfCostSummary,
    EtfData,
    EtfTopStock,
    Investor,
    StockFlow,
} from "@/types"
import { INVESTOR_LABELS, etfFlowList, expandStocks, marketNote } from "@/utils/flow"
import { YI, formatDate, toYi } from "@/utils/format"
import { colors } from "@/utils/theme"

const TOP_CHART_ROWS = 15
// 經理人成本表格的列數上限，搜尋時不受限
const COST_TABLE_ROWS = 60

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
    return formatDate(day.value.date)
})

/* ===== 經理人成本 ===== */

const cost = ref<EtfCostSummary | null>(null)
const costCode = ref<string | null>(null)
const costDetail = ref<EtfCostDetail | null>(null)
const costHighlight = ref<string | null>(null)
const costQuery = ref("")
const costError = ref<string | null>(null)

const costLatest = computed(() => cost.value?.daily.at(-1) ?? null)

const costNote = computed(() => {
    if (!cost.value) {
        return costError.value ? `載入失敗：${costError.value}` : "載入中"
    }
    return `近 ${cost.value.days} 個交易日（${formatDate(cost.value.start)} ~ ${formatDate(cost.value.date)}），`
        + `${cost.value.etfs.length} 檔以台股為主的 ETF。買賣價以當日 VWAP 推估，`
        + "第一個快照之前的庫存以當日收盤價為成本，未扣除申購贖回造成的被動買賣"
})

const costRows = computed<EtfCostItem[]>(() => {
    const items = cost.value?.items ?? []
    const query = costQuery.value.trim()
    if (!query) {
        return items.slice(0, COST_TABLE_ROWS)
    }
    return items.filter((row) => row.code.includes(query) || (row.name ?? "").includes(query))
})

const costCurrent = computed(() => cost.value?.items.find((row) => row.code === costCode.value) ?? null)

/** 收盤價相對資金加權共識價的距離 (%) */
function premium(row: EtfCostItem): number | null {
    if (row.close === null || !row.weighted) {
        return null
    }
    return (row.close / row.weighted - 1) * 100
}

function premiumText(row: EtfCostItem): string {
    const value = premium(row)
    return value === null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`
}

function fixed(value: number | null | undefined, digits = 2): string {
    return value === null || value === undefined ? "--" : value.toFixed(digits)
}

function lots(shares: number): string {
    return Math.round(shares / 1000).toLocaleString()
}

/** 有買進的 ETF 依均價排序，給強調選單用 */
const costBuyers = computed(() => {
    const avg = costDetail.value?.consensus?.buyer_avg ?? {}
    return Object.entries(avg).sort((a, b) => a[1] - b[1])
})

async function selectCost(code: string) {
    costCode.value = code
    costHighlight.value = null
    try {
        costDetail.value = await loadEtfCostDetail(code)
    } catch (err) {
        costError.value = (err as Error).message
    }
}

async function loadCost() {
    try {
        cost.value = await loadEtfCost()
        const first = cost.value.items[0]
        if (first) {
            await selectCost(first.code)
        }
    } catch (err) {
        costError.value = (err as Error).message
    }
}

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

// 持股變動跟著交易日切換，來自當日資料檔
const allChanges = computed(() => day.value?.etf_changes ?? [])

/** 持股變動要看的 ETF，一次只顯示一檔 */
const changeEtf = ref<string | null>(null)

const changeCounts = computed(() => {
    const counts: Record<string, number> = {}
    for (const row of allChanges.value) {
        counts[row.etf_code] = (counts[row.etf_code] ?? 0) + 1
    }
    return counts
})

const changes = computed(() => allChanges.value.filter((row) => row.etf_code === changeEtf.value))

const changeNote = computed(() => {
    if (!allChanges.value.length) {
        const count = etf.value?.dates?.length ?? 0
        return day.value?.etf_changes
            ? "這個交易日沒有可比對的 ETF 持股快照"
            : `持股變動需要每檔 ETF 各有兩個快照，目前只有 ${count} 個日期的資料，明日再執行一次即可比對`
    }
    const first = changes.value[0]
    if (!first) {
        return "這檔 ETF 截至這個交易日的持股與前一個快照相同，沒有異動"
    }
    const buy = changes.value.reduce((sum, row) => sum + Math.max(row.value_change ?? 0, 0), 0)
    const sell = changes.value.reduce((sum, row) => sum + Math.min(row.value_change ?? 0, 0), 0)
    // 各檔 ETF 的持股基準日不同，因此日期依所選的 ETF 標示
    return `${formatDate(first.date)} 與前一個快照 ${formatDate(first.prev_date)} 相比，共 ${changes.value.length} 筆；`
        + `加碼 ${toYi(buy, 2)} 億、減碼 ${toYi(sell, 2)} 億`
})

function changeOptionLabel(code: string, name: string | null): string {
    const count = changeCounts.value[code] ?? 0
    return `${code} ${name ?? ""}（${count ? `${count} 筆` : "無異動"}）`
}

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
        // 預設顯示規模最大、且有異動的那一檔；之後切換交易日時保留使用者的選擇
        if (!changeEtf.value || !etfData.etfs.some((e) => e.etf_code === changeEtf.value)) {
            const withChanges = new Set((dayData.etf_changes ?? []).map((row) => row.etf_code))
            changeEtf.value = etfData.etfs.find((e) => withChanges.has(e.etf_code))?.etf_code
                ?? etfData.etfs[0]?.etf_code
                ?? null
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
    // 經理人成本與交易日選單無關，獨立載入
    loadCost()
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
        </div>

        <section class="panel" data-nav="經理人成本">
            <div class="panel-head">
                <h2>經理人的成本在哪裡</h2>
                <p class="panel-note">{{ costNote }}</p>
            </div>

            <div v-if="costLatest" class="quote-grid cost-tiles">
                <div class="quote-card">
                    <div class="quote-name">{{ formatDate(costLatest.date) }} 全體買進</div>
                    <div class="quote-value val-buy">{{ toYi(costLatest.buy_amt, 1) }} 億</div>
                </div>
                <div class="quote-card">
                    <div class="quote-name">{{ formatDate(costLatest.date) }} 全體賣出</div>
                    <div class="quote-value val-sell">{{ toYi(-costLatest.sell_amt, 1) }} 億</div>
                </div>
                <div class="quote-card">
                    <div class="quote-name">淨買賣</div>
                    <div
                        class="quote-value"
                        :class="costLatest.buy_amt >= costLatest.sell_amt ? 'val-buy' : 'val-sell'"
                    >
                        {{ toYi(costLatest.buy_amt - costLatest.sell_amt, 1) }} 億
                    </div>
                </div>
            </div>

            <template v-if="costDetail && costCurrent">
                <p class="table-title cost-title">
                    {{ costCurrent.code }} {{ costCurrent.name ?? "" }}　收盤 {{ fixed(costCurrent.close) }}
                    　{{ costCurrent.buyers }} 家出手、{{ costCurrent.buy_count }} 筆買進、
                    合計 {{ lots(costCurrent.buy_shares) }} 張；
                    等權共識 {{ fixed(costCurrent.equal) }}，資金加權 {{ fixed(costCurrent.weighted) }}，
                    價帶 {{ costCurrent.band ? `${fixed(costCurrent.band[0])} ~ ${fixed(costCurrent.band[1])}` : "--" }}
                </p>
                <div v-if="costBuyers.length" class="controls controls-inline">
                    <span class="control-label">強調 ETF</span>
                    <button
                        type="button"
                        class="chip"
                        :class="{ 'is-active': costHighlight === null }"
                        @click="costHighlight = null"
                    >
                        不強調
                    </button>
                    <button
                        v-for="[code, avg] in costBuyers"
                        :key="code"
                        type="button"
                        class="chip"
                        :class="{ 'is-active': costHighlight === code }"
                        @click="costHighlight = code"
                    >
                        {{ code }}　均價 {{ fixed(avg) }}
                    </button>
                </div>
                <EtfCostChart :detail="costDetail" :highlight="costHighlight" />
                <p class="panel-note">
                    灰色細線為各 ETF 的持倉成本，點選上方 ETF 可單獨上色；橘色底色為共識價帶 (各家買進均價的 25% 到 75% 分位)。
                    <template v-if="costDetail.events.length">
                        垂直虛線標示偵測到的分割或股票股利，之前的股價與成本已依倍率還原。
                    </template>
                </p>
            </template>

            <div class="controls controls-inline">
                <label class="control">
                    <span class="control-label">搜尋個股</span>
                    <input v-model="costQuery" type="search" class="cost-search" placeholder="代號或名稱" />
                </label>
                <span class="panel-note">依觀察期間的買進金額排序，點選列可切換上方的圖</span>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>名稱</th>
                            <th class="num">收盤</th><th class="num">等權共識</th>
                            <th class="num">資金加權</th><th class="num">價帶</th>
                            <th class="num">距加權共識</th><th class="num">持倉成本</th>
                            <th class="num">出手 / 持有</th><th class="num">買進張數</th>
                            <th class="num">買進（億）</th><th class="num">賣出（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!costRows.length" class="empty-row">
                            <td colspan="12">無資料</td>
                        </tr>
                        <tr
                            v-for="row in costRows"
                            :key="row.code"
                            class="clickable"
                            :class="{ 'is-selected': row.code === costCode }"
                            @click="selectCost(row.code)"
                        >
                            <td>{{ row.code }}</td>
                            <td>{{ row.name ?? "" }}</td>
                            <td class="num">{{ fixed(row.close) }}</td>
                            <td class="num">{{ fixed(row.equal) }}</td>
                            <td class="num">{{ fixed(row.weighted) }}</td>
                            <td class="num">{{ row.band ? `${fixed(row.band[0], 0)} ~ ${fixed(row.band[1], 0)}` : "--" }}</td>
                            <td class="num" :class="(premium(row) ?? 0) >= 0 ? 'val-buy' : 'val-sell'">
                                {{ premiumText(row) }}
                            </td>
                            <td class="num">{{ fixed(row.cost) }}</td>
                            <td class="num">{{ row.buyers }} / {{ row.holders }}</td>
                            <td class="num">{{ lots(row.buy_shares) }}</td>
                            <td class="num val-buy">{{ toYi(row.buy_amt, 2) }}</td>
                            <td class="num val-sell">{{ toYi(-row.sell_amt, 2) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel" data-nav="持股變動">
            <div class="panel-head">
                <h2>ETF 持股變動</h2>
                <p class="panel-note">{{ changeNote }}</p>
            </div>
            <div v-if="etfs.length" class="controls controls-inline">
                <label class="control">
                    <span class="control-label">ETF</span>
                    <select v-model="changeEtf">
                        <option v-for="item in etfs" :key="item.etf_code" :value="item.etf_code">
                            {{ changeOptionLabel(item.etf_code, item.etf_name) }}
                        </option>
                    </select>
                </label>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>個股</th><th>異動</th>
                            <th class="num">前一日股數</th><th class="num">當日股數</th>
                            <th class="num">股數變動</th><th class="num">估算金額（億）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!changes.length" class="empty-row">
                            <td colspan="7">無異動</td>
                        </tr>
                        <tr
                            v-for="row in changes"
                            :key="row.stock_code"
                        >
                            <td>{{ row.stock_code }}</td>
                            <td>{{ row.stock_name ?? "" }}</td>
                            <td :class="row.share_change >= 0 ? 'val-buy' : 'val-sell'">
                                {{ CHANGE_LABELS[row.change_type] ?? row.change_type }}
                            </td>
                            <td class="num">{{ row.prev_shares.toLocaleString() }}</td>
                            <td class="num">{{ row.shares.toLocaleString() }}</td>
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

        <section class="panel" data-nav="合計持股">
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

        <section class="panel" data-nav="法人買賣超">
            <div class="panel-head">
                <h2>ETF 的法人買賣超</h2>
                <p class="panel-note">{{ flowNote }}</p>
            </div>
            <!-- 法人別只影響這個區塊，其他區塊的資料來自投信揭露的持股，沒有法人之分 -->
            <div class="controls controls-inline">
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

        <section class="panel" data-nav="持股明細">
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

<style scoped>
.cost-tiles {
    margin-bottom: 16px;
}

.cost-title {
    color: var(--text-primary);
    font-weight: 400;
}

.cost-search {
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-1);
    color: var(--text-primary);
    font: inherit;
}

.clickable {
    cursor: pointer;
}

.is-selected td {
    background: var(--neutral);
    font-weight: 600;
}
</style>
