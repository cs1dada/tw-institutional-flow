<script setup lang="ts">
/**
 * 主動式 ETF 累積趨勢：跨週比較，找出經理人默默加碼或減碼的個股與族群。
 *
 * 單日榜單看的是「哪一天被大買」，這一頁看的是每天買一點、從不上榜、
 * 累積起來卻很可觀的部位。窗口、標籤與金額都由後端計算 (app/services/etf_trend.py)，
 * 前端只負責切換與排序。
 */
import { computed, onMounted, ref } from "vue"

import { loadEtfTrend } from "@/api/dataSource"
import type { EtfTrendData, EtfTrendGroup, EtfTrendStock, EtfTrendTag } from "@/types"
import { formatDate, signedPct } from "@/utils/format"

type GroupKind = "theme" | "industry"
type DivergeTab = "contrarian_buy" | "profit_take"

const GROUP_LABELS: Record<GroupKind, string> = {
    theme: "題材分類",
    industry: "產業別",
}

const TAG_NOTES: Record<EtfTrendTag, string> = {
    stealth_buy: "加碼分散在多天、沒有單日大買，累積淨買",
    stealth_sell: "減碼分散在多天、沒有單日大賣，累積淨賣",
    contrarian_buy: "窗口內股價下跌，經理人仍淨買",
    profit_take: "窗口內股價上漲，經理人反而淨賣",
}

// 預設顯示的筆數，其餘收在「展開全部」
const COLLAPSED_ROWS = 15

const trend = ref<EtfTrendData | null>(null)
const weeks = ref("4")
const groupKind = ref<GroupKind>("theme")
const divergeTab = ref<DivergeTab>("contrarian_buy")
const expanded = ref<Record<string, boolean>>({})
const error = ref<string | null>(null)

const win = computed(() => trend.value?.windows[weeks.value] ?? null)
const windowKeys = computed(() => Object.keys(trend.value?.windows ?? {}).sort((a, b) => Number(a) - Number(b)))

const headline = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    return win.value ? `${formatDate(win.value.start)} ～ ${formatDate(win.value.end)}` : "載入中"
})

function tagged(tag: EtfTrendTag): EtfTrendStock[] {
    return win.value?.stocks.filter((row) => row.tags.includes(tag)) ?? []
}

const stealthBuys = computed(() => tagged("stealth_buy").sort((a, b) => b.net_amt - a.net_amt))
const stealthSells = computed(() => tagged("stealth_sell").sort((a, b) => a.net_amt - b.net_amt))
const divergeRows = computed(() => tagged(divergeTab.value).sort((a, b) => Math.abs(b.net_amt) - Math.abs(a.net_amt)))
const groupRows = computed<EtfTrendGroup[]>(() => win.value?.groups[groupKind.value] ?? [])

/** 連續淨買或淨賣的週數，從最近一週往回算 */
function runLength(weekly: number[]): number {
    const last = weekly[weekly.length - 1]
    if (!last) {
        return 0
    }
    let count = 0
    for (let i = weekly.length - 1; i >= 0 && weekly[i] * last > 0; i--) {
        count++
    }
    return last > 0 ? count : -count
}

const groupSummary = computed(() => {
    const rows = groupRows.value
    if (!rows.length || !win.value) {
        return ""
    }
    const total = win.value.weeks
    const steadyBuy = rows.filter((r) => r.buy_weeks === total).map((r) => r.name)
    const steadySell = rows.filter((r) => r.sell_weeks === total).map((r) => r.name)
    const parts = []
    if (steadyBuy.length) {
        parts.push(`連續 ${total} 週淨買：${steadyBuy.join("、")}`)
    }
    if (steadySell.length) {
        parts.push(`連續 ${total} 週淨賣：${steadySell.join("、")}`)
    }
    return parts.length ? `${parts.join("；")}。` : `沒有任何${GROUP_LABELS[groupKind.value]}連續 ${total} 週同方向。`
})

function stockSummary(rows: EtfTrendStock[], side: "buy" | "sell"): string {
    if (!rows.length) {
        return "這個窗口沒有符合條件的個股。"
    }
    const total = rows.reduce((acc, r) => acc + r.net_amt, 0)
    const against = rows.filter((r) => r.change_pct !== null && (side === "buy" ? r.change_pct < 0 : r.change_pct > 0))
    const word = side === "buy" ? "股價下跌仍在買" : "股價上漲仍在賣"
    return `共 ${rows.length} 檔，合計 ${yi(total, 1)} 億；其中 ${against.length} 檔${word}。`
}

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

function etfList(codes: string[]): string {
    const names = trend.value?.etf_names ?? {}
    return codes.map((code) => `${code} ${names[code] ?? ""}`).join("\n")
}

/** 20261028 轉為 10/28 */
function shortDate(date: string): string {
    return `${date.slice(4, 6)}/${date.slice(6, 8)}`
}

function weekLabel(index: number): string {
    const range = win.value?.week_ranges[index]
    return range ? `${shortDate(range.start)}～${shortDate(range.end)}` : ""
}

/** 逐週迷你長條的高度，以該列的最大週為基準；零軸在中線，因此最高只到一半 */
function barHeight(weekly: number[], value: number): string {
    const max = Math.max(...weekly.map(Math.abs))
    return max && value ? `${Math.max(4, (Math.abs(value) / max) * 50)}%` : "0"
}

function weeklyAria(weekly: number[]): string {
    return weekly.map((v, i) => `${weekLabel(i)} ${yi(v)} 億`).join("，")
}

onMounted(async () => {
    try {
        trend.value = await loadEtfTrend()
        if (!trend.value.windows[weeks.value]) {
            weeks.value = Object.keys(trend.value.windows)[0] ?? weeks.value
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
                <h1>主動式 ETF 累積趨勢</h1>
                <p class="subtitle">
                    跨週比較經理人的持股變化，找出每天買一點、從不上單日榜單，累積起來卻很可觀的部位
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <div class="controls">
            <span class="control-label">窗口</span>
            <div class="tabs" role="tablist">
                <button
                    v-for="key in windowKeys"
                    :key="key"
                    type="button"
                    class="tab"
                    :class="{ 'is-active': weeks === key }"
                    role="tab"
                    @click="weeks = key; expanded = {}"
                >
                    {{ key }} 週
                </button>
            </div>
        </div>

        <div v-if="win && trend" class="quote-grid report-gap">
            <div class="quote-card">
                <div class="quote-name">比較區間</div>
                <div class="quote-value">{{ shortDate(win.start) }} ～ {{ shortDate(win.end) }}</div>
                <div class="quote-meta">{{ win.days }} 個揭露日，期初為 {{ formatDate(win.base_date) }} 收盤</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">{{ trend.tags.stealth_buy }}</div>
                <div class="quote-value val-buy">{{ stealthBuys.length }} 檔</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">{{ trend.tags.stealth_sell }}</div>
                <div class="quote-value val-sell">{{ stealthSells.length }} 檔</div>
            </div>
            <div class="quote-card">
                <div class="quote-name">{{ trend.tags.contrarian_buy }} / {{ trend.tags.profit_take }}</div>
                <div class="quote-value">{{ tagged("contrarian_buy").length }} / {{ tagged("profit_take").length }} 檔</div>
            </div>
        </div>

        <template v-if="win && trend">
            <section
                v-for="side in (['buy', 'sell'] as const)"
                :key="side"
                class="panel"
                :data-nav="side === 'buy' ? '默默加碼' : '默默減碼'"
            >
                <div class="panel-head">
                    <h2>{{ side === "buy" ? trend.tags.stealth_buy : trend.tags.stealth_sell }}</h2>
                    <p class="panel-note">
                        窗口內{{ side === "buy" ? "加碼" : "減碼" }}天數至少 {{ Math.round(win.days * trend.thresholds.stealth_min_day_ratio) }} 天，
                        且單日最大佔比低於 {{ Math.round(trend.thresholds.stealth_max_top_share * 100) }}%。佔比越低，代表越分散、越不顯眼
                    </p>
                </div>
                <p class="summary">{{ stockSummary(side === "buy" ? stealthBuys : stealthSells, side) }}</p>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>個股</th>
                                <th class="num">淨額（億）</th>
                                <th>逐週</th>
                                <th class="num">加碼 / 減碼天數</th>
                                <th class="num">單日最大佔比</th>
                                <th class="num">ETF 加碼 / 減碼</th>
                                <th class="num">區間股價</th>
                                <th>標籤</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in limited(side, side === 'buy' ? stealthBuys : stealthSells)" :key="row.code">
                                <td>
                                    <div>{{ row.name ?? row.code }} <span class="muted">{{ row.code }}</span></div>
                                    <div class="muted small">{{ row.industry }}</div>
                                </td>
                                <td class="num" :class="polarity(row.net_amt)">{{ yi(row.net_amt, 1) }}</td>
                                <td>
                                    <div class="spark" role="img" :aria-label="weeklyAria(row.weekly)">
                                        <span
                                            v-for="(v, i) in row.weekly"
                                            :key="i"
                                            class="spark-cell"
                                            :title="`${weekLabel(i)}　${yi(v)} 億`"
                                        >
                                            <span
                                                class="spark-bar"
                                                :class="v > 0 ? 'is-buy' : 'is-sell'"
                                                :style="{ height: barHeight(row.weekly, v) }"
                                            />
                                        </span>
                                    </div>
                                </td>
                                <td class="num">{{ row.buy_days }} / {{ row.sell_days }}</td>
                                <td class="num">{{ row.top_day_share === null ? "--" : `${Math.round(row.top_day_share * 100)}%` }}</td>
                                <td class="num">
                                    <span :title="etfList(row.buyers)">{{ row.buyers.length }}</span>
                                    /
                                    <span :title="etfList(row.sellers)">{{ row.sellers.length }}</span>
                                </td>
                                <td class="num" :class="polarity(row.change_pct)">{{ signedPct(row.change_pct, 1) }}</td>
                                <td>
                                    <span
                                        v-for="tag in row.tags.filter((t) => !t.startsWith('stealth'))"
                                        :key="tag"
                                        class="grade"
                                        :class="`tag-${tag}`"
                                        :title="TAG_NOTES[tag]"
                                    >
                                        {{ trend.tags[tag] }}
                                    </span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div v-if="(side === 'buy' ? stealthBuys : stealthSells).length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand(side)">
                        {{ expanded[side] ? "收合" : `展開全部 ${(side === "buy" ? stealthBuys : stealthSells).length} 檔` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="族群逐週">
                <div class="panel-head">
                    <h2>族群逐週淨額</h2>
                    <p class="panel-note">
                        每週 {{ trend.week_days }} 個揭露日。題材分類一檔股票可同時計入多個題材；
                        只計入窗口淨額 {{ trend.thresholds.min_net_yi }} 億以上的個股
                    </p>
                </div>
                <div class="controls controls-inline">
                    <div class="tabs" role="tablist">
                        <button
                            v-for="(label, key) in GROUP_LABELS"
                            :key="key"
                            type="button"
                            class="tab"
                            :class="{ 'is-active': groupKind === key }"
                            role="tab"
                            @click="groupKind = key as GroupKind"
                        >
                            {{ label }}
                        </button>
                    </div>
                </div>
                <p class="summary">{{ groupSummary }}</p>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>{{ groupKind === "theme" ? "題材" : "產業" }}</th>
                                <th v-for="(_, i) in win.week_ranges" :key="i" class="num">{{ weekLabel(i) }}</th>
                                <th class="num">淨額（億）</th>
                                <th class="num">連續週數</th>
                                <th class="num">買 / 賣檔數</th>
                                <th>主要個股</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in limited('groups', groupRows)" :key="row.name">
                                <td>{{ row.name }}</td>
                                <td v-for="(v, i) in row.weekly" :key="i" class="num" :class="polarity(v)">{{ yi(v, 1) }}</td>
                                <td class="num" :class="polarity(row.net_amt)">{{ yi(row.net_amt, 1) }}</td>
                                <td class="num" :class="polarity(runLength(row.weekly))">
                                    {{ runLength(row.weekly) ? `${runLength(row.weekly) > 0 ? "買" : "賣"} ${Math.abs(runLength(row.weekly))} 週` : "--" }}
                                </td>
                                <td class="num">{{ row.buy_count }} / {{ row.sell_count }}</td>
                                <td class="leaders">
                                    <span v-for="l in row.leaders" :key="l.code" :class="polarity(l.net_amt)">
                                        {{ l.name ?? l.code }} {{ yi(l.net_amt, 1) }}
                                    </span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div v-if="groupRows.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('groups')">
                        {{ expanded.groups ? "收合" : `展開全部 ${groupRows.length} 個` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="價量背離">
                <div class="panel-head">
                    <h2>價量背離：{{ trend.tags[divergeTab] }}</h2>
                    <p class="panel-note">{{ TAG_NOTES[divergeTab] }}。不限加碼天數，依淨額大小排序</p>
                </div>
                <div class="controls controls-inline">
                    <div class="tabs" role="tablist">
                        <button
                            v-for="tab in (['contrarian_buy', 'profit_take'] as DivergeTab[])"
                            :key="tab"
                            type="button"
                            class="tab"
                            :class="{ 'is-active': divergeTab === tab }"
                            role="tab"
                            @click="divergeTab = tab"
                        >
                            {{ trend.tags[tab] }}
                        </button>
                    </div>
                </div>
                <div class="table-wrap">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>個股</th>
                                <th class="num">淨額（億）</th>
                                <th class="num">區間股價</th>
                                <th class="num">加碼 / 減碼天數</th>
                                <th class="num">ETF 加碼 / 減碼</th>
                                <th>題材</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in limited('diverge', divergeRows)" :key="row.code">
                                <td>{{ row.name ?? row.code }} <span class="muted">{{ row.code }}</span></td>
                                <td class="num" :class="polarity(row.net_amt)">{{ yi(row.net_amt, 1) }}</td>
                                <td class="num" :class="polarity(row.change_pct)">{{ signedPct(row.change_pct, 1) }}</td>
                                <td class="num">{{ row.buy_days }} / {{ row.sell_days }}</td>
                                <td class="num">
                                    <span :title="etfList(row.buyers)">{{ row.buyers.length }}</span>
                                    /
                                    <span :title="etfList(row.sellers)">{{ row.sellers.length }}</span>
                                </td>
                                <td class="muted small">{{ row.themes.join("、") }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div v-if="divergeRows.length > COLLAPSED_ROWS" class="more-wrap">
                    <button type="button" class="chip" @click="toggleExpand('diverge')">
                        {{ expanded.diverge ? "收合" : `展開全部 ${divergeRows.length} 檔` }}
                    </button>
                </div>
            </section>

            <section class="panel" data-nav="計算方式">
                <div class="panel-head">
                    <h2>計算方式</h2>
                </div>
                <ul class="method">
                    <li>
                        <strong>淨額</strong>：每週各 ETF 期初與期末持股相比，以共同持股的股數倍率中位數扣除申購贖回造成的整批同比例變動，
                        剩下的股數乘上週末 VWAP，再把各週加總。不直接用發行單位數換算，因為申購多以現金交付，經理人之後才分批買進
                    </li>
                    <li><strong>加碼 / 減碼天數</strong>：窗口內每日 (扣除申購贖回後) 淨加碼、淨減碼的揭露日數</li>
                    <li><strong>單日最大佔比</strong>：與淨額同方向的單日最大金額 ÷ 同方向的每日金額合計</li>
                    <li><strong>ETF 加碼 / 減碼</strong>：窗口內淨加碼、淨減碼的 ETF 檔數，滑過數字可看是哪幾檔</li>
                    <li><strong>區間股價</strong>：期初 (窗口前一個揭露日) 收盤到最新收盤的漲跌幅，已還原分割與減資</li>
                    <li>期初還沒上市的 ETF，建倉不算加碼。持股於盤後揭露，跟單至少晚一天。不構成投資建議</li>
                </ul>
            </section>
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

.spark {
    display: flex;
    align-items: center;
    gap: 2px;
    width: max-content;
    height: 28px;
}

/* 每格上半部畫買超、下半部畫賣超，中線即為零軸 */
.spark-cell {
    position: relative;
    width: 8px;
    height: 100%;
}

.spark-cell::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    border-top: 1px solid var(--border);
}

.spark-bar {
    position: absolute;
    left: 0;
    right: 0;
    border-radius: 1px;
}

.spark-bar.is-buy {
    bottom: 50%;
    background: var(--buy);
}

.spark-bar.is-sell {
    top: 50%;
    background: var(--sell);
}

.grade {
    display: inline-block;
    margin-right: 4px;
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 12px;
    white-space: nowrap;
}

/* 標籤以文字標示，顏色只是次要編碼 */
.tag-contrarian_buy {
    border-color: var(--buy);
    color: var(--buy);
}

.tag-profit_take {
    border-color: var(--sell);
    color: var(--sell);
}

.leaders {
    font-size: 12px;
}

.leaders span + span {
    margin-left: 8px;
}

.more-wrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
}

.method {
    margin: 0;
    padding-left: 20px;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.8;
}

.muted {
    color: var(--text-muted);
}

.small {
    font-size: 12px;
}
</style>
