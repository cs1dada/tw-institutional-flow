<script setup lang="ts">
/**
 * 槓桿配置回測：純 0050、純 00631L、5050 (正 2 + 短債)、442 (正 2 + 0050 + 短債)。
 *
 * 回測在 Python 端算好 (scripts/backtest_leverage.py)，輸出成 src/data/leverage_backtest.json
 * 隨前端一起打包，靜態站與本機模式都能直接顯示，不需要後端端點。
 * 要更新數字就重跑腳本再重新建置。
 */
import { computed, ref } from "vue"
import VChart from "vue-echarts"

import data from "@/data/leverage_backtest.json"
import { baseTooltip, colors } from "@/utils/theme"

type Key = "e100" | "l100" | "s5050" | "s442"

interface Stat {
    final: number
    cagr: number
    vol: number
    mdd: number
    sharpe: number
    sortino: number
    calmar: number
    underwater_days: number
    rebalances: number
}

interface Holding {
    worst: number
    median: number
    best: number
    loss_prob: number
    beat_0050: number | null
}

interface Dca {
    invested: number
    final: number
    multiple: number
    xirr: number
    nav_mdd: number
    max_loss_amount: number
    worst_book: number
}

const stats = data.stats as Record<string, Stat>
const dca = data.dca as Record<string, Dca>
const holding = data.holding as Record<string, Record<Key, Holding>>
const curve = data.curve as unknown as { dates: string[] } & Record<Key, number[]>
const yearly = data.yearly as unknown as ({ year: number } & Record<Key, number>)[]
const crashes = data.crashes as unknown as ({ label: string } & Record<Key, number>)[]

/** 色票：沿用全站三法人系列色 (slot 1-3)，第四條補黃色；已通過相鄰配對的色覺缺陷驗證，線尾另有直接標註 */
const STRATEGIES: { key: Key; name: string; mix: string; exposure: string; color: string; note: string }[] = [
    {
        key: "e100", name: "純 0050", mix: "100% 0050", exposure: "1.0 倍", color: "#2a78d6",
        note: "最簡單，不需要任何操作",
    },
    {
        key: "l100", name: "純 00631L", mix: "100% 00631L，買進後不動", exposure: "2.0 倍", color: "#eb6834",
        note: "報酬最高、效率最低，回撤常超過四成",
    },
    {
        key: "s5050", name: "5050", mix: "50% 00631L + 50% 短債", exposure: "1.0 倍", color: "#1baf7a",
        note: "報酬接近 0050，回撤較淺、回本較快",
    },
    {
        key: "s442", name: "442", mix: "40% 00631L + 40% 0050 + 20% 短債", exposure: "1.2 倍", color: "#f2a600",
        note: "回撤和 0050 相當，長期持有幾乎穩贏 0050",
    },
]
const RECOMMENDED: Key = "s442"

/* ===== 格式化 ===== */

function pct(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return `${(value * 100).toFixed(digits)}%`
}

function signedPctOf(value: number, digits = 1): string {
    return `${value > 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`
}

/** 金額以萬元顯示 */
function wan(amount: number): string {
    return `${Math.round(amount / 1e4).toLocaleString("zh-TW")} 萬`
}

/** 台股慣例：正值紅、負值綠 */
function tone(value: number | null | undefined): string {
    if (value === null || value === undefined || value === 0) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

/** 一列之中最好的那一格 (越大越好，lowerBetter 時越小越好) */
function bestKey(values: Record<Key, number | null>, lowerBetter = false): Key | null {
    let best: Key | null = null
    for (const s of STRATEGIES) {
        const v = values[s.key]
        if (v === null || v === undefined) {
            continue
        }
        if (best === null || (lowerBetter ? v < values[best]! : v > values[best]!)) {
            best = s.key
        }
    }
    return best
}

/* ===== 摘要文字 ===== */

const period = `${data.start} ~ ${data.end}，約 ${data.years} 年`

const diff442 = computed(() => ({
    cagr: ((stats.s442.cagr - stats.e100.cagr) * 100).toFixed(1),
    mdd: ((stats.e100.mdd - stats.s442.mdd) * 100).toFixed(1),
}))

const diff5050 = computed(() => ({
    mdd: ((stats.s5050.mdd - stats.e100.mdd) * 100).toFixed(1),
    months: Math.round((stats.e100.underwater_days - stats.s5050.underwater_days) / 30),
}))

/* ===== 圖表 ===== */

const scale = ref<"log" | "linear">("log")

const drawdowns = computed(() =>
    Object.fromEntries(
        STRATEGIES.map((s) => {
            let peak = -Infinity
            return [s.key, curve[s.key].map((v) => {
                peak = Math.max(peak, v)
                return +(v / peak - 1).toFixed(4)
            })]
        }),
    ) as Record<Key, number[]>,
)

function lineOption(
    values: Record<Key, number[]>,
    axis: Record<string, unknown>,
    format: (v: number) => string,
    endFormat: (v: number) => string,
) {
    const c = colors()
    return {
        animation: false,
        grid: { left: 56, right: 120, top: 16, bottom: 32 },
        xAxis: {
            type: "time",
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 11 },
            splitLine: { show: false },
        },
        yAxis: {
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            ...axis,
            axisLabel: { color: c.muted, fontSize: 11, ...(axis.axisLabel as object) },
        },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "line" },
            formatter: (params: { dataIndex: number }[]) => {
                const index = params[0]?.dataIndex
                if (index === undefined) {
                    return ""
                }
                // 依當時數值由高到低排列
                const rows = STRATEGIES
                    .map((s) => ({ s, v: values[s.key][index] }))
                    .sort((a, b) => b.v - a.v)
                    .map(({ s, v }) =>
                        `<span style="display:inline-block;width:10px;height:3px;background:${s.color};`
                        + `vertical-align:middle;margin-right:6px"></span>${s.name}　${format(v)}`)
                return [`<strong>${curve.dates[index]}</strong>`, ...rows].join("<br>")
            },
        },
        series: STRATEGIES.map((s) => ({
            name: s.name,
            type: "line",
            symbol: "none",
            lineStyle: { width: 2, color: s.color },
            itemStyle: { color: s.color },
            data: curve.dates.map((d, i) => [d, values[s.key][i]]),
            endLabel: {
                show: true,
                color: c.text,
                fontSize: 12,
                formatter: (p: { value: [string, number] }) => `${s.name} ${endFormat(p.value[1])}`,
            },
            labelLayout: { moveOverlap: "shiftY" },
            emphasis: { focus: "series" },
        })),
    }
}

const equityOption = computed(() =>
    lineOption(
        Object.fromEntries(STRATEGIES.map((s) => [s.key, curve[s.key]])) as Record<Key, number[]>,
        scale.value === "log"
            ? { type: "log", logBase: 10, min: 0.8, axisLabel: { showMinLabel: false, formatter: (v: number) => `${v}x` } }
            : { type: "value", min: 0, axisLabel: { formatter: (v: number) => `${v}x` } },
        (v) => `${v.toFixed(2)} 倍`,
        (v) => `${v.toFixed(1)}x`,
    ),
)

const drawdownOption = computed(() =>
    lineOption(
        drawdowns.value,
        { type: "value", max: 0, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` } },
        (v) => pct(v),
        (v) => pct(v, 0),
    ),
)

/* ===== 表格 ===== */

const summaryRows = computed(() => {
    const rows: { label: string; get: (s: Stat) => number; fmt: (v: number) => string; lowerBetter?: boolean }[] = [
        { label: "100 萬變成", get: (s) => s.final, fmt: (v) => wan(v * 1e6) },
        { label: "年化報酬", get: (s) => s.cagr, fmt: (v) => pct(v) },
        { label: "年化波動", get: (s) => s.vol, fmt: (v) => pct(v), lowerBetter: true },
        { label: "最大回撤", get: (s) => s.mdd, fmt: (v) => pct(v) },
        { label: "報酬/波動", get: (s) => s.sharpe, fmt: (v) => v.toFixed(2) },
        { label: "Sortino (只計下跌波動)", get: (s) => s.sortino, fmt: (v) => v.toFixed(2) },
        { label: "報酬/回撤", get: (s) => s.calmar, fmt: (v) => v.toFixed(2) },
        { label: "最長套牢期 (天)", get: (s) => s.underwater_days, fmt: (v) => v.toLocaleString("zh-TW"), lowerBetter: true },
        { label: "再平衡次數", get: (s) => s.rebalances, fmt: (v) => String(v) },
    ]
    return rows.map((r) => {
        const values = Object.fromEntries(STRATEGIES.map((s) => [s.key, r.get(stats[s.key])])) as Record<Key, number>
        return {
            label: r.label,
            cells: STRATEGIES.map((s) => r.fmt(values[s.key])),
            best: r.label === "再平衡次數" ? null : bestKey(values, r.lowerBetter),
        }
    })
})

const HOLD_YEARS = ["1", "3", "5"] as const
const holdYears = ref<(typeof HOLD_YEARS)[number]>("3")

const holdingRows = computed(() => {
    const h = holding[holdYears.value]
    const rows: { label: string; field: keyof Holding; lowerBetter?: boolean; signed?: boolean }[] = [
        { label: "最差年化", field: "worst", signed: true },
        { label: "中位數年化", field: "median", signed: true },
        { label: "最佳年化", field: "best", signed: true },
        { label: "虧損機率", field: "loss_prob", lowerBetter: true },
        { label: "贏 0050 的機率", field: "beat_0050" },
    ]
    return rows.map((r) => {
        const values = Object.fromEntries(STRATEGIES.map((s) => [s.key, h[s.key][r.field]])) as Record<Key, number | null>
        return {
            label: r.label,
            cells: STRATEGIES.map((s) => ({
                text: values[s.key] === null ? "--" : r.signed ? signedPctOf(values[s.key]!) : pct(values[s.key]),
                cls: r.signed ? tone(values[s.key]) : "",
            })),
            best: bestKey(values, r.lowerBetter),
        }
    })
})

const crashRows = computed(() =>
    crashes.map((row) => ({
        label: row.label,
        cells: STRATEGIES.map((s) => pct(row[s.key])),
        best: bestKey(Object.fromEntries(STRATEGIES.map((s) => [s.key, row[s.key]])) as Record<Key, number>),
    })),
)

const yearRows = computed(() =>
    yearly.map((row, i) => {
        let label = String(row.year)
        if (i === 0) {
            label += ` (${data.start.slice(5, 7)} 月起)`
        } else if (i === yearly.length - 1) {
            label += ` (至 ${data.end.slice(5)})`
        }
        return {
            label,
            cells: STRATEGIES.map((s) => ({ text: signedPctOf(row[s.key]), cls: tone(row[s.key]) })),
        }
    }),
)

const dcaRows = computed(() => {
    const rows: { label: string; fmt: (d: Dca) => string; signedVal?: (d: Dca) => number }[] = [
        { label: "總投入", fmt: (d) => wan(d.invested) },
        { label: "期末市值", fmt: (d) => wan(d.final) },
        { label: "市值/投入", fmt: (d) => `${d.multiple.toFixed(2)} 倍` },
        { label: "XIRR (年化)", fmt: (d) => pct(d.xirr) },
        { label: "淨值最大回撤", fmt: (d) => pct(d.nav_mdd), signedVal: (d) => d.nav_mdd },
        { label: "市值最大縮水", fmt: (d) => wan(d.max_loss_amount), signedVal: (d) => d.max_loss_amount },
        { label: "最差帳面報酬", fmt: (d) => pct(d.worst_book), signedVal: (d) => d.worst_book },
    ]
    return rows.map((r) => ({
        label: r.label,
        cells: STRATEGIES.map((s) => ({
            text: r.fmt(dca[s.key]),
            cls: r.signedVal ? tone(r.signedVal(dca[s.key])) : "",
        })),
    }))
})
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>槓桿配置回測</h1>
                <p class="subtitle">
                    00631L 每日重設 2 倍槓桿，長期報酬有路徑相依與波動耗損；
                    比較純 0050、純 00631L 與兩種搭配短債的再平衡組合
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">回測期間 {{ period }}</span>
            </div>
        </header>

        <section class="panel" data-nav="配置一覽">
            <div class="panel-head">
                <h2>四種配置一覽</h2>
                <p class="panel-note">單筆投入，期初 100 萬；5050 與 442 採門檻再平衡</p>
            </div>
            <div class="cards">
                <article
                    v-for="s in STRATEGIES"
                    :key="s.key"
                    class="quote-card card"
                    :class="{ 'is-rec': s.key === RECOMMENDED }"
                >
                    <div class="card-head">
                        <span class="card-swatch" :style="{ background: s.color }" />
                        <span class="card-name">{{ s.name }}</span>
                        <span v-if="s.key === RECOMMENDED" class="rec-tag">推薦</span>
                    </div>
                    <div class="card-mix">{{ s.mix }}・曝險 {{ s.exposure }}</div>
                    <div class="quote-value">{{ pct(stats[s.key].cagr) }}</div>
                    <div class="quote-meta">年化報酬</div>
                    <dl class="kv">
                        <dt>100 萬變成</dt><dd>{{ wan(stats[s.key].final * 1e6) }}</dd>
                        <dt>最大回撤</dt><dd>{{ pct(stats[s.key].mdd) }}</dd>
                        <dt>報酬/波動</dt><dd>{{ stats[s.key].sharpe.toFixed(2) }}</dd>
                    </dl>
                    <p class="card-note">{{ s.note }}</p>
                </article>
            </div>
        </section>

        <section class="panel" data-nav="淨值走勢">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>淨值走勢</h2>
                    <p class="panel-note">
                        期初 1 元，週資料。對數刻度下斜率代表報酬率，比較容易看出各段漲跌幅
                    </p>
                </div>
                <div class="tabs" role="tablist">
                    <button
                        type="button" class="tab" role="tab"
                        :class="{ 'is-active': scale === 'log' }" @click="scale = 'log'"
                    >
                        對數刻度
                    </button>
                    <button
                        type="button" class="tab" role="tab"
                        :class="{ 'is-active': scale === 'linear' }" @click="scale = 'linear'"
                    >
                        線性刻度
                    </button>
                </div>
            </div>
            <div class="legend">
                <span v-for="s in STRATEGIES" :key="s.key" class="legend-item">
                    <span class="legend-line" :style="{ background: s.color }" />{{ s.name }}
                </span>
            </div>
            <VChart class="chart chart-tall" :option="equityOption" autoresize />
        </section>

        <section class="panel" data-nav="回撤">
            <div class="panel-head">
                <h2>回撤 (距離前高的跌幅)</h2>
                <p class="panel-note">
                    純 00631L 大約每兩三年就有一次 45% 以上的回撤；5050 在多數下跌中都比 0050 淺。
                    圖為週資料，最低點會比下表的日資料淺一些
                </p>
            </div>
            <div class="legend">
                <span v-for="s in STRATEGIES" :key="s.key" class="legend-item">
                    <span class="legend-line" :style="{ background: s.color }" />{{ s.name }}
                </span>
            </div>
            <VChart class="chart" :option="drawdownOption" autoresize />
            <h3 class="table-title">各次下跌的最大回撤</h3>
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>期間</th>
                            <th v-for="s in STRATEGIES" :key="s.key" class="num">{{ s.name }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in crashRows" :key="row.label">
                            <td>{{ row.label }}</td>
                            <td
                                v-for="(cell, i) in row.cells" :key="i"
                                class="num" :class="{ best: STRATEGIES[i].key === row.best }"
                            >
                                {{ cell }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p class="panel-note">粗體為該次跌得最少的配置</p>
        </section>

        <section class="panel" data-nav="績效總表">
            <div class="panel-head">
                <h2>績效總表 (單筆投入)</h2>
                <p class="panel-note">粗體為該項最好的配置；再平衡次數不比較</p>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>指標</th>
                            <th v-for="s in STRATEGIES" :key="s.key" class="num">{{ s.name }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in summaryRows" :key="row.label">
                            <td>{{ row.label }}</td>
                            <td
                                v-for="(cell, i) in row.cells" :key="i"
                                class="num" :class="{ best: STRATEGIES[i].key === row.best }"
                            >
                                {{ cell }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel" data-nav="進場勝率">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>任意時點進場的勝率</h2>
                    <p class="panel-note">
                        把每一個交易日當成進場日，統計持有 N 年後的年化報酬，也就是「隨便哪天買進，結果會怎樣」
                    </p>
                </div>
                <div class="tabs" role="tablist">
                    <button
                        v-for="y in HOLD_YEARS" :key="y"
                        type="button" class="tab" role="tab"
                        :class="{ 'is-active': holdYears === y }" @click="holdYears = y"
                    >
                        持有 {{ y }} 年
                    </button>
                </div>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>指標</th>
                            <th v-for="s in STRATEGIES" :key="s.key" class="num">{{ s.name }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in holdingRows" :key="row.label">
                            <td>{{ row.label }}</td>
                            <td
                                v-for="(cell, i) in row.cells" :key="i"
                                class="num" :class="[cell.cls, { best: STRATEGIES[i].key === row.best }]"
                            >
                                {{ cell.text }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p class="panel-note">5 年期的進場點只有約 6 年，彼此高度重疊，統計參考價值有限</p>
        </section>

        <section class="panel" data-nav="各年度報酬">
            <div class="panel-head">
                <h2>各年度報酬</h2>
                <p class="panel-note">空頭年 (2018、2022) 5050 最抗跌；大多頭年 5050 會因為一半是短債而落後 0050</p>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>年度</th>
                            <th v-for="s in STRATEGIES" :key="s.key" class="num">{{ s.name }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in yearRows" :key="row.label">
                            <td>{{ row.label }}</td>
                            <td v-for="(cell, i) in row.cells" :key="i" class="num" :class="cell.cls">
                                {{ cell.text }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel" data-nav="定期定額">
            <div class="panel-head">
                <h2>定期定額：每月 {{ (data.monthly / 1e4).toFixed(0) }} 萬元</h2>
                <p class="panel-note">
                    每月第一個交易日投入，新資金優先買比重最低的資產；比重超出門檻時仍賣出調回目標
                </p>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>指標</th>
                            <th v-for="s in STRATEGIES" :key="s.key" class="num">{{ s.name }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in dcaRows" :key="row.label">
                            <td>{{ row.label }}</td>
                            <td v-for="(cell, i) in row.cells" :key="i" class="num" :class="cell.cls">
                                {{ cell.text }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p class="panel-note">
                淨值最大回撤扣除新資金的影響，等於策略本身的跌幅。前幾年本金小，定期定額能壓低帳面虧損；
                資產變大後每月投入的影響有限，跌幅會接近單筆投入。
                若「只靠新資金補、不賣出」，資產變大後比重會失控：5050 的淨值回撤從
                {{ pct(dca.s5050.nav_mdd) }} 擴大到 {{ pct(dca.s5050_nosell.nav_mdd) }}，
                442 從 {{ pct(dca.s442.nav_mdd) }} 擴大到 {{ pct(dca.s442_nosell.nav_mdd) }}。
            </p>
        </section>

        <section class="panel" data-nav="執行規則">
            <div class="panel-head">
                <h2>執行規則</h2>
            </div>
            <div class="rules">
                <div class="rule">
                    <h3>5050</h3>
                    <ul>
                        <li>00631L 50%、短債 50%，對台股曝險約 1.0 倍</li>
                        <li>00631L 比重跑出 40%~60% 就調回 50/50</li>
                        <li>回測期間共再平衡 {{ stats.s5050.rebalances }} 次</li>
                    </ul>
                </div>
                <div class="rule">
                    <h3>442</h3>
                    <ul>
                        <li>00631L 40%、0050 40%、短債 20%，曝險約 1.2 倍</li>
                        <li>00631L 跑出 32%~48%，或短債跑出 14%~26%，就調回 40/40/20</li>
                        <li>回測期間共再平衡 {{ stats.s442.rebalances }} 次</li>
                    </ul>
                </div>
                <div class="rule">
                    <h3>共同做法</h3>
                    <ul>
                        <li>每月新資金整筆買比重最低的那一檔，減少賣出 (省證交稅)</li>
                        <li>沒觸發門檻就不動，每年檢視一次</li>
                        <li>大跌時照規則賣債買正 2，這是組合優勢的來源</li>
                    </ul>
                </div>
                <div class="rule">
                    <h3>為什麼一定要再平衡</h3>
                    <ul>
                        <li>
                            不再平衡時正 2 比重一路長大：5050 的最大回撤擴大到 {{ pct(stats.s5050_none.mdd) }}，
                            442 擴大到 {{ pct(stats.s442_none.mdd) }}
                        </li>
                        <li>
                            門檻再平衡優於每年固定再平衡：442 年化 {{ pct(stats.s442.cagr) }} 對
                            {{ pct(stats.s442_annual.cagr) }}，5050 年化 {{ pct(stats.s5050.cagr) }} 對
                            {{ pct(stats.s5050_annual.cagr) }}
                        </li>
                        <li>00631L 和 0050 同漲同跌，組合裡要有短債，再平衡才有子彈</li>
                    </ul>
                </div>
            </div>
        </section>

        <section class="panel" data-nav="結論">
            <div class="panel-head">
                <h2>結論</h2>
            </div>
            <div class="verdict">
                <p>
                    <strong>442 是回測中最均衡的選擇。</strong>
                    最大回撤 {{ pct(stats.s442.mdd) }}，只比 0050 多 {{ diff442.mdd }} 個百分點，
                    年化卻多 {{ diff442.cagr }} 個百分點；持有 3 年以上，
                    贏 0050 的機率為 {{ pct(holding["3"].s442.beat_0050) }}。
                </p>
                <p>
                    <strong>5050 適合重視下檔保護的人。</strong>
                    年化 {{ pct(stats.s5050.cagr) }}，和 0050 的 {{ pct(stats.e100.cagr) }} 相近，
                    但最大回撤少 {{ diff5050.mdd }} 個百分點、最長套牢期少約 {{ diff5050.months }} 個月。
                </p>
                <p>
                    <strong>純 00631L 報酬最高，但效率最差。</strong>
                    報酬/波動 {{ stats.l100.sharpe.toFixed(2) }}，是四者最低；高報酬建立在這段期間是趨勢多頭，
                    以及每次腰斬都抱住不賣這兩個前提上。
                </p>
                <p>
                    <strong>純 0050 仍是不想操作時的好選擇。</strong>
                    效率指標和兩個組合差距不大，而且不需要任何再平衡。
                </p>
            </div>
        </section>

        <section class="panel" data-nav="假設與限制">
            <div class="panel-head">
                <h2>假設與限制</h2>
            </div>
            <ul class="notes">
                <li>價格來源為 Yahoo Finance 還原收盤價；0050 配息再投入，未扣稅與二代健保。</li>
                <li>短債以美國 1~3 年公債 ETF (SHY) 換算台幣代替，因為台灣掛牌的短債 ETF 上市太晚；實際內扣費用較高，報酬會略低。</li>
                <li>00631L 在 2015 年 8 月以前的 Yahoo 資料有誤，因此回測從 2015-09-01 開始。</li>
                <li>交易成本：手續費 0.1425% 打 6 折，賣出另計證交稅 0.1%。</li>
                <li>回測期間是台積電帶動的強勢多頭，對有槓桿的配置特別有利；若未來進入長期盤整，正 2 的波動耗損會明顯放大。</li>
                <li>期末數字對結束日很敏感，近期市場波動大，看相對排名即可。</li>
                <li>資料由 scripts/backtest_leverage.py 產生，產生日期 {{ data.generated_at }}。</li>
            </ul>
        </section>

        <p class="page-foot">以上為歷史回測與策略說明，不構成投資建議；過去績效不代表未來表現。</p>
    </section>
</template>

<style scoped>
.head-meta {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
}

.cards {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
}

@media (max-width: 1100px) {
    .cards {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 520px) {
    .cards {
        grid-template-columns: minmax(0, 1fr);
    }
}

.card {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.card.is-rec {
    border-color: var(--series-foreign);
    box-shadow: inset 0 0 0 1px var(--series-foreign);
}

.card-head {
    display: flex;
    align-items: center;
    gap: 8px;
}

.card-swatch {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    flex: none;
}

.card-name {
    font-weight: 600;
    font-size: 15px;
}

.rec-tag {
    padding: 0 8px;
    border-radius: 99px;
    background: var(--series-foreign);
    color: var(--surface-1);
    font-size: 11px;
    font-weight: 600;
}

.card-mix {
    color: var(--text-muted);
    font-size: 12px;
}

.kv {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px 12px;
    margin: 8px 0 0;
    font-size: 13px;
}

.kv dt {
    color: var(--text-secondary);
}

.kv dd {
    margin: 0;
    text-align: right;
    font-variant-numeric: tabular-nums;
}

.card-note {
    margin: 8px 0 0;
    padding-top: 8px;
    border-top: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 12px;
}

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin-bottom: 4px;
    font-size: 12px;
    color: var(--text-secondary);
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.legend-line {
    display: inline-block;
    width: 14px;
    height: 3px;
    border-radius: 2px;
}

.table-title {
    margin-top: 16px;
}

.table-scroll {
    overflow-x: auto;
}

.data-table td.best {
    font-weight: 700;
}

.rules {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
}

@media (max-width: 720px) {
    .rules {
        grid-template-columns: minmax(0, 1fr);
    }
}

.rule {
    padding: 12px 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    min-width: 0;
}

.rule h3 {
    margin: 0 0 4px;
    font-size: 14px;
}

.rule ul,
.notes {
    margin: 0;
    padding-left: 1.2em;
    color: var(--text-secondary);
}

.rule li,
.notes li {
    margin: 3px 0;
}

.verdict {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
    border-radius: 8px;
    background: var(--surface-0);
}

.verdict p {
    margin: 0;
    max-width: 80ch;
}
</style>
