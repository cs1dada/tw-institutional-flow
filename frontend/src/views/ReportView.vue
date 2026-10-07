<script setup lang="ts">
/**
 * 主動式 ETF 日報：訊號有多強、誰出手最準。
 *
 * 統計區的 7 個指標由後端計算，並同時提供申購贖回校正前後兩組數字；
 * 深度解讀是另外撰寫的 Markdown 檔，有檔案的日子才顯示。
 * 方法見 notes/ETF_STRATEGY.md 第三節。
 */
import { computed, onMounted, ref, watch } from "vue"

import { loadEtfReport, loadEtfReportDates } from "@/api/dataSource"
import BarChart from "@/components/BarChart.vue"
import ReportStockTable from "@/components/ReportStockTable.vue"
import type {
    EtfReportData,
    EtfReportDateItem,
    EtfReportGrade,
    EtfReportIndustryRow,
    EtfReportMode,
    EtfReportPositionRow,
    EtfReportStockRow,
} from "@/types"
import { formatDate } from "@/utils/format"
import { renderMarkdown } from "@/utils/markdown"

type Mode = "adjusted" | "raw"

const MODE_LABELS: Record<Mode, string> = {
    adjusted: "扣除申購贖回",
    raw: "原始持股變化",
}

const GRADE_NOTES: Record<EtfReportGrade, string> = {
    sync_sell: "多家同步減碼，警戒等級高於任何買超",
    broad: "家數與金額兼具，最強的買方訊號",
    concentrated: "金額大但家數少，取決於單一經理人的續航力",
    heavy_sell: "少數經理人大額調節",
    quiet: "多家同步加碼，但金額不大",
}

// 預設顯示的筆數，其餘收在「展開全部」
const COLLAPSED_ROWS = 10

const dates = ref<EtfReportDateItem[]>([])
const selectedDate = ref("")
const report = ref<EtfReportData | null>(null)
const mode = ref<Mode>("adjusted")
const flowTab = ref<"buys" | "sells">("buys")
const consensusTab = ref<"buys" | "sells">("buys")
const tempTab = ref<"warming" | "cooling">("warming")
const expanded = ref<Record<string, boolean>>({})
const error = ref<string | null>(null)

const data = computed<EtfReportMode | null>(() => report.value?.modes[mode.value] ?? null)

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    return report.value ? formatDate(report.value.date) : "載入中"
})

const etfNames = computed(() => {
    const names: Record<string, string> = {}
    for (const item of report.value?.etfs ?? []) {
        names[item.etf_code] = item.etf_name ?? ""
    }
    return names
})

const reportedEtfs = computed(() => report.value?.etfs.filter((e) => e.reported) ?? [])
const missingEtfs = computed(() => report.value?.etfs.filter((e) => !e.reported) ?? [])
const passiveEtfs = computed(() => reportedEtfs.value.filter((e) => e.passive_factor !== 1))
const passiveTotal = computed(() => passiveEtfs.value.reduce((sum, e) => sum + (e.passive_amt ?? 0), 0))

const noteHtml = computed(() => (report.value?.note ? renderMarkdown(report.value.note) : ""))

const bigAmount = computed(() => report.value?.thresholds.big_amount_yi ?? 3)
const consensusCount = computed(() => report.value?.thresholds.consensus_count ?? 3)

const flowRows = computed(() => (flowTab.value === "buys" ? data.value?.top_buys : data.value?.top_sells) ?? [])
const consensusRows = computed(
    () => (consensusTab.value === "buys" ? data.value?.consensus_buys : data.value?.consensus_sells) ?? [],
)
const tempRows = computed(() => (tempTab.value === "warming" ? data.value?.warming : data.value?.cooling) ?? [])

/** 族群圖只畫淨額最大與最小的幾個，其餘在表格 */
const industryChartRows = computed(() => {
    const rows = data.value?.industries.filter((r) => r.net_amt) ?? []
    if (rows.length <= 16) {
        return rows
    }
    return [...rows.slice(0, 8), ...rows.slice(-8)]
})

/** 族群表格依淨額絕對值排序，收合時先看到規模最大的流入與流出 */
const industryTableRows = computed(() =>
    (data.value?.industries ?? []).slice().sort((a, b) => Math.abs(b.net_amt) - Math.abs(a.net_amt)),
)

function limited<T>(key: string, rows: T[]): T[] {
    return expanded.value[key] ? rows : rows.slice(0, COLLAPSED_ROWS)
}

function toggleExpand(key: string) {
    expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

function yi(value: number, digits = 2): string {
    return (value > 0 ? "+" : "") + value.toFixed(digits)
}

function polarity(value: number | null | undefined): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

function etfLabel(code: string): string {
    return `${code} ${etfNames.value[code] ?? ""}`
}

function stockName(row: { code: string; name: string | null }): string {
    return row.name ? `${row.name} (${row.code})` : row.code
}

function joinNames(rows: { code: string; name: string | null }[], limit = 3): string {
    return rows.slice(0, limit).map(stockName).join("、")
}

/* ===== 各區塊的一句話摘要，由統計結果直接組出 ===== */

const signalSummary = computed(() => {
    const signals = data.value?.signals ?? []
    if (!signals.length) {
        return "今天沒有達到分級門檻的訊號。"
    }
    const parts: string[] = []
    for (const grade of ["sync_sell", "broad", "concentrated"] as EtfReportGrade[]) {
        const rows = signals.filter((r) => r.grade === grade)
        if (rows.length) {
            parts.push(`${report.value?.grades[grade]} ${rows.length} 檔 (${joinNames(rows)})`)
        }
    }
    return parts.length ? parts.join("；") + "。" : "只有小額共識或集中調節，沒有強訊號。"
})

const flowSummary = computed(() => {
    const top = flowRows.value[0]
    if (!top) {
        return ""
    }
    const amount = flowTab.value === "buys" ? top.buy_amt : top.sell_amt
    const count = flowTab.value === "buys" ? top.buy_count : top.sell_count
    const verb = flowTab.value === "buys" ? "加碼" : "減碼"
    return `${stockName(top)} 被 ${count} 家${verb} ${yi(amount)} 億，居今日之冠。`
})

const consensusSummary = computed(() => {
    const rows = consensusRows.value
    const verb = consensusTab.value === "buys" ? "加碼" : "減碼"
    if (!rows.length) {
        return `沒有被 ${consensusCount.value} 家以上同時${verb}的個股。`
    }
    const top = rows[0]
    const count = consensusTab.value === "buys" ? top.buy_count : top.sell_count
    return `共 ${rows.length} 檔被 ${consensusCount.value} 家以上同時${verb}，家數最多的是 ${stockName(top)} (${count} 家)。`
})

const industrySummary = computed(() => {
    const rows = data.value?.industries ?? []
    const inflow = rows.filter((r) => r.net_amt > 0).slice(0, 2)
    const outflow = rows.filter((r) => r.net_amt < 0).slice(-2).reverse()
    const fmt = (r: EtfReportIndustryRow) => `${r.industry} ${yi(r.net_amt, 1)} 億`
    const parts = []
    if (inflow.length) {
        parts.push(`流入 ${inflow.map(fmt).join("、")}`)
    }
    if (outflow.length) {
        parts.push(`流出 ${outflow.map(fmt).join("、")}`)
    }
    return parts.length ? parts.join("；") + "。" : ""
})

const tempSummary = computed(() => {
    const rows = tempRows.value
    if (!report.value?.prev_date) {
        return "沒有前一個揭露日可比較。"
    }
    if (!rows.length) {
        return tempTab.value === "warming" ? "沒有加碼家數明顯增加的個股。" : "沒有加碼家數明顯減少的個股。"
    }
    const top = rows[0]
    return `${stockName(top)} 加碼家數 ${top.prev_buy_count}→${top.buy_count}，`
        + `與 ${formatDate(report.value.prev_date)} 相比${tempTab.value === "warming" ? "升溫最多" : "退潮最多"}。`
})

const positionSummary = computed(() => {
    if (!data.value) {
        return ""
    }
    return `新進 ${data.value.new_count} 筆、清倉 ${data.value.exit_count} 筆。`
})

const accuracySummary = computed(() => {
    const acc = data.value?.accuracy
    const best = acc?.items[0]
    if (!acc || !best) {
        return ""
    }
    return `${formatDate(acc.from)} 起 ${acc.days} 個揭露日，${best.etf_code} ${best.etf_name ?? ""} `
        + `買進的部位以金額加權報酬 ${yi(best.return_pct)}% 最高。短期手感不代表長期選股能力。`
})

function positionKey(row: EtfReportPositionRow): string {
    return `${row.etf_code}-${row.code}`
}

function industryTooltip(row: EtfReportIndustryRow): string {
    const leaders = row.leaders.map((l) => `${l.name ?? l.code} ${yi(l.net_amt)}`).join("<br>")
    return `<strong>${row.industry}</strong><br>`
        + `淨額　${yi(row.net_amt)} 億<br>`
        + `加碼　${yi(row.buy_amt)} 億<br>`
        + `減碼　${yi(row.sell_amt)} 億<br>`
        + leaders
}

function gradeOf(row: EtfReportStockRow): string {
    return row.grade ? report.value?.grades[row.grade] ?? "" : ""
}

function dateLabel(item: EtfReportDateItem): string {
    const note = item.reported < item.listed ? `（已公布 ${item.reported}/${item.listed} 檔）` : ""
    return formatDate(item.date) + note + (item.has_note ? "  解讀" : "")
}

async function load(date: string) {
    error.value = null
    try {
        report.value = await loadEtfReport(date)
        selectedDate.value = report.value.date
        expanded.value = {}
    } catch (err) {
        error.value = (err as Error).message
    }
}

watch(selectedDate, (date) => {
    if (date && date !== report.value?.date) {
        load(date)
    }
})

onMounted(async () => {
    try {
        dates.value = (await loadEtfReportDates()).dates
        // 預設顯示最近一個全部公布的日子，盤後陸續公布期間不會先看到不完整的日報
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
                <h1>ETF 日報</h1>
                <p class="subtitle">
                    訊號有多強、誰出手最準：以金額 × 家數為訊號分級，並扣除申購贖回造成的被動買賣
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
            <div class="tabs" role="tablist">
                <button
                    v-for="(label, key) in MODE_LABELS"
                    :key="key"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': mode === key }"
                    role="tab"
                    @click="mode = key as Mode"
                >
                    {{ label }}
                </button>
            </div>
        </div>

        <p v-if="missingEtfs.length" class="notice report-gap">
            已公布 {{ reportedEtfs.length }}/{{ report?.etfs.length }} 檔，未含
            {{ missingEtfs.map((e) => e.etf_code).join("、") }}。這是暫時的日報，資料進來後重新整理即可更新
        </p>

        <div v-if="data" class="quote-grid report-gap">
            <div class="quote-card">
                <div class="quote-name">全體加碼</div>
                <div class="quote-value val-buy">{{ yi(data.buy_amt, 1) }} 億</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">全體減碼</div>
                <div class="quote-value val-sell">{{ yi(data.sell_amt, 1) }} 億</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">淨額</div>
                <div class="quote-value" :class="polarity(data.net_amt)">{{ yi(data.net_amt, 1) }} 億</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">申購贖回的被動買賣</div>
                <div class="quote-value" :class="polarity(passiveTotal)">{{ yi(passiveTotal, 1) }} 億</div>
                <div class="quote-meta">
                    {{ passiveEtfs.length ? `${passiveEtfs.map((e) => e.etf_code).join("、")} 持股整批同比例變動` : "今天沒有 ETF 整批同比例調整持股" }}
                </div>
            </div>
        </div>

        <section v-if="report" class="panel" data-nav="深度解讀">
            <div class="panel-head">
                <h2>深度解讀</h2>
                <p class="panel-note">依當日統計撰寫的解讀，著重共識強弱、族群輪動與隔日驗證點</p>
            </div>
            <!-- eslint-disable-next-line vue/no-v-html -- 內容已在 renderMarkdown 跳脫 -->
            <div v-if="noteHtml" class="note-body" v-html="noteHtml" />
            <p v-else class="notice">這一天還沒有深度解讀，只提供下方的統計區。</p>
        </section>

        <template v-if="data && report">
            <section class="panel" data-nav="訊號強度">
                <div class="panel-head">
                    <h2>訊號強度：金額 × 家數</h2>
                    <p class="panel-note">
                        金額大為單日 {{ bigAmount }} 億以上，家數多為 {{ consensusCount }} 家以上。家數比金額重要，賣方共識比買方共識更值得注意
                    </p>
                </div>
                <p class="summary">{{ signalSummary }}</p>
                <ReportStockTable :rows="limited('signals', data.signals)" :etf-label="etfLabel" extra-head="分級">
                    <template #extra="{ row }">
                        <span class="grade" :class="`grade-${row.grade}`" :title="row.grade ? GRADE_NOTES[row.grade] : ''">
                            {{ gradeOf(row) }}
                        </span>
                    </template>
                </ReportStockTable>
                <div v-if="data.signals.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('signals')">
                        {{ expanded.signals ? "收合" : `展開全部 ${data.signals.length} 檔` }}
                    </button>
                </div>
                <ul class="legend">
                    <li v-for="grade in (['sync_sell', 'broad', 'concentrated', 'heavy_sell', 'quiet'] as EtfReportGrade[])" :key="grade">
                        <span class="grade" :class="`grade-${grade}`">{{ report.grades[grade] }}</span>
                        {{ GRADE_NOTES[grade] }}
                    </li>
                </ul>
            </section>

            <section class="panel" data-nav="被買最兇">
                <div class="panel-head">
                    <h2>{{ flowTab === "buys" ? "被買最兇" : "被調節最重" }}</h2>
                    <p class="panel-note">各股當日加碼或減碼金額排名，同一檔可能同時有人買有人賣</p>
                </div>
                <div class="controls controls-inline">
                    <div class="tabs" role="tablist">
                        <button type="button" class="tab" :class="{ 'is-active': flowTab === 'buys' }" @click="flowTab = 'buys'">被買最兇</button>
                        <button type="button" class="tab" :class="{ 'is-active': flowTab === 'sells' }" @click="flowTab = 'sells'">被調節最重</button>
                    </div>
                </div>
                <p class="summary">{{ flowSummary }}</p>
                <ReportStockTable :rows="limited('flow', flowRows)" :etf-label="etfLabel" />
                <div v-if="flowRows.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('flow')">
                        {{ expanded.flow ? "收合" : `展開全部 ${flowRows.length} 檔` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="有志一同">
                <div class="panel-head">
                    <h2>{{ consensusTab === "buys" ? "有志一同" : "集體減碼" }}</h2>
                    <p class="panel-note">同一天被 {{ consensusCount }} 家以上加碼 (含新進) 或減碼 (含出清) 的個股</p>
                </div>
                <div class="controls controls-inline">
                    <div class="tabs" role="tablist">
                        <button type="button" class="tab" :class="{ 'is-active': consensusTab === 'buys' }" @click="consensusTab = 'buys'">有志一同</button>
                        <button type="button" class="tab" :class="{ 'is-active': consensusTab === 'sells' }" @click="consensusTab = 'sells'">集體減碼</button>
                    </div>
                </div>
                <p class="summary">{{ consensusSummary }}</p>
                <ReportStockTable :rows="limited('consensus', consensusRows)" :etf-label="etfLabel" />
                <div v-if="consensusRows.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('consensus')">
                        {{ expanded.consensus ? "收合" : `展開全部 ${consensusRows.length} 檔` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="族群流向">
                <div class="panel-head">
                    <h2>資金往哪個族群跑</h2>
                    <p class="panel-note">依證交所產業別加總主動式 ETF 的淨買賣，尚無散熱、網通等細分類</p>
                </div>
                <p class="summary">{{ industrySummary }}</p>
                <div class="chart-scroll">
                    <BarChart
                        v-if="industryChartRows.length"
                        :rows="industryChartRows"
                        :name-of="(row: EtfReportIndustryRow) => row.industry"
                        :value-of="(row: EtfReportIndustryRow) => row.net_amt"
                        :tooltip="industryTooltip"
                        :label-width="130"
                    />
                </div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>產業</th>
                                <th class="num">檔數</th>
                                <th class="num">加碼（億）</th>
                                <th class="num">減碼（億）</th>
                                <th class="num">淨額（億）</th>
                                <th>主要個股</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in limited('industries', industryTableRows)" :key="row.industry">
                                <td>{{ row.industry }}</td>
                                <td class="num">{{ row.stock_count }}</td>
                                <td class="num val-buy">{{ row.buy_amt ? yi(row.buy_amt) : "" }}</td>
                                <td class="num val-sell">{{ row.sell_amt ? yi(row.sell_amt) : "" }}</td>
                                <td class="num" :class="polarity(row.net_amt)">{{ yi(row.net_amt) }}</td>
                                <td class="leaders">
                                    <span v-for="l in row.leaders" :key="l.code" :class="polarity(l.net_amt)">
                                        {{ l.name ?? l.code }} {{ yi(l.net_amt) }}
                                    </span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div v-if="data.industries.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('industries')">
                        {{ expanded.industries ? "收合" : `展開全部 ${data.industries.length} 個產業` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="共識升溫退潮">
                <div class="panel-head">
                    <h2>共識{{ tempTab === "warming" ? "升溫" : "退潮" }}</h2>
                    <p class="panel-note">
                        加碼家數與前一個揭露日{{ report.prev_date ? ` (${formatDate(report.prev_date)})` : "" }}比較，
                        變化 2 家以上、或由 0 升到 {{ consensusCount }} 家以上、由 {{ consensusCount }} 家以上降到 0。看變化不看存量
                    </p>
                </div>
                <div class="controls controls-inline">
                    <div class="tabs" role="tablist">
                        <button type="button" class="tab" :class="{ 'is-active': tempTab === 'warming' }" @click="tempTab = 'warming'">升溫</button>
                        <button type="button" class="tab" :class="{ 'is-active': tempTab === 'cooling' }" @click="tempTab = 'cooling'">退潮</button>
                    </div>
                </div>
                <p class="summary">{{ tempSummary }}</p>
                <ReportStockTable :rows="limited('temp', tempRows)" :etf-label="etfLabel" extra-head="加碼家數">
                    <template #extra="{ row }">
                        <span :class="polarity(row.diff)">{{ row.prev_buy_count }}→{{ row.buy_count }}</span>
                    </template>
                </ReportStockTable>
                <div v-if="tempRows.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('temp')">
                        {{ expanded.temp ? "收合" : `展開全部 ${tempRows.length} 檔` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="新進與清倉">
                <div class="panel-head">
                    <h2>新進與清倉</h2>
                    <p class="panel-note">持股從 0 變有、從有變 0，代表經理人態度的轉變</p>
                </div>
                <p class="summary">{{ positionSummary }}</p>
                <div class="pair-grid">
                    <div v-for="side in (['new_positions', 'exits'] as const)" :key="side" class="table-wrap">
                        <div class="table-title">{{ side === "new_positions" ? `新進 ${data.new_count} 筆` : `清倉 ${data.exit_count} 筆` }}</div>
                        <table class="data-table">
                            <thead>
                                <tr><th>個股</th><th>ETF</th><th class="num">張數</th><th class="num">金額（億）</th></tr>
                            </thead>
                            <tbody>
                                <tr v-if="!data[side].length" class="empty-row"><td colspan="4">無資料</td></tr>
                                <tr v-for="row in data[side]" :key="positionKey(row)">
                                    <td>{{ stockName(row) }}</td>
                                    <td :title="etfLabel(row.etf_code)">{{ row.etf_code }}</td>
                                    <td class="num">{{ Math.abs(row.lots).toLocaleString() }}</td>
                                    <td class="num" :class="polarity(row.amt)">{{ yi(row.amt) }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>

            <section class="panel" data-nav="誰出手最準">
                <div class="panel-head">
                    <h2>誰出手最準</h2>
                    <p class="panel-note">
                        近 {{ data.accuracy.days }} 個揭露日各 ETF 的買進，以當日 VWAP 為成本、{{ formatDate(report.date) }} 收盤計算的金額加權報酬
                    </p>
                </div>
                <p class="summary">{{ accuracySummary }}</p>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ETF</th>
                                <th class="num">報酬（%）</th>
                                <th class="num">買進（億）</th>
                                <th class="num">檔數</th>
                                <th>買最多的個股</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-if="!data.accuracy.items.length" class="empty-row"><td colspan="5">無資料</td></tr>
                            <tr v-for="row in data.accuracy.items" :key="row.etf_code">
                                <td>{{ row.etf_code }} {{ row.etf_name ?? "" }}</td>
                                <td class="num" :class="polarity(row.return_pct)">{{ yi(row.return_pct) }}</td>
                                <td class="num">{{ row.buy_amt.toFixed(2) }}</td>
                                <td class="num">{{ row.stock_count }}</td>
                                <td class="leaders">
                                    <span v-for="s in row.top_stocks" :key="s.code">{{ s.name ?? s.code }} {{ s.amt.toFixed(2) }}</span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <section class="panel" data-nav="申購贖回">
                <div class="panel-head">
                    <h2>申購贖回校正</h2>
                    <p class="panel-note">
                        持股整批同比例變動 1% 以上時，以共同持股的股數倍率中位數為被動倍率，扣除後才是經理人的主動調整。
                        發行單位數變動當天持股多半沒有同步變動 (申購多以現金交付)，因此不直接以單位數倍率扣除，僅列出供參考
                    </p>
                </div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ETF</th>
                                <th>比對日</th>
                                <th class="num">單位數變化（%）</th>
                                <th class="num">被動倍率</th>
                                <th class="num">原始淨額（億）</th>
                                <th class="num">被動（億）</th>
                                <th class="num">主動淨額（億）</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in report.etfs" :key="row.etf_code" :class="{ 'is-passive': row.passive_factor !== undefined && row.passive_factor !== 1 }">
                                <td>{{ row.etf_code }} {{ row.etf_name ?? "" }}</td>
                                <template v-if="row.reported">
                                    <td>{{ formatDate(row.prev_date) }}</td>
                                    <td class="num" :class="polarity(row.unit_change_pct)">
                                        {{ row.unit_change_pct === null || row.unit_change_pct === undefined ? "--" : yi(row.unit_change_pct) }}
                                    </td>
                                    <td class="num">{{ row.passive_factor === 1 ? "" : row.passive_factor?.toFixed(4) }}</td>
                                    <td class="num" :class="polarity(row.raw_net_amt)">{{ yi(row.raw_net_amt ?? 0) }}</td>
                                    <td class="num" :class="polarity(row.passive_amt)">{{ row.passive_amt ? yi(row.passive_amt) : "" }}</td>
                                    <td class="num" :class="polarity(row.active_net_amt)">{{ yi(row.active_net_amt ?? 0) }}</td>
                                </template>
                                <td v-else colspan="6" class="muted">當日尚未公布</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <p class="panel-note">
                金額以當日 VWAP 推估，不是實際成交價。只計算以台股為主的主動式 ETF；ETF 漏抓某一天時，下一個揭露日的變動會包含多天的累積。
            </p>
        </template>
    </section>
</template>

<style scoped>
.report-gap {
    margin-bottom: 16px;
}

.summary {
    margin: 0 0 12px;
    color: var(--text-primary);
}

.note-body {
    max-width: 880px;
    line-height: 1.8;
}

.note-body :deep(h3) {
    margin: 20px 0 6px;
    font-size: 15px;
}

.note-body :deep(h3:first-child) {
    margin-top: 0;
}

.note-body :deep(h4) {
    margin: 14px 0 4px;
    font-size: 14px;
}

.note-body :deep(p) {
    margin: 0 0 10px;
}

.note-body :deep(ul),
.note-body :deep(ol) {
    margin: 0 0 10px;
    padding-left: 22px;
}

.note-body :deep(.table-wrap) {
    margin: 0 0 12px;
}

.note-body :deep(blockquote) {
    margin: 16px 0 0;
    padding: 6px 12px;
    border-left: 3px solid var(--border);
    color: var(--text-muted);
    font-size: 12px;
}

.note-body :deep(code) {
    padding: 0 4px;
    border-radius: 3px;
    background: var(--neutral);
    font-size: 13px;
}

.grade {
    display: inline-block;
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 12px;
    white-space: nowrap;
}

/* 分級以文字標示，顏色只是次要編碼 */
.grade-sync_sell,
.grade-heavy_sell {
    border-color: var(--sell);
    color: var(--sell);
}

.grade-broad,
.grade-concentrated {
    border-color: var(--buy);
    color: var(--buy);
}

.grade-broad {
    font-weight: 600;
}

.grade-quiet {
    color: var(--text-secondary);
}

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 18px;
    margin: 12px 0 0;
    padding: 0;
    list-style: none;
    color: var(--text-muted);
    font-size: 12px;
}

.legend .grade {
    margin-right: 4px;
}

.leaders {
    font-size: 12px;
}

.leaders span + span {
    margin-left: 8px;
}

.pair-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
}

.more-wrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
}

.is-passive td {
    background: var(--neutral);
    font-weight: 600;
}

.muted {
    color: var(--text-muted);
}
</style>
