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
import AssetCompareChart from "@/components/AssetCompareChart.vue"
import LiquidityChart from "@/components/LiquidityChart.vue"
import { formatDate } from "@/utils/format"
import {
    ASSETS,
    REGIMES,
    SHAPE_LABEL,
    describeMove,
    describeTwdGap,
    twdDeviation,
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
const ROW_LABEL = { up: "美元漲", down: "美元跌" } as const
const COL_LABEL = { flat: "利差縮小 (趨平)", steep: "利差擴大 (趨陡)" } as const

const points = ref<LiquidityPoint[]>([])
const latest = ref<LatestDates>({ dxy: null, bond: null })
const error = ref("")
const loading = ref(true)
// 預設看近 3 個月：1 個月的訊號雜訊較多，6 個月又太慢
const lookback = ref(60)

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
const deviation = computed(() => twdDeviation(points.value, lookback.value))
/** 最新一天的台幣偏離 */
const twdGap = computed(() => deviation.value.values[deviation.value.values.length - 1] ?? null)
const periodLabel = computed(() => LOOKBACKS.find((x) => x.days === lookback.value)?.label ?? "")
/** 資產比較的區間 (交易日數)，null 為全部資料 */
const ASSET_RANGES = [
    { days: 60, label: "近 3 個月" },
    { days: 250, label: "近 1 年" },
    { days: 750, label: "近 3 年" },
    { days: null, label: "全部" },
] as const
const assetRange = ref<number | null>(250)
const assetPoints = computed(() =>
    assetRange.value == null ? points.value : points.value.slice(-assetRange.value - 1),
)

/** 區間摘要：利差從多少變到多少、哪項資產漲最多與最少 */
const assetSummary = computed(() => {
    const list = assetPoints.value
    if (list.length < 2) {
        return null
    }
    const first = list[0]
    const last = list[list.length - 1]
    const ranked = ASSETS.map((asset) => {
        const base = list.find((p) => p.assets[asset.id] != null)?.assets[asset.id]
        const now = last.assets[asset.id]
        return { asset, pct: base != null && now != null ? ((now - base) / base) * 100 : null }
    })
        .filter((r): r is { asset: (typeof ASSETS)[number]; pct: number } => r.pct != null)
        .sort((a, b) => b.pct - a.pct)
    const dxyPct = ((last.dxy - first.dxy) / first.dxy) * 100
    const spreadFrom = Math.round(first.spread * 100)
    const spreadTo = Math.round(last.spread * 100)
    return {
        from: first.date,
        dxyPct,
        spreadFrom,
        spreadTo,
        spreadDiff: spreadTo - spreadFrom,
        best: ranked[0],
        worst: ranked[ranked.length - 1],
    }
})

/** 捲到「四種情境」區塊；區塊 id 由左側選單動態編號，所以用 data-nav 找 */
function jumpToRegimes() {
    document.querySelector('[data-nav="四種情境"]')?.scrollIntoView({ behavior: "smooth", block: "start" })
}

function percent(value: number | null, digits = 1): string {
    if (value == null) {
        return "-"
    }
    // 四捨五入後為 0 時不顯示負號，避免出現 -0.0%
    const rounded = Number(value.toFixed(digits))
    return `${signed(rounded === 0 ? 0 : rounded, digits)}%`
}

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
                    <div class="quote-name">美元兌新台幣</div>
                    <div class="quote-value">{{ reading.to.usdtwd?.toFixed(2) ?? "-" }}</div>
                    <div class="quote-meta">
                        <template v-if="reading.twdPct != null">
                            {{ signed(reading.twdPct, 2) }}%，台幣{{ reading.twdPct >= 0 ? "貶值" : "升值" }}
                        </template>
                        <div v-if="twdGap != null">
                            偏離 {{ signed(twdGap, 2) }}%，{{ describeTwdGap(twdGap) }}
                        </div>
                    </div>
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
                    <strong class="verdict-title">{{ reading.regime.headline }}</strong>
                    <button type="button" class="note-toggle regime-jump" @click="jumpToRegimes">
                        四種情境說明 ↓
                    </button>
                </div>
                <p class="verdict-text">{{ reading.regime.story }}</p>
                <p class="verdict-text"><strong>對台股：</strong>{{ reading.regime.taiwan }}</p>
                <p class="verdict-basis">
                    判斷依據：美元{{ DXY_LABEL[reading.dxy] }} ({{ signed(reading.dxyPct, 2) }}%)，
                    10Y-2Y 利差{{ CURVE_LABEL[reading.curve] }} ({{ signed(reading.spreadBp) }} bp)
                    <template v-if="streak">
                        ・自 {{ formatDate(streak.since) }} 起已持續 {{ streak.days }} 個交易日
                    </template>
                </p>
                <p v-if="!reading.typical" class="verdict-warn">
                    注意：這次和典型情況不完全一樣。典型的「{{ reading.regime.label }}」是{{ reading.regime.curveDetail }}，
                    這次卻是{{ describeMove(reading.us2yBp, reading.us10yBp) }}，背後原因可能不同，參考價值要打點折扣。
                </p>
                <p v-if="reading.weak" class="verdict-warn">
                    這段期間美元或利差變化很小 (美元不到 0.5% 或利差不到 5 bp)，方向不明確，建議切換到較長的期間一起看。
                </p>
            </div>
        </section>

        <section v-if="points.length" class="panel" data-nav="資產影響">
            <div class="panel-head panel-head-row">
                <div>
                    <h2>對資產的影響：美股、台股、比特幣、黃金</h2>
                    <p class="panel-note">
                        四項資產都從區間第一天算漲跌幾 %，放在同一張圖比較；下方是同期間的美元指數與利差
                    </p>
                </div>
                <div class="tabs" role="tablist">
                    <button
                        v-for="item in ASSET_RANGES"
                        :key="item.label"
                        type="button"
                        class="tab"
                        :class="{ 'is-active': assetRange === item.days }"
                        role="tab"
                        @click="assetRange = item.days"
                    >
                        {{ item.label }}
                    </button>
                </div>
            </div>

            <p v-if="assetSummary" class="asset-hint">
                從 {{ formatDate(assetSummary.from) }} 到現在，美元指數{{ assetSummary.dxyPct >= 0 ? "漲" : "跌" }}
                {{ percent(Math.abs(assetSummary.dxyPct)).replace("+", "") }}，利差從 {{ assetSummary.spreadFrom }} bp 變成
                {{ assetSummary.spreadTo }} bp
                ({{ assetSummary.spreadDiff >= 0 ? "擴大" : "縮小" }} {{ Math.abs(assetSummary.spreadDiff) }} bp)；
                漲最多的是 <strong>{{ assetSummary.best.asset.label }}</strong> ({{ percent(assetSummary.best.pct) }})，
                最少的是 <strong>{{ assetSummary.worst.asset.label }}</strong> ({{ percent(assetSummary.worst.pct) }})。
            </p>

            <div class="legend">
                <span class="legend-caption">上方色帶＝情境 (以{{ periodLabel }}判讀)：</span>
                <span v-for="r in REGIMES" :key="r.id" class="legend-item">
                    <span class="legend-swatch" :style="{ background: r.color }" />{{ r.label }}
                </span>
            </div>
            <AssetCompareChart :points="assetPoints" :spans="spans" />

            <p class="panel-note asset-note">
                怎麼看：最上方色帶是當時的情境 (美元方向 + 利差方向)，對照同一段時間四條線誰漲誰跌；
                下方兩格看美元和利差實際怎麼走。色帶的判讀期間跟著頁面最上方「目前判讀」的選項切換。
                滑鼠移到圖上可以看當天的情境與各資產漲跌。
            </p>
        </section>

        <section v-if="points.length" class="panel" data-nav="美元與利率">
            <div class="panel-head">
                <h2>美元與利率走勢</h2>
                <p class="panel-note">
                    美元指數的底色為每天以「{{ periodLabel }}」判讀出的情境；
                    台幣偏離為台幣實際漲跌扣掉「依美元指數推算的漲跌」，紅色為台幣偏弱、藍色為偏強；
                    下方縮放條可拖動查看近五年
                </p>
            </div>
            <div class="legend">
                <span v-for="r in REGIMES" :key="r.id" class="legend-item">
                    <span class="legend-swatch" :style="{ background: r.color }" />{{ r.label }}
                </span>
            </div>
            <LiquidityChart
                :points="points"
                :spans="spans"
                :from-date="reading?.from.date ?? null"
                :twd-gap="deviation.values"
                :period-label="periodLabel"
            />
        </section>

        <section class="panel" data-nav="四種情境">
            <div class="panel-head">
                <h2>四種情境</h2>
                <p class="panel-note">
                    依「美元漲或跌」和「長短天期利差變大或變小」組合成四種情境；外框加粗的是目前所在情境
                </p>
            </div>

            <div class="matrix">
                <div class="axis-corner" />
                <div v-for="col in COLS" :key="col" class="axis-col">{{ COL_LABEL[col] }}</div>
                <template v-for="row in ROWS" :key="row">
                    <div class="axis-row">{{ ROW_LABEL[row] }}</div>
                    <article
                        v-for="regime in [regimeOf(row, COLS[0]), regimeOf(row, COLS[1])]"
                        :key="regime.id"
                        class="cell"
                        :class="{ 'is-current': isCurrent(regime) }"
                        :style="{ '--tone': regime.color, '--tone-bg': regime.background }"
                    >
                        <div class="cell-top">
                            <span class="tone-tag">{{ regime.label }}</span>
                            <span v-if="isCurrent(regime)" class="current-mark">目前</span>
                        </div>
                        <p class="cell-title">{{ regime.headline }}</p>
                        <p class="cell-text">{{ regime.story }}</p>
                        <p class="cell-text"><strong>對台股：</strong>{{ regime.taiwan }}</p>
                        <div class="assets">
                            <div class="asset-line">
                                <span class="asset-label">比較撐得住</span>
                                <span>{{ regime.winners.join("、") }}</span>
                            </div>
                            <div class="asset-line">
                                <span class="asset-label">比較容易跌</span>
                                <span>{{ regime.losers.join("、") }}</span>
                            </div>
                        </div>
                        <details class="cell-more">
                            <summary>專業說明</summary>
                            <p>
                                曲線型態：{{ SHAPE_LABEL[regime.shape] }}，{{ regime.curveDetail }}。
                            </p>
                            <p>{{ regime.driver }}</p>
                            <p>{{ regime.liquidity }}</p>
                        </details>
                    </article>
                </template>
            </div>
        </section>

        <section class="panel" data-nav="怎麼看">
            <div class="panel-head">
                <h2>這頁怎麼算</h2>
            </div>
            <ol class="steps">
                <li>
                    <strong>美元</strong>：比較今天和一段時間前的美元指數，漲了算「走強」(錢回流美國)，
                    跌了算「走弱」(錢流向其他市場)。美元兌新台幣只當對照，不影響情境判斷。
                </li>
                <li>
                    <strong>利差</strong>：10 年期減 2 年期美債殖利率，差距變大算「趨陡」，變小算「趨平」。
                </li>
                <li>
                    <strong>對照情境</strong>：兩者組合落在上面四種情境之一。最上方可切換比較 1、3、6 個月；
                    1 個月和 3 個月結果一致時比較可信。
                </li>
                <li>
                    <strong>怎麼用</strong>：當作大環境的風向參考，不是買賣訊號。例如資金偏緊時，外資賣超台股比較合理；
                    轉為寬鬆時，可以留意外資是否開始回補。
                </li>
            </ol>

            <h3 class="glossary-title">名詞小辭典</h3>
            <dl class="glossary">
                <dt>美元指數 (DXY)</dt>
                <dd>美元對歐元、日圓等六種主要貨幣的強弱，數字越大代表美元越強。</dd>
                <dt>美元兌新台幣</dt>
                <dd>
                    1 美元可以換多少新台幣。數字變大代表台幣貶值，常見於外資賣台股、把台幣換回美元的時候；
                    數字變小代表台幣升值。
                </dd>
                <dt>台幣偏離</dt>
                <dd>
                    台幣通常只反映美元指數一部分的漲跌 (目前估計美元指數漲 1%，台幣約貶 {{ deviation.beta.toFixed(2) }}%)。
                    偏離是台幣實際漲跌扣掉這部分後剩下的，代表台灣自己的因素。
                    正值 (紅色) 表示台幣比推算的弱，常見於資金流出台灣或央行壓抑升值；
                    負值 (藍色) 表示台幣比推算的強，常見於資金流入台灣或央行壓抑貶值。
                </dd>
                <dt>殖利率</dt>
                <dd>買美國公債每年拿到的報酬率，可以看成「借美元的成本」。殖利率上升，借錢就變貴。</dd>
                <dt>2Y／10Y</dt>
                <dd>2 年期與 10 年期美國公債。2Y 主要跟著聯準會的利率預期走，10Y 反映對長期經濟與通膨的看法。</dd>
                <dt>利差 (10Y-2Y)</dt>
                <dd>10Y 減 2Y。正常時長天期利率較高、利差為正；變成負數叫「倒掛」，常被視為經濟衰退的警訊。</dd>
                <dt>bp (基點)</dt>
                <dd>0.01 個百分點。例如殖利率從 4.00% 升到 4.25%，就是上升 25 bp。</dd>
                <dt>趨平／趨陡</dt>
                <dd>利差縮小叫趨平，利差擴大叫趨陡。</dd>
                <dt>熊市／牛市 (債券用語)</dt>
                <dd>殖利率整體上升 (債券價格下跌) 叫熊市，整體下降叫牛市，和股市的牛熊無關。</dd>
                <dt>聯準會 (Fed)</dt>
                <dd>美國央行，負責決定美國的基準利率。</dd>
            </dl>

            <p class="notice">
                資料來源：美元指數為 Yahoo Finance (ICE 美元指數 DX-Y.NYB)，美債殖利率為 FRED
                (美國財政部固定期限殖利率 DGS2、DGS10，通常晚一個交易日公布)，日期皆為美國時間。
                四種情境是常見的典型對應，實際走勢仍會受個別事件、資金部位與估值影響，僅供觀察參考。
            </p>
        </section>
    </section>
</template>

<style scoped>
.metrics {
    grid-template-columns: repeat(5, minmax(0, 1fr));
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

.regime-jump {
    margin-left: auto;
}

.verdict-title {
    font-size: 17px;
}

.verdict-text {
    margin: 8px 0 0;
    color: var(--text);
    line-height: 1.7;
}

.verdict-basis {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 13px;
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

.legend-caption {
    color: var(--text-muted);
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

.cell-title {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
}

.cell-text {
    margin: 0;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

.cell-more {
    color: var(--text-secondary);
    font-size: 12px;
}

.cell-more summary {
    color: var(--text-muted);
    cursor: pointer;
}

.cell-more p {
    margin: 6px 0 0;
    line-height: 1.6;
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

.asset-hint {
    margin: 0 0 12px;
    line-height: 1.8;
}

.asset-note {
    margin: 6px 0 0;
    line-height: 1.7;
}

.muted {
    color: var(--text-muted);
    font-size: 12px;
}

.glossary-title {
    margin: 4px 0 8px;
    font-size: 15px;
}

.glossary {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 16px;
    margin: 0 0 14px;
    font-size: 13px;
    line-height: 1.7;
}

.glossary dt {
    font-weight: 600;
}

.glossary dd {
    margin: 0;
    color: var(--text-secondary);
}

.steps {
    margin: 0 0 16px;
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

    /* 五張卡在兩欄時最後一張獨佔一列 */
    .metrics .quote-card:last-child {
        grid-column: 1 / -1;
    }

    .matrix {
        grid-template-columns: 1fr;
    }

    .glossary {
        grid-template-columns: 1fr;
        gap: 2px;
    }

    .glossary dd {
        margin-bottom: 6px;
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
