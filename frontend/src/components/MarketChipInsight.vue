<script setup lang="ts">
/**
 * 大盤籌碼圖下方的摘要與對照表，內容跟著上方選的指標換：
 * 法人看連續買賣超與累計，融券看近期增減，
 * 維持率與 VIX 則列出極端值的日子，對照之後 20 個交易日指數怎麼走。
 * 融資餘額有自己的「相近日」表，在 MarketChipPanel 裡處理，這裡不顯示。
 */
import { computed } from "vue"

import type { ChipRow } from "@/types"
import { formatDate } from "@/utils/format"
import {
    extremeDays,
    forwardPct,
    maintenanceLevel,
    maintenanceLows,
    streak,
    sumLast,
    vixHighs,
    vixLevel,
    type ChipMetric,
    type Point,
} from "@/utils/market"

const props = defineProps<{
    rows: ChipRow[]
    closes: Map<string, number>
    metric: ChipMetric
    metricLabel: string
    marketLabel: string
    indexName: string
    twVix: Map<string, number>
    usVix: Map<string, number>
}>()

/** 對照極端值之後的指數走勢，取 20 個交易日 (約一個月) */
const FORWARD_DAYS = 20
/** 近期明細列幾天 */
const RECENT_DAYS = 10

type Tone = "buy" | "sell" | ""

interface Stat {
    label: string
    value: string
    sub?: string
    tone?: Tone
}

interface Cell {
    text: string
    tone?: Tone
}

interface Table {
    title: string
    note: string
    columns: string[]
    rows: { key: string; cells: Cell[] }[]
}

function fmt(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return value.toLocaleString("zh-TW", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    })
}

function signed(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return (value > 0 ? "+" : "") + fmt(value, digits)
}

function toneOf(value: number | null | undefined): Tone {
    if (!value) {
        return ""
    }
    return value > 0 ? "buy" : "sell"
}

const tradingDates = computed(() => props.rows.map((row) => row.date))

/** 某欄位有值的資料點 */
function pointsOf(key: keyof ChipRow): Point[] {
    const points: Point[] = []
    for (const row of props.rows) {
        const value = row[key]
        if (typeof value === "number") {
            points.push({ date: row.date, value })
        }
    }
    return points
}

/** 指數當天收盤與前一個交易日比較的漲跌幅 */
function dayPct(date: string): number | null {
    const index = tradingDates.value.indexOf(date)
    if (index <= 0) {
        return null
    }
    const today = props.closes.get(date)
    const prev = props.closes.get(tradingDates.value[index - 1])
    return today && prev ? (today / prev - 1) * 100 : null
}

function forwardCell(date: string): Cell {
    const pct = forwardPct(tradingDates.value, props.closes, date, FORWARD_DAYS)
    return pct === null ? { text: "未滿 20 日" } : { text: `${signed(pct)}%`, tone: toneOf(pct) }
}

/** 法人買賣超：連續天數與各區間累計，下方列近 10 天 */
function netView(key: "total" | "foreign" | "trust" | "dealer"): { stats: Stat[]; table: Table } {
    const points = pointsOf(key)
    const values = points.map((point) => point.value)
    const last = points[points.length - 1]
    const run = streak(values)
    const stats: Stat[] = [
        {
            label: `今天 ${last ? formatDate(last.date).slice(5) : ""}`,
            value: `${signed(last?.value)} 億`,
            tone: toneOf(last?.value),
        },
        {
            label: "連續",
            value: run ? `${Math.abs(run)} 天${run > 0 ? "買超" : "賣超"}` : "--",
            tone: toneOf(run),
        },
        ...[5, 20, 60].map((n) => {
            const total = sumLast(values, n)
            return { label: `近 ${n} 日累計`, value: `${signed(total)} 億`, tone: toneOf(total) }
        }),
    ]
    const recent = points.slice(-RECENT_DAYS).reverse()
    return {
        stats,
        table: {
            title: `${props.marketLabel}${props.metricLabel}近 ${RECENT_DAYS} 個交易日`,
            note: "對照當天指數漲跌，看買賣超有沒有推動行情",
            columns: ["日期", `${props.metricLabel}（億）`, `${props.indexName}收盤`, "指數漲跌"],
            rows: recent.map((point) => {
                const pct = dayPct(point.date)
                return {
                    key: point.date,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: signed(point.value), tone: toneOf(point.value) },
                        { text: fmt(props.closes.get(point.date), 2) },
                        { text: pct === null ? "--" : `${signed(pct, 2)}%`, tone: toneOf(pct) },
                    ],
                }
            }),
        },
    }
}

/** 融券餘額：近期增減與一年高點，下方列近 10 天 */
function shortView(): { stats: Stat[]; table: Table } {
    const points = pointsOf("short_units")
    const values = points.map((point) => point.value)
    const last = points[points.length - 1]
    const prev = points[points.length - 2]
    const before20 = points[points.length - 1 - 20]
    const [top] = extremeDays(points, "max", 1)
    const stats: Stat[] = [
        { label: `今天 ${last ? formatDate(last.date).slice(5) : ""}`, value: `${fmt(last?.value, 0)} 張` },
        {
            label: "較前一日",
            value: `${signed(last && prev ? last.value - prev.value : null, 0)} 張`,
            tone: toneOf(last && prev ? last.value - prev.value : null),
        },
        {
            label: "近 20 日變化",
            value: `${signed(last && before20 ? last.value - before20.value : null, 0)} 張`,
            tone: toneOf(last && before20 ? last.value - before20.value : null),
        },
        {
            label: "一年最高",
            value: `${fmt(top?.value, 0)} 張`,
            sub: top ? formatDate(top.date) : "",
        },
    ]
    const recent = points.slice(-RECENT_DAYS).reverse()
    return {
        stats,
        table: {
            title: `${props.marketLabel}融券餘額近 ${RECENT_DAYS} 個交易日`,
            note: "融券增加代表看空的人變多，也可能是日後回補的買盤",
            columns: ["日期", "融券餘額（張）", "增減（張）", `${props.indexName}收盤`],
            rows: recent.map((point) => {
                const index = values.length - 1 - recent.indexOf(point)
                const diff = index > 0 ? point.value - values[index - 1] : null
                return {
                    key: point.date,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: fmt(point.value, 0) },
                        { text: signed(diff, 0), tone: toneOf(diff) },
                        { text: fmt(props.closes.get(point.date), 2) },
                    ],
                }
            }),
        },
    }
}

/** 融資維持率：一年高低點，下方列維持率最低的幾天與之後的指數表現 */
function maintenanceView(): { stats: Stat[]; table: Table } {
    const points = pointsOf("maintenance")
    const last = points[points.length - 1]
    const [high] = extremeDays(points, "max", 1)
    const lows = maintenanceLows(props.rows)
    const below = points.filter((point) => point.value < 160).length
    const stats: Stat[] = [
        {
            label: `今天 ${last ? formatDate(last.date).slice(5) : ""}`,
            value: `${fmt(last?.value, 2)}%`,
            sub: last ? maintenanceLevel(last.value).label : "",
        },
        { label: "一年最高", value: `${fmt(high?.value, 2)}%`, sub: high ? formatDate(high.date) : "" },
        { label: "一年最低", value: `${fmt(lows[0]?.value, 2)}%`, sub: lows[0] ? formatDate(lows[0].date) : "" },
        { label: "低於 160% 的天數", value: `${below} 天`, sub: `共 ${points.length} 天` },
    ]
    return {
        stats,
        table: {
            title: `${props.marketLabel}融資維持率最低的 ${lows.length} 天`,
            note: `彼此至少相隔 10 個交易日；維持率探底常伴隨斷頭賣壓，看之後 ${FORWARD_DAYS} 個交易日指數是否反彈`,
            columns: ["日期", "維持率", `${props.indexName}收盤`, `之後 ${FORWARD_DAYS} 日指數`],
            rows: [...lows]
                .sort((a, b) => a.date.localeCompare(b.date))
                .map((point) => ({
                    key: point.date,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: `${fmt(point.value, 2)}%` },
                        { text: fmt(props.closes.get(point.date), 2) },
                        forwardCell(point.date),
                    ],
                })),
        },
    }
}

/** 恐慌指標：台美最新值與高點，下方列兩邊 VIX 最高的日子與之後的指數表現 */
function vixView(): { stats: Stat[]; table: Table } {
    const toPoints = (source: Map<string, number>) =>
        [...source].map(([date, value]) => ({ date, value })).sort((a, b) => a.date.localeCompare(b.date))
    const tw = toPoints(props.twVix)
    const us = toPoints(props.usVix).filter((point) => point.date >= (tradingDates.value[0] ?? ""))
    const twLast = tw[tw.length - 1]
    const usLast = us[us.length - 1]
    const highs = vixHighs(props.twVix, props.usVix, tradingDates.value[0] ?? "")
    const byValue = (a: Point, b: Point) => b.value - a.value
    const twHighs = highs.filter((point) => point.market === "TW").sort(byValue)
    const usHighs = highs.filter((point) => point.market === "US").sort(byValue)
    const stats: Stat[] = [
        {
            label: `台指 VIX ${twLast ? formatDate(twLast.date).slice(5) : ""}`,
            value: fmt(twLast?.value, 2),
            sub: twLast ? vixLevel(twLast.value, "TW").label : "",
        },
        {
            label: `美國 VIX ${usLast ? formatDate(usLast.date).slice(5) : ""}`,
            value: fmt(usLast?.value, 2),
            sub: usLast ? vixLevel(usLast.value, "US").label : "",
        },
        {
            label: "台指 VIX 最高",
            value: fmt(twHighs[0]?.value, 2),
            // 期交所只留約三個月，註明資料起點；最高點剛好是第一天時就不重複寫
            sub: twHighs[0]
                ? twHighs[0].date === tw[0].date
                    ? `${formatDate(twHighs[0].date)} (資料首日)`
                    : `${formatDate(twHighs[0].date)} (資料自 ${formatDate(tw[0].date)} 起)`
                : "",
        },
        {
            label: "美國 VIX 一年最高",
            value: fmt(usHighs[0]?.value, 2),
            sub: usHighs[0] ? formatDate(usHighs[0].date) : "",
        },
    ]
    const rows = highs.map((point) => ({ ...point, market: point.market === "TW" ? "台指" : "美國" }))
    return {
        stats,
        table: {
            title: "VIX 最高的日子",
            note: `台指與美國各取最高的 3 天，彼此至少相隔 10 天；恐慌高點常是相對低點，看之後 ${FORWARD_DAYS} 個交易日${props.indexName}怎麼走`,
            columns: ["日期", "市場", "VIX", `當天${props.indexName}收盤`, `之後 ${FORWARD_DAYS} 日指數`],
            rows: rows.map((point) => {
                const start = tradingDates.value.find((date) => date >= point.date)
                return {
                    key: `${point.market}-${point.date}`,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: point.market },
                        { text: fmt(point.value, 2) },
                        { text: fmt(start ? props.closes.get(start) : null, 2) },
                        forwardCell(point.date),
                    ],
                }
            }),
        },
    }
}

const view = computed(() => {
    if (!props.rows.length) {
        return null
    }
    switch (props.metric) {
        case "total":
        case "foreign":
        case "trust":
        case "dealer":
            return netView(props.metric)
        case "short_units":
            return shortView()
        case "maintenance":
            return maintenanceView()
        case "vix":
            return vixView()
        default:
            return null
    }
})

function toneClass(tone: Tone | undefined): string {
    return tone === "buy" ? "val-buy" : tone === "sell" ? "val-sell" : ""
}
</script>

<template>
    <div v-if="view" class="insight">
        <div class="stats">
            <div v-for="stat in view.stats" :key="stat.label" class="stat">
                <div class="stat-label">{{ stat.label }}</div>
                <div class="stat-value" :class="toneClass(stat.tone)">{{ stat.value }}</div>
                <div v-if="stat.sub" class="stat-sub">{{ stat.sub }}</div>
            </div>
        </div>

        <h3 class="table-title">
            {{ view.table.title }}
            <span class="insight-note">{{ view.table.note }}</span>
        </h3>
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th
                            v-for="(column, index) in view.table.columns"
                            :key="column"
                            :class="{ num: index > 0 && column !== '市場' }"
                        >
                            {{ column }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-if="!view.table.rows.length" class="empty-row">
                        <td :colspan="view.table.columns.length">無資料</td>
                    </tr>
                    <tr v-for="row in view.table.rows" :key="row.key">
                        <td
                            v-for="(cell, index) in row.cells"
                            :key="index"
                            :class="[toneClass(cell.tone), { num: index > 0 && view.table.columns[index] !== '市場' }]"
                        >
                            {{ cell.text }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</template>

<style scoped>
.insight {
    margin-top: 12px;
}

.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px;
    margin-bottom: 12px;
}

.stat {
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-0);
}

.stat-label {
    color: var(--text-muted);
    font-size: 12px;
}

.stat-value {
    margin-top: 2px;
    font-size: 17px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.stat-sub {
    margin-top: 2px;
    color: var(--text-secondary);
    font-size: 12px;
}

.insight-note {
    margin-left: 8px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
}
</style>
