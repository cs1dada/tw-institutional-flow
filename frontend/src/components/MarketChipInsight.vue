<script setup lang="ts">
/**
 * 大盤籌碼圖下方的摘要與對照表，內容跟著上方選的指標換：
 * 法人看連續買賣超與累計，融券看近期增減，
 * 維持率、VIX 與追繳戶數則列出極端值的日子，對照之後 20 個交易日指數怎麼走；
 * 融資槓桿列出近期比重與 2000 年以來的年度歷史。
 * 融資餘額有自己的「相近日」表，在 MarketChipPanel 裡處理，這裡不顯示。
 */
import { computed } from "vue"

import type { ChipRow, CreditRow, MarketPayload } from "@/types"
import { formatDate } from "@/utils/format"
import {
    callPeaks,
    extremeDays,
    forwardPct,
    maintenanceLevel,
    maintenanceLows,
    officialLevel,
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
    /** 官方全市場信用交易指標 */
    credit: CreditRow[]
    creditHistory?: MarketPayload["credit_history"]
    /** TWSE 或 TPEX，用來挑年度歷史 */
    marketKey: "TWSE" | "TPEX"
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

interface View {
    stats: Stat[]
    tables: Table[]
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
const creditByDate = computed(() => new Map(props.credit.map((row) => [row.date, row])))

function pct(value: number | null | undefined, digits = 2): string {
    return value === null || value === undefined ? "--" : `${fmt(value, digits)}%`
}

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
function netView(key: "total" | "foreign" | "trust" | "dealer"): View {
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
        tables: [{
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
        }],
    }
}

/** 融券餘額：近期增減與一年高點，下方列近 10 天 */
function shortView(): View {
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
        tables: [{
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
        }],
    }
}

/** 融資維持率：一年高低點，下方列維持率最低的幾天與之後的指數表現 */
function maintenanceView(): View {
    const points = pointsOf("maintenance")
    const last = points[points.length - 1]
    const [high] = extremeDays(points, "max", 1)
    const lows = maintenanceLows(props.rows)
    const below = points.filter((point) => point.value < 160).length
    const official = props.credit.filter((row) => typeof row.keep_rate === "number")
    const officialLast = official[official.length - 1]
    const officialSameDay = last ? creditByDate.value.get(last.date)?.keep_rate : null
    const stats: Stat[] = [
        {
            label: `民間版 ${last ? formatDate(last.date).slice(5) : ""}`,
            value: `${fmt(last?.value, 2)}%`,
            sub: last ? maintenanceLevel(last.value).label : "",
        },
        {
            label: `官方全市場 ${officialLast ? formatDate(officialLast.date).slice(5) : ""}`,
            value: pct(officialLast?.keep_rate),
            sub: [
                officialLast?.keep_rate != null ? officialLevel(officialLast.keep_rate).label : "",
                last && typeof officialSameDay === "number"
                    ? `比民間版高 ${fmt(officialSameDay - last.value, 2)} 個百分點`
                    : "",
            ].filter(Boolean).join("，"),
        },
        { label: "一年最高", value: `${fmt(high?.value, 2)}%`, sub: high ? formatDate(high.date) : "" },
        { label: "一年最低", value: `${fmt(lows[0]?.value, 2)}%`, sub: lows[0] ? formatDate(lows[0].date) : "" },
        { label: "低於 160% 的天數", value: `${below} 天`, sub: `共 ${points.length} 天` },
    ]
    return {
        stats,
        tables: [{
            title: `${props.marketLabel}融資維持率最低的 ${lows.length} 天`,
            note: `彼此至少相隔 10 個交易日；維持率探底常伴隨斷頭賣壓，看之後 ${FORWARD_DAYS} 個交易日指數是否反彈`,
            columns: ["日期", "民間版", "官方全市場", `${props.indexName}收盤`, `之後 ${FORWARD_DAYS} 日指數`],
            rows: [...lows]
                .sort((a, b) => a.date.localeCompare(b.date))
                .map((point) => ({
                    key: point.date,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: `${fmt(point.value, 2)}%` },
                        { text: pct(creditByDate.value.get(point.date)?.keep_rate) },
                        { text: fmt(props.closes.get(point.date), 2) },
                        forwardCell(point.date),
                    ],
                })),
        }],
    }
}

/** 融資槓桿：融資占市值與信用交易占成交比重，近期明細與 2000 年以來的年度歷史 */
function ratioView(): View {
    const ratios = pointsOf("margin_ratio")
    const credits = pointsOf("credit_ratio")
    const last = ratios[ratios.length - 1]
    const lastCredit = credits[credits.length - 1]
    const history = props.creditHistory?.[props.marketKey] ?? []
    const thisYear = history[history.length - 1]
    const pastYears = history.slice(0, -1).filter((row) => typeof row[1] === "number")
    const peak = pastYears.reduce<(typeof history)[number] | null>(
        (best, row) => (best === null || (row[1] as number) > (best[1] as number) ? row : best),
        null,
    )
    const stats: Stat[] = [
        {
            label: `融資占市值 ${last ? formatDate(last.date).slice(5) : ""}`,
            value: pct(last?.value, 3),
        },
        {
            label: `信用交易占成交 ${lastCredit ? formatDate(lastCredit.date).slice(5) : ""}`,
            value: pct(lastCredit?.value),
        },
        {
            label: thisYear ? `${thisYear[0]} 年至今` : "今年至今",
            value: thisYear ? `${pct(thisYear[1])} / ${pct(thisYear[2])}` : "--",
            sub: "融資占市值 / 信用交易占成交",
        },
        {
            label: "2000 年來融資占市值最高",
            value: pct(peak?.[1]),
            sub: peak ? `${peak[0]} 年` : "",
        },
    ]
    const byDate = new Map(credits.map((point) => [point.date, point.value]))
    const marginByDate = new Map(pointsOf("margin").map((point) => [point.date, point.value]))
    const recent = ratios.slice(-RECENT_DAYS).reverse()
    return {
        stats,
        tables: [
            {
                title: `${props.marketLabel}融資槓桿近 ${RECENT_DAYS} 個交易日`,
                note: "信用交易占成交 = 信用交易成交值 ÷ (總成交值 × 2)，與臺股儀表板的定義相同",
                columns: ["日期", "融資占市值", "信用交易占成交", "融資餘額（億）", `${props.indexName}收盤`],
                rows: recent.map((point) => ({
                    key: point.date,
                    cells: [
                        { text: formatDate(point.date) },
                        { text: pct(point.value, 3) },
                        { text: pct(byDate.get(point.date)) },
                        { text: fmt(marginByDate.get(point.date)) },
                        { text: fmt(props.closes.get(point.date), 2) },
                    ],
                })),
            },
            {
                title: `${props.marketLabel}年度融資槓桿`,
                note: "年資料為年底的融資占市值與全年的信用交易占成交，今年為截至上個月底",
                columns: ["年度", "融資占市值", "信用交易占成交"],
                rows: [...history].reverse().map((row) => ({
                    key: row[0],
                    cells: [{ text: row[0] }, { text: pct(row[1]) }, { text: pct(row[2]) }],
                })),
            },
        ],
    }
}

/** 追繳處分：官方全市場的追繳與處分，追繳戶數最多的日子與近期明細 */
function callsView(): View {
    const rows = props.credit
    const last = rows[rows.length - 1]
    const peaks = callPeaks(rows)
    const defaultPoints = pointsOf("default")
    const defaults = new Map(defaultPoints.map((point) => [point.date, point.value]))
    const lastDefault = defaultPoints[defaultPoints.length - 1]
    const stats: Stat[] = [
        {
            label: `追繳戶數 ${last ? formatDate(last.date).slice(5) : ""}`,
            value: last?.below_acc == null ? "--" : `${fmt(last.below_acc, 0)} 戶`,
            sub: `官方維持率 ${pct(last?.keep_rate)}${last?.keep_rate != null ? ` ${officialLevel(last.keep_rate).label}` : ""}`,
        },
        { label: "當日追繳金額", value: `${fmt(last?.call_amt, 2)} 億` },
        {
            label: "次日處分",
            value: last?.exe_acc == null ? "--" : `${fmt(last.exe_acc, 0)} 戶`,
            sub: `${fmt(last?.exe_amt, 2)} 億`,
        },
        {
            label: "最多的一天",
            value: peaks[0] ? `${fmt(peaks[0].value, 0)} 戶` : "--",
            sub: peaks[0] ? formatDate(peaks[0].date) : "",
        },
        ...(props.marketKey === "TWSE"
            ? [{
                label: `上市違約金額 ${lastDefault ? formatDate(lastDefault.date).slice(5) : ""}`,
                value: `${fmt(lastDefault?.value, 2)} 億`,
                sub: "證券商申報，買賣合計",
            }]
            : []),
    ]
    const recent = rows.slice(-RECENT_DAYS).reverse()
    return {
        stats,
        tables: [
            {
                title: "追繳戶數暴增的日子",
                note: `全市場，至少有最多那天的三成，彼此相隔 10 個交易日以上；追繳暴增後常有斷頭賣壓，看之後 ${FORWARD_DAYS} 個交易日${props.indexName}怎麼走`,
                columns: ["日期", "追繳戶數", "追繳金額（億）", "官方維持率", `${props.indexName}收盤`, `之後 ${FORWARD_DAYS} 日指數`],
                rows: [...peaks]
                    .sort((a, b) => a.date.localeCompare(b.date))
                    .map((point) => {
                        const row = creditByDate.value.get(point.date)
                        return {
                            key: point.date,
                            cells: [
                                { text: formatDate(point.date) },
                                { text: fmt(point.value, 0) },
                                { text: fmt(row?.call_amt, 2) },
                                { text: pct(row?.keep_rate) },
                                { text: fmt(props.closes.get(point.date), 2) },
                                forwardCell(point.date),
                            ],
                        }
                    }),
            },
            {
                title: `近 ${RECENT_DAYS} 個交易日的追繳與處分`,
                note: "追繳後 2 個營業日內未補足，券商會在次一營業日處分 (斷頭)；違約金額只有上市",
                columns: ["日期", "追繳戶數", "追繳金額（億）", "處分戶數", "處分金額（億）", "違約金額（億）"],
                rows: recent.map((row) => ({
                    key: row.date,
                    cells: [
                        { text: formatDate(row.date) },
                        { text: fmt(row.below_acc, 0) },
                        { text: fmt(row.call_amt, 2) },
                        { text: fmt(row.exe_acc, 0) },
                        { text: fmt(row.exe_amt, 2) },
                        { text: fmt(defaults.get(row.date), 2) },
                    ],
                })),
            },
        ],
    }
}

/** 恐慌指標：台美最新值與高點，下方列兩邊 VIX 最高的日子與之後的指數表現 */
function vixView(): View {
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
        tables: [{
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
        }],
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
        case "margin_ratio":
            return ratioView()
        case "calls":
            return callsView()
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

        <template v-for="table in view.tables" :key="table.title">
            <h3 class="table-title">
                {{ table.title }}
                <span class="insight-note">{{ table.note }}</span>
            </h3>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th
                                v-for="(column, index) in table.columns"
                                :key="column"
                                :class="{ num: index > 0 && column !== '市場' }"
                            >
                                {{ column }}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!table.rows.length" class="empty-row">
                            <td :colspan="table.columns.length">無資料</td>
                        </tr>
                        <tr v-for="row in table.rows" :key="row.key">
                            <td
                                v-for="(cell, index) in row.cells"
                                :key="index"
                                :class="[toneClass(cell.tone), { num: index > 0 && table.columns[index] !== '市場' }]"
                            >
                                {{ cell.text }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </template>
    </div>
</template>

<style scoped>
.insight {
    margin-top: 12px;
}

.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
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

/* 有兩張表時，第二張與上一張表格拉開距離 */
.table-wrap + .table-title {
    margin-top: 16px;
}

.insight-note {
    margin-left: 8px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
}
</style>
