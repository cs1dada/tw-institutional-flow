<script setup lang="ts">
/**
 * 流動性觀察：美元指數 (DXY) × 美債殖利率曲線 (10Y-2Y) 四象限。
 *
 * 美元指數取自 Yahoo Finance，美債 2Y、10Y 殖利率取自 FRED (美國財政部公布值)，
 * 每日排程更新。比較最新一天與 N 個交易日前的變化，判斷目前落在哪個象限，
 * 再對照該情境的驅動主因與各類資產的典型表現。判讀邏輯見 utils/liquidity.ts。
 */
import { computed, onMounted, ref } from "vue"

import { loadLiquidity } from "@/api/dataSource"
import LiquidityChart from "@/components/LiquidityChart.vue"
import { formatDate } from "@/utils/format"
import {
    REGIMES,
    SHAPE_LABEL,
    preparePoints,
    readAt,
    regimeOf,
    regimeSpans,
    type Curve,
    type Dxy,
    type LatestDates,
    type LiquidityPoint,
    type Regime,
} from "@/utils/liquidity"

const LOOKBACKS = [
    { days: 20, label: "近 1 個月" },
    { days: 60, label: "近 3 個月" },
    { days: 120, label: "近 6 個月" },
]

const DXY_LABEL = { up: "走強↑", down: "走弱↓" } as const
const CURVE_LABEL = { steep: "趨陡 (↑)", flat: "趨平 (↓)" } as const

/** 象限排列：列為美元方向，欄為曲線方向 */
const ROWS: Dxy[] = ["up", "down"]
const COLS: Curve[] = ["flat", "steep"]

const points = ref<LiquidityPoint[]>([])
const latest = ref<LatestDates>({ dxy: null, bond: null })
const error = ref("")
const loading = ref(true)
const lookback = ref(20)

onMounted(async () => {
    try {
        const prepared = preparePoints(await loadLiquidity())
        points.value = prepared.points
        latest.value = prepared.latest
    } catch (exc) {
        error.value = exc instanceof Error ? exc.message : String(exc)
    } finally {
        loading.value = false
    }
})

const reading = computed(() => readAt(points.value, points.value.length - 1, lookback.value))
const spans = computed(() => regimeSpans(points.value, lookback.value))

/** 目前情境已持續多久：從最後一段色帶的起點算起 */
const streak = computed(() => {
    const last = spans.value[spans.value.length - 1]
    if (!last) {
        return null
    }
    const start = points.value.findIndex((p) => p.date === last.start)
    return { since: last.start, days: points.value.length - start }
})

const headline = computed(() => {
    const parts = []
    if (latest.value.dxy) {
        parts.push(`美元指數 ${formatDate(latest.value.dxy)}`)
    }
    if (latest.value.bond) {
        parts.push(`美債 ${formatDate(latest.value.bond)}`)
    }
    return parts.length ? `資料日期 (美國時間)：${parts.join("・")}` : ""
})

function signed(value: number, digits = 0): string {
    const text = value.toFixed(digits)
    return value > 0 ? `+${text}` : text
}

function isCurrent(regime: Regime): boolean {
    return reading.value?.regime.id === regime.id
}
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>流動性觀察</h1>
                <p class="subtitle">
                    以美元指數 (DXY) 與美債殖利率曲線 (10Y-2Y) 的方向，判斷全球資金鬆緊與資產輪動
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ headline }}</span>
            </div>
        </header>

        <p v-if="loading" class="notice">載入中…</p>
        <p v-else-if="error" class="notice">資料載入失敗：{{ error }}</p>

        <section v-if="reading" class="panel" data-nav="目前判讀">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>目前判讀</h2>
                    <p class="panel-note">
                        比較 {{ formatDate(reading.to.date) }} 與 {{ lookback }} 個交易日前
                        ({{ formatDate(reading.from.date) }}) 的變化
                    </p>
                </div>
                <div class="tabs" role="tablist">
                    <button
                        v-for="item in LOOKBACKS"
                        :key="item.days"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': lookback === item.days }"
                        role="tab"
                        @click="lookback = item.days"
                    >
                        {{ item.label }}
                    </button>
                </div>
            </div>

            <div class="quote-grid metrics">
                <div class="quote-card">
                    <div class="quote-name">美元指數 (DXY)</div>
                    <div class="quote-value">{{ reading.to.dxy.toFixed(2) }}</div>
                    <div class="quote-meta">{{ signed(reading.dxyPct, 2) }}%，{{ DXY_LABEL[reading.dxy] }}</div>
                </div>
                <div class="quote-card">
                    <div class="quote-name">美債 2Y 殖利率</div>
                    <div class="quote-value">{{ reading.to.us2y.toFixed(2) }}%</div>
                    <div class="quote-meta">{{ signed(reading.us2yBp) }} bp</div>
                </div>
                <div class="quote-card">
                    <div class="quote-name">美債 10Y 殖利率</div>
                    <div class="quote-value">{{ reading.to.us10y.toFixed(2) }}%</div>
                    <div class="quote-meta">{{ signed(reading.us10yBp) }} bp</div>
                </div>
                <div class="quote-card">
                    <div class="quote-name">10Y-2Y 利差</div>
                    <div class="quote-value">{{ signed(reading.to.spread * 100) }} bp</div>
                    <div class="quote-meta">
                        {{ signed(reading.spreadBp) }} bp，{{ CURVE_LABEL[reading.curve] }}
                        <template v-if="reading.to.spread < 0">・倒掛中</template>
                    </div>
                </div>
            </div>

            <div class="verdict" :style="{ '--tone': reading.regime.color, '--tone-bg': reading.regime.background }">
                <div class="verdict-head">
                    <span class="tone-tag">{{ reading.regime.label }}</span>
                    <strong>美元{{ DXY_LABEL[reading.dxy] }} + 殖利率曲線{{ CURVE_LABEL[reading.curve] }}</strong>
                    <span v-if="streak" class="muted">
                        自 {{ formatDate(streak.since) }} 起已持續 {{ streak.days }} 個交易日
                    </span>
                </div>
                <p class="verdict-text">
                    曲線型態為 <strong>{{ SHAPE_LABEL[reading.shape] }}</strong>
                    (2Y {{ signed(reading.us2yBp) }} bp、10Y {{ signed(reading.us10yBp) }} bp)。
                    {{ reading.regime.liquidity }}
                </p>
                <p v-if="!reading.typical" class="verdict-warn">
                    注意：這個象限的典型情境是{{ SHAPE_LABEL[reading.regime.shape] }}
                    ({{ reading.regime.curveDetail }})，目前實際為{{ SHAPE_LABEL[reading.shape] }}，
                    驅動因素可能不同，資產表現不一定照典型情境走。
                </p>
                <p v-if="reading.weak" class="verdict-warn">
                    美元變動不到 0.5% 或利差變動不到 5 bp，方向不明顯，建議改看較長的期間交叉確認。
                </p>
            </div>
        </section>

        <section v-if="points.length" class="panel" data-nav="走勢圖">
            <div class="panel-head">
                <h2>走勢與歷史情境</h2>
                <p class="panel-note">
                    美元指數的底色為每天以「{{ LOOKBACKS.find((x) => x.days === lookback)?.label }}」判讀出的情境；
                    下方縮放條可拖動查看近五年
                </p>
            </div>
            <div class="legend">
                <span v-for="r in REGIMES" :key="r.id" class="legend-item">
                    <span class="legend-swatch" :style="{ background: r.color }" />{{ r.label }}
                </span>
            </div>
            <LiquidityChart :points="points" :spans="spans" :from-date="reading?.from.date ?? null" />
        </section>

        <section class="panel" data-nav="四象限">
            <div class="panel-head">
                <h2>四象限總覽</h2>
                <p class="panel-note">
                    橫軸為殖利率曲線 (10Y-2Y 利差) 變化，縱軸為美元指數方向；外框加粗的是目前所在象限
                </p>
            </div>

            <div class="matrix">
                <div class="axis-corner" />
                <div v-for="col in COLS" :key="col" class="axis-col">
                    殖利率曲線 {{ CURVE_LABEL[col] }}
                </div>
                <template v-for="row in ROWS" :key="row">
                    <div class="axis-row">美元{{ DXY_LABEL[row] }}</div>
                    <article
                        v-for="regime in [regimeOf(row, COLS[0]), regimeOf(row, COLS[1])]"
                        :key="regime.id"
                        class="cell"
                        :class="{ 'is-current': isCurrent(regime) }"
                        :style="{ '--tone': regime.color, '--tone-bg': regime.background }"
                    >
                        <div class="cell-top">
                            <span class="tone-tag">{{ regime.label }}</span>
                            <span class="curve-name">{{ SHAPE_LABEL[regime.shape] }}</span>
                            <span v-if="isCurrent(regime)" class="current-mark">目前</span>
                        </div>
                        <p class="cell-detail">{{ regime.curveDetail }}</p>
                        <p class="cell-driver">{{ regime.driver }}</p>
                        <div class="assets">
                            <div class="asset-line">
                                <span class="asset-label">相對抗跌</span>
                                <span>{{ regime.winners.join("、") }}</span>
                            </div>
                            <div class="asset-line">
                                <span class="asset-label">相對承壓</span>
                                <span>{{ regime.losers.join("、") }}</span>
                            </div>
                        </div>
                    </article>
                </template>
            </div>
        </section>

        <section class="panel" data-nav="對照表">
            <div class="panel-head">
                <h2>對照表</h2>
                <p class="panel-note">驅動主因、宏觀定價與流動性狀態的完整說明</p>
            </div>
            <div class="table-wrap">
                <table class="data-table regime-table">
                    <thead>
                        <tr>
                            <th>美元指數 (DXY)</th>
                            <th>美債殖利率曲線 (10Y-2Y)</th>
                            <th>驅動主因與宏觀定價</th>
                            <th>流動性狀態與資產表現</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="r in REGIMES"
                            :key="r.id"
                            :class="{ 'is-current': isCurrent(r) }"
                            :style="{ '--tone': r.color }"
                        >
                            <td>{{ r.dxy === "up" ? "走強 (↑)" : "走弱 (↓)" }}</td>
                            <td>
                                {{ r.curve === "steep" ? "走強 (↑)" : "走弱 (↓)" }}：{{ r.curveDetail }}
                                <div class="muted">{{ SHAPE_LABEL[r.shape] }}</div>
                            </td>
                            <td>{{ r.driver }}</td>
                            <td>
                                <span class="tone-tag">{{ r.label }}</span>
                                {{ r.liquidity }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="panel" data-nav="判讀說明">
            <div class="panel-head">
                <h2>判讀說明</h2>
            </div>
            <ol class="steps">
                <li>
                    <strong>看美元方向</strong>：DXY 在期間內上漲為走強、下跌為走弱，反映全球美元資金是回流美國還是外溢。
                </li>
                <li>
                    <strong>看曲線方向</strong>：10Y-2Y 利差擴大為趨陡、縮小為趨平。
                </li>
                <li>
                    <strong>看哪一端在動</strong>：2Y 與 10Y 平均上升為「熊市」、平均下降為「牛市」；
                    短端 (2Y) 反映聯準會政策預期，長端 (10Y) 反映成長、通膨與期限溢價。
                </li>
                <li>
                    <strong>對照象限</strong>：找到所在情境後，留意相對抗跌與相對承壓的資產，調整部位風險。
                    建議同時看 1 個月與 3 個月，兩者一致時訊號較可靠。
                </li>
            </ol>
            <p class="notice">
                資料來源：美元指數為 Yahoo Finance (ICE 美元指數 DX-Y.NYB)，美債殖利率為 FRED
                (美國財政部固定期限殖利率 DGS2、DGS10，通常晚一個交易日公布)，日期皆為美國時間。
                四象限為宏觀情境的典型對應，實際走勢仍會受個別事件、資金部位與估值水準影響，僅供觀察參考。
            </p>
        </section>
    </section>
</template>

<style scoped>
.metrics {
    margin-bottom: 14px;
}

.verdict {
    padding: 14px 16px;
    border: 1px solid var(--border);
    border-left: 4px solid var(--tone);
    border-radius: 8px;
    background: var(--tone-bg);
}

.verdict-head {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 10px;
    align-items: center;
    font-size: 15px;
}

.verdict-text {
    margin: 8px 0 0;
    color: var(--text-secondary);
}

.verdict-warn {
    margin: 8px 0 0;
    padding: 6px 10px;
    border-radius: 6px;
    background: var(--surface-1);
    color: var(--text-secondary);
    font-size: 13px;
}

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin-bottom: 4px;
    color: var(--text-secondary);
    font-size: 12px;
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.legend-swatch {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    opacity: 0.5;
}

.matrix {
    display: grid;
    grid-template-columns: auto 1fr 1fr;
    gap: 10px;
}

.axis-col,
.axis-row {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 600;
}

.axis-row {
    padding: 0 6px;
    writing-mode: vertical-rl;
    text-orientation: upright;
    letter-spacing: 0.08em;
}

.cell {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    border: 1px solid var(--border);
    border-top: 4px solid var(--tone);
    border-radius: 8px;
    background: var(--tone-bg);
    opacity: 0.72;
}

.cell.is-current {
    border: 2px solid var(--tone);
    border-top-width: 4px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
    opacity: 1;
}

.current-mark {
    margin-left: auto;
    color: var(--tone);
    font-size: 12px;
    font-weight: 700;
}

.cell-top {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 10px;
    align-items: center;
}

.tone-tag {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--tone);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
}

.curve-name {
    color: var(--text-secondary);
    font-size: 12px;
}

.cell-detail {
    margin: 0;
    font-weight: 600;
}

.cell-driver {
    margin: 0;
    color: var(--text-secondary);
    font-size: 13px;
}

.assets {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: auto;
    padding-top: 8px;
    border-top: 1px dashed var(--border);
    font-size: 13px;
}

.asset-line {
    display: flex;
    gap: 8px;
}

.asset-label {
    flex: none;
    color: var(--text-muted);
}

.regime-table td {
    white-space: normal;
    vertical-align: top;
    line-height: 1.6;
}

.regime-table td:nth-child(1) {
    white-space: nowrap;
}

.regime-table td:nth-child(2) {
    min-width: 180px;
}

.regime-table tr.is-current td {
    background: var(--surface-0);
}

.regime-table tr.is-current td:first-child {
    box-shadow: inset 4px 0 0 var(--tone);
}

.regime-table .tone-tag {
    margin-right: 4px;
}

.muted {
    color: var(--text-muted);
    font-size: 12px;
}

.steps {
    margin: 0 0 12px;
    padding-left: 22px;
    line-height: 1.9;
}

.tab {
    white-space: nowrap;
}

@media (max-width: 900px) {
    .panel-head-row {
        flex-wrap: wrap;
    }

    .metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .matrix {
        grid-template-columns: 1fr;
    }

    .axis-corner,
    .axis-col {
        display: none;
    }

    .axis-row {
        justify-content: flex-start;
        padding: 6px 0 0;
        writing-mode: horizontal-tb;
    }
}
</style>
