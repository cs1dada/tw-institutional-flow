<script setup lang="ts">
/**
 * 大盤指標卡：加權與櫃買指數、三大法人、融資融券與維持率、匯率與 VIX。
 *
 * 各指標的公布時間不同 (法人 15:00、融資晚間、美股隔天清晨)，
 * 因此每張卡各自標示資料日期，不假設它們是同一天。
 */
import { computed } from "vue"

import type { IndexRow, MarketPayload } from "@/types"
import { expandRows } from "@/utils/indexBars"
import {
    MARKET_LABELS,
    expandChip,
    expandCredit,
    latestOf,
    latestPoint,
    maintenanceLevel,
    officialLevel,
    vixLevel,
    type Latest,
    type Level,
    type MarketKey,
} from "@/utils/market"

const props = defineProps<{
    taiex: IndexRow[]
    market: MarketPayload | null
}>()

const MARKETS: MarketKey[] = ["TWSE", "TPEX"]
const TURNOVER_AVG_DAYS = 5

interface IndexCard {
    date: string
    close: number
    change: number | null
    pct: number | null
}

function indexCard(rows: IndexRow[]): IndexCard | null {
    const last = rows[rows.length - 1]
    if (!last) {
        return null
    }
    const prev = rows[rows.length - 2]
    const change = last.change ?? (prev ? last.close - prev.close : null)
    const base = change === null ? null : last.close - change
    return {
        date: last.date,
        close: last.close,
        change,
        pct: change === null || !base ? null : (change / base) * 100,
    }
}

const taiexCard = computed(() => indexCard(props.taiex))

const tpexCard = computed(() =>
    props.market ? indexCard(expandRows(props.market.tpex_index)) : null,
)

/** 今日成交金額與前 5 日均量的比較 */
const turnover = computed(() => {
    const rows = props.taiex
    if (rows.length < TURNOVER_AVG_DAYS + 1) {
        return null
    }
    const last = rows[rows.length - 1]
    const prior = rows.slice(-TURNOVER_AVG_DAYS - 1, -1)
    const avg = prior.reduce((sum, row) => sum + row.turnover, 0) / prior.length
    return { value: last.turnover, pct: avg ? (last.turnover / avg - 1) * 100 : null }
})

const chips = computed(() => {
    const payload = props.market
    return MARKETS.map((key) => {
        const rows = payload ? expandChip(payload, key) : []
        return {
            key,
            label: MARKET_LABELS[key],
            inst: [
                { label: "外資", item: latestOf(rows, "foreign") },
                { label: "投信", item: latestOf(rows, "trust") },
                { label: "自營商", item: latestOf(rows, "dealer") },
                { label: "合計", item: latestOf(rows, "total") },
            ],
            margin: latestOf(rows, "margin"),
            maintenance: latestOf(rows, "maintenance"),
            short: latestOf(rows, "short_units"),
        }
    })
})

/** 官方全市場擔保維持率與追繳戶數，兩張融資卡都顯示同一組 */
const official = computed(() => {
    const rows = props.market ? expandCredit(props.market) : []
    return rows.length ? rows[rows.length - 1] : null
})

/**
 * 法人卡的長條以該市場自己最大的絕對值為基準。
 * 上櫃的金額通常只有上市的幾十分之一，共用比例尺會短到看不見
 */
function instScale(inst: { item: Latest | null }[]): number {
    return Math.max(...inst.map((row) => Math.abs(row.item?.value ?? 0))) || 1
}

const macro = computed(() => {
    const data = props.market?.macro
    const usdtwd = latestPoint(data?.USDTWD)
    const twVix = latestPoint(data?.TWVIX)
    const usVix = latestPoint(data?.USVIX)
    return {
        usdtwd,
        twVix,
        twVixLevel: twVix ? vixLevel(twVix.value, "TW") : null,
        usVix,
        usVixLevel: usVix ? vixLevel(usVix.value, "US") : null,
    }
})

function shortDate(date: string | undefined): string {
    return date ? `${Number(date.slice(4, 6))}/${Number(date.slice(6, 8))}` : ""
}

function fmt(value: number, digits = 2): string {
    return value.toLocaleString("zh-TW", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    })
}

function signedFmt(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return (value > 0 ? "+" : "") + fmt(value, digits)
}

/** 漲跌方向的 class：台股慣例紅漲綠跌 */
function tone(value: number | null | undefined): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}

function arrow(value: number | null | undefined): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "▲" : "▼"
}

function barStyle(item: Latest | null, scale: number) {
    const value = item?.value ?? 0
    const width = (Math.abs(value) / scale) * 50
    return {
        width: `${width}%`,
        left: value >= 0 ? "50%" : `${50 - width}%`,
    }
}

function levelClass(level: Level | null): string {
    return level ? `level level-${level.tone}` : "level"
}
</script>

<template>
    <!-- 標上 data-nav，左側捷徑才跳得回頁首的總覽 -->
    <section class="overview" data-nav="市場總覽">
        <div class="tile">
            <div class="tile-head">
                <span class="tile-title">加權指數</span>
                <span class="tile-date">{{ shortDate(taiexCard?.date) }}</span>
            </div>
            <template v-if="taiexCard">
                <div class="tile-value">{{ fmt(taiexCard.close) }}</div>
                <div class="tile-sub" :class="tone(taiexCard.change)">
                    {{ arrow(taiexCard.change) }} {{ signedFmt(taiexCard.change) }}（{{ signedFmt(taiexCard.pct) }}%）
                </div>
                <div v-if="turnover" class="tile-foot">
                    成交 {{ fmt(turnover.value, 0) }} 億
                    <span :class="tone(turnover.pct)">較前 5 日均量 {{ signedFmt(turnover.pct, 0) }}%</span>
                </div>
            </template>
            <div v-else class="tile-empty">尚無資料</div>
        </div>

        <div class="tile">
            <div class="tile-head">
                <span class="tile-title">櫃買指數</span>
                <span class="tile-date">{{ shortDate(tpexCard?.date) }}</span>
            </div>
            <template v-if="tpexCard">
                <div class="tile-value">{{ fmt(tpexCard.close) }}</div>
                <div class="tile-sub" :class="tone(tpexCard.change)">
                    {{ arrow(tpexCard.change) }} {{ signedFmt(tpexCard.change) }}（{{ signedFmt(tpexCard.pct) }}%）
                </div>
            </template>
            <div v-else class="tile-empty">尚無資料</div>
        </div>

        <div v-for="chip in chips" :key="`margin-${chip.key}`" class="tile">
            <div class="tile-head">
                <span class="tile-title">{{ chip.label }}融資</span>
                <span class="tile-date">{{ shortDate(chip.margin?.date) }}</span>
            </div>
            <template v-if="chip.margin">
                <div class="tile-value">
                    {{ fmt(chip.margin.value, 0) }}<span class="unit">億</span>
                </div>
                <div class="tile-sub" :class="tone(chip.margin.diff)">
                    {{ arrow(chip.margin.diff) }} {{ signedFmt(chip.margin.diff, 1) }} 億
                </div>
                <div class="tile-foot">
                    <template v-if="chip.maintenance">
                        維持率 <strong>{{ fmt(chip.maintenance.value) }}%</strong>
                        <span :class="levelClass(maintenanceLevel(chip.maintenance.value))">
                            {{ maintenanceLevel(chip.maintenance.value).label }}
                        </span>
                    </template>
                </div>
                <div v-if="official?.keep_rate != null" class="tile-foot">
                    官方全市場 <strong>{{ fmt(official.keep_rate) }}%</strong>
                    <span :class="levelClass(officialLevel(official.keep_rate))">
                        {{ officialLevel(official.keep_rate).label }}
                    </span>
                    <span v-if="official.below_acc != null">追繳 {{ fmt(official.below_acc, 0) }} 戶</span>
                </div>
                <div v-if="chip.short" class="tile-foot">
                    融券 {{ fmt(chip.short.value, 0) }} 張
                    <span :class="tone(chip.short.diff)">{{ signedFmt(chip.short.diff, 0) }}</span>
                </div>
            </template>
            <div v-else class="tile-empty">尚無資料</div>
        </div>

        <div class="tile">
            <div class="tile-head">
                <span class="tile-title">美元／台幣</span>
                <span class="tile-date">{{ shortDate(macro.usdtwd?.date) }}</span>
            </div>
            <template v-if="macro.usdtwd">
                <div class="tile-value">{{ fmt(macro.usdtwd.value, 3) }}</div>
                <!-- 匯價上升代表台幣貶值，顏色一律依數值方向：上升紅、下降綠 -->
                <div class="tile-sub" :class="tone(macro.usdtwd.diff)">
                    {{ arrow(macro.usdtwd.diff) }} {{ signedFmt(macro.usdtwd.diff, 3) }}
                    {{ (macro.usdtwd.diff ?? 0) > 0 ? "台幣貶值" : (macro.usdtwd.diff ?? 0) < 0 ? "台幣升值" : "" }}
                </div>
            </template>
            <div v-else class="tile-empty">尚無資料</div>
        </div>

        <div v-for="chip in chips" :key="`inst-${chip.key}`" class="tile tile-wide">
            <div class="tile-head">
                <span class="tile-title">{{ chip.label }}三大法人（億）</span>
                <span class="tile-date">{{ shortDate(chip.inst[3].item?.date) }}</span>
            </div>
            <div v-if="chip.inst[3].item" class="inst-list">
                <div
                    v-for="row in chip.inst"
                    :key="row.label"
                    class="inst-row"
                    :class="{ 'inst-total': row.label === '合計' }"
                >
                    <span class="inst-label">{{ row.label }}</span>
                    <span class="inst-track">
                        <span
                            class="inst-bar"
                            :class="(row.item?.value ?? 0) >= 0 ? 'bar-buy' : 'bar-sell'"
                            :style="barStyle(row.item, instScale(chip.inst))"
                        />
                    </span>
                    <span class="inst-value" :class="tone(row.item?.value)">
                        {{ signedFmt(row.item?.value, 1) }}
                    </span>
                </div>
            </div>
            <div v-else class="tile-empty">尚無資料</div>
        </div>

        <div class="tile">
            <div class="tile-head">
                <span class="tile-title">恐慌指標 VIX</span>
            </div>
            <div class="vix-row">
                <span class="vix-name">台指<em>{{ shortDate(macro.twVix?.date) }}</em></span>
                <template v-if="macro.twVix">
                    <strong class="vix-value">{{ fmt(macro.twVix.value) }}</strong>
                    <span class="vix-diff" :class="tone(macro.twVix.diff)">{{ signedFmt(macro.twVix.diff) }}</span>
                    <span :class="levelClass(macro.twVixLevel)">{{ macro.twVixLevel?.label }}</span>
                </template>
                <span v-else class="tile-empty">尚無資料</span>
            </div>
            <div class="vix-row">
                <span class="vix-name">美國<em>{{ shortDate(macro.usVix?.date) }}</em></span>
                <template v-if="macro.usVix">
                    <strong class="vix-value">{{ fmt(macro.usVix.value) }}</strong>
                    <span class="vix-diff" :class="tone(macro.usVix.diff)">{{ signedFmt(macro.usVix.diff) }}</span>
                    <span :class="levelClass(macro.usVixLevel)">{{ macro.usVixLevel?.label }}</span>
                </template>
                <span v-else class="tile-empty">尚無資料</span>
            </div>
            <div class="tile-foot">美國 VIX 為前一晚美股收盤</div>
        </div>
    </section>
</template>

<style scoped>
/*
 * 卡片剛好排成兩列五欄：第一列五張單欄卡，第二列兩張雙欄法人卡加 VIX。
 * 用 auto-fill 的話寬螢幕會多出第六欄，右側留下一整條空白，因此依寬度明訂欄數。
 */
.overview {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}

@media (max-width: 1100px) {
    .overview {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 520px) {
    .overview {
        grid-template-columns: minmax(0, 1fr);
    }
}

.tile {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: 12px 14px;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 8px;
}

.vix-row {
    display: grid;
    grid-template-columns: 64px auto 1fr auto;
    align-items: baseline;
    gap: 8px;
    margin-top: 4px;
    font-variant-numeric: tabular-nums;
}

.vix-name {
    color: var(--text-secondary);
    font-size: 13px;
}

.vix-name em {
    margin-left: 4px;
    color: var(--text-muted);
    font-size: 11px;
    font-style: normal;
}

.vix-value {
    font-size: 20px;
}

.vix-diff {
    font-size: 13px;
}

.tile-wide {
    grid-column: span 2;
}

@media (max-width: 520px) {
    .tile-wide {
        grid-column: span 1;
    }
}

.tile-head {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    color: var(--text-secondary);
    font-size: 12px;
}

.tile-date {
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
}

.tile-value {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 24px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1.3;
}

.unit {
    margin-left: 2px;
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 400;
}

.tile-sub {
    font-size: 13px;
    font-variant-numeric: tabular-nums;
}

.tile-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px;
    color: var(--text-secondary);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}

.tile-empty {
    padding: 8px 0;
    color: var(--text-muted);
    font-size: 13px;
}

.inst-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 4px;
}

.inst-row {
    display: grid;
    grid-template-columns: 48px 1fr 72px;
    align-items: center;
    gap: 8px;
    font-size: 13px;
}

.inst-total {
    padding-top: 4px;
    border-top: 1px solid var(--border);
    font-weight: 600;
}

.inst-label {
    color: var(--text-secondary);
}

.inst-track {
    position: relative;
    height: 10px;
    background: var(--surface-0);
    border-radius: 2px;
}

/* 中線為零軸 */
.inst-track::after {
    position: absolute;
    top: -2px;
    bottom: -2px;
    left: 50%;
    width: 1px;
    background: var(--border);
    content: "";
}

.inst-bar {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 2px;
}

.bar-buy {
    background: var(--buy);
}

.bar-sell {
    background: var(--sell);
}

.inst-value {
    text-align: right;
    font-variant-numeric: tabular-nums;
}

.level {
    padding: 0 6px;
    border: 1px solid currentColor;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    line-height: 18px;
    white-space: nowrap;
}

.level-calm {
    color: var(--text-secondary);
}

.level-normal {
    color: var(--series-foreign);
}

.level-alert {
    color: var(--series-trust);
}

.level-panic {
    color: var(--buy);
}

/* 維持率與 VIX 分區的 TradingView 五段色階 */
.level-strong-sell {
    color: var(--zone-strong-sell);
}

.level-sell {
    color: var(--zone-sell);
}

.level-neutral {
    color: var(--text-secondary);
}

.level-buy {
    color: var(--zone-buy);
}

.level-strong-buy {
    color: var(--zone-strong-buy);
}
</style>
