<script setup lang="ts">
/**
 * 盤中觀察。
 *
 * 與盤後頁不同，這裡沒有法人買賣超可用 (盤中不存在該資料)，
 * 改以成交金額表示資金規模、成交金額加權漲跌幅表示方向。
 *
 * MIS 端點沒有 CORS 標頭，必須由後端代抓，因此靜態站沒有這一頁；
 * 後端另有 INTRADAY_ENABLED 開關，關閉時這一頁連入口都不會出現。
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import VChart from "vue-echarts"

import type { IntradayData, IntradayIndustry, IntradayStock } from "@/types"
import { ETF_GROUP } from "@/utils/flow"
import { YI, formatDate, signed } from "@/utils/format"
import { baseTooltip, buyColor, colors, polarityColor, sellColor } from "@/utils/theme"

/** 與後端快取時間一致。掃描一輪要 24 個請求，間隔太短會讓證交所
    對整個 IP 停止回應 20 分鐘以上，類股輪動也不需要秒級更新 */
const INTERVAL = 180000
const TOP_INDUSTRIES = 20
const TOP_STOCKS = 30
/** 加權漲跌幅達此值即為最深的顏色 */
const PCT_CAP = 3

const data = ref<IntradayData | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const auto = ref(true)
const includeEtf = ref(false)

let timer: number | null = null

const industries = computed<IntradayIndustry[]>(() =>
    (data.value?.industries ?? []).filter(
        (row) => row.amount > 0 && (includeEtf.value || row.industry !== ETF_GROUP),
    ),
)

const stocks = computed<IntradayStock[]>(() => {
    if (!data.value) {
        return []
    }
    const fields = data.value.stock_fields
    return data.value.stocks
        .map((row) => {
            const item: Record<string, unknown> = {}
            fields.forEach((name, index) => {
                item[name] = row[index]
            })
            return item as unknown as IntradayStock
        })
        .filter((item) => includeEtf.value || item.industry !== ETF_GROUP)
})

const totalAmount = computed(() => industries.value.reduce((sum, row) => sum + row.amount, 0))

const status = computed(() => {
    if (error.value) {
        return `載入失敗：${error.value}`
    }
    const payload = data.value
    if (!payload) {
        return "載入中"
    }
    return `${formatDate(payload.date)}　${payload.trading ? "盤中" : "非交易時段"}`
        + `　更新於 ${payload.updated_at}`
        // 證交所在請求過密時會斷線，此時沿用上一份資料並明確標示，
        // 以免使用者把過時的數字當成當下的行情
        + (payload.stale ? "（來源忙碌，暫時沿用前一筆）" : "")
})

/** 漲跌幅轉顏色：以 PCT_CAP 為上限線性內插到平盤底色 */
function parseHex(hex: string): [number, number, number] {
    let text = hex.trim().replace("#", "")
    if (text.length === 3) {
        text = text[0] + text[0] + text[1] + text[1] + text[2] + text[2]
    }
    const value = parseInt(text, 16)
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function intradayColor(pct: number): string {
    const ratio = Math.min(Math.abs(pct) / PCT_CAP, 1)
    const from = parseHex(colors().neutral)
    const to = parseHex(pct >= 0 ? buyColor() : sellColor())
    const parts = from.map((channel, i) => Math.round(channel + (to[i] - channel) * ratio))
    return `rgb(${parts.join(",")})`
}

const treemapOption = computed(() => {
    const c = colors()
    return {
        tooltip: {
            ...baseTooltip(),
            formatter: (params: any) => {
                const row: IntradayIndustry = params.data?.detail
                if (!row) {
                    return ""
                }
                const upShare = row.amount ? ((row.up_amount / row.amount) * 100).toFixed(0) : "0"
                return `<strong>${row.industry}</strong><br>`
                    + `成交金額 ${(row.amount / YI).toFixed(1)} 億<br>`
                    + `加權漲跌 ${signed(row.weighted_pct, 2)}%<br>`
                    + `漲 ${row.up_count}　跌 ${row.down_count}　平 ${row.flat_count}<br>`
                    + `成交集中於上漲檔 ${upShare}%`
            },
        },
        series: [
            {
                type: "treemap",
                data: industries.value.map((row) => ({
                    name: row.industry,
                    value: row.amount,
                    detail: row,
                    itemStyle: {
                        color: intradayColor(row.weighted_pct),
                        borderColor: "rgba(255, 255, 255, 0.7)",
                        borderWidth: 2,
                        gapWidth: 2,
                    },
                })),
                sort: null,
                roam: false,
                nodeClick: false,
                breadcrumb: { show: false },
                width: "100%",
                height: "100%",
                label: {
                    show: true,
                    overflow: "truncate",
                    formatter: (params: any) =>
                        `{name|${params.name}}\n{value|${signed(params.data.detail.weighted_pct, 2)}%}`,
                    rich: {
                        name: { fontSize: 13, fontWeight: 600, color: c.text, lineHeight: 18 },
                        value: { fontSize: 12, color: c.secondary, lineHeight: 16 },
                    },
                },
            },
        ],
    }
})

const strengthOption = computed(() => {
    const c = colors()
    // ECharts 的類目軸由下往上排，先由弱到強排序，畫出來才是由上而下由強到弱
    const ordered = industries.value
        .slice(0, TOP_INDUSTRIES)
        .sort((a, b) => a.weighted_pct - b.weighted_pct)

    return {
        grid: { left: 110, right: 70, top: 10, bottom: 30 },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: (params: any[]) => {
                const row: IntradayIndustry = params[0].data.detail
                return `<strong>${row.industry}</strong><br>`
                    + `加權漲跌 ${signed(row.weighted_pct, 2)}%<br>`
                    + `成交金額 ${(row.amount / YI).toFixed(1)} 億`
            },
        },
        xAxis: {
            type: "value",
            axisLabel: { formatter: "{value}%", color: c.secondary },
            splitLine: { lineStyle: { color: c.border } },
        },
        yAxis: {
            type: "category",
            data: ordered.map((row) => row.industry),
            axisLabel: { color: c.secondary },
            axisLine: { lineStyle: { color: c.border } },
        },
        series: [
            {
                type: "bar",
                data: ordered.map((row) => ({
                    value: row.weighted_pct,
                    detail: row,
                    itemStyle: { color: polarityColor(row.weighted_pct) },
                })),
                label: {
                    show: true,
                    position: "right",
                    color: c.secondary,
                    fontSize: 12,
                    formatter: (params: any) => `${signed(params.value, 2)}%`,
                },
            },
        ],
    }
})

async function load(force = false) {
    if (loading.value) {
        return
    }
    loading.value = true
    try {
        const resp = await fetch(`/api/intraday${force ? "?force=true" : ""}`)
        if (!resp.ok) {
            const text = await resp.text()
            let detail = resp.statusText
            try {
                detail = JSON.parse(text).detail ?? text
            } catch {
                detail = text || resp.statusText
            }
            throw new Error(detail)
        }
        const payload = (await resp.json()) as IntradayData
        data.value = payload
        error.value = null
        // 收盤後資料不會再變，自動更新沒有意義
        if (!payload.trading) {
            stopTimer()
        }
    } catch (err) {
        error.value = (err as Error).message
    } finally {
        loading.value = false
    }
}

function startTimer() {
    stopTimer()
    if (!auto.value) {
        return
    }
    timer = window.setInterval(() => load(false), INTERVAL)
}

function stopTimer() {
    if (timer !== null) {
        clearInterval(timer)
        timer = null
    }
}

function setAuto(value: boolean) {
    auto.value = value
    if (value) {
        load(false)
        startTimer()
    } else {
        stopTimer()
    }
}

onMounted(() => {
    load(false)
    startTimer()
})

onUnmounted(stopTimer)
</script>

<template>
    <section class="view" :class="{ 'is-refreshing': loading }">
        <header class="page-head">
            <div>
                <h1>盤中類股強弱</h1>
                <p class="subtitle">
                    開盤至今的成交金額與加權漲跌幅，約每三分鐘更新一次，可隨時手動更新
                </p>
            </div>
            <div class="head-meta">
                <span class="data-date">{{ status }}</span>
            </div>
        </header>

        <div class="controls">
            <div class="control">
                <span class="control-label">更新</span>
                <div class="tabs" role="tablist">
                    <button
                        type="button"
                        class="tab"
                        :class="{ 'is-active': auto }"
                        role="tab"
                        @click="setAuto(true)"
                    >
                        自動
                    </button>
                    <button
                        type="button"
                        class="tab"
                        :class="{ 'is-active': !auto }"
                        role="tab"
                        @click="setAuto(false)"
                    >
                        暫停
                    </button>
                </div>
            </div>

            <div class="control">
                <span class="control-label">範圍</span>
                <div class="tabs" role="tablist">
                    <button
                        type="button"
                        class="tab"
                        :class="{ 'is-active': !includeEtf }"
                        role="tab"
                        @click="includeEtf = false"
                    >
                        不含 ETF
                    </button>
                    <button
                        type="button"
                        class="tab"
                        :class="{ 'is-active': includeEtf }"
                        role="tab"
                        @click="includeEtf = true"
                    >
                        含 ETF
                    </button>
                </div>
            </div>

            <div class="control control-inline">
                <button type="button" class="chip" @click="load(true)">立即更新</button>
            </div>
        </div>

        <p class="notice">
            盤中沒有任何官方即時法人買賣超資料，三大法人進出要收盤後才公布。本頁改以實際成交統計呈現：
            區塊面積為該類股開盤至今的成交金額，顏色為以成交金額加權的漲跌幅。
            成交金額以現價乘上累積成交量估算，與真實成交值有誤差，用於比較類股之間的相對規模。
        </p>

        <section class="panel">
            <div class="panel-head">
                <h2>即時指數</h2>
                <p class="panel-note">報價時間 {{ data?.quote_time || "--" }}</p>
            </div>
            <div class="quote-grid">
                <div v-for="row in data?.indexes ?? []" :key="row.code" class="quote-card">
                    <div class="quote-name">{{ row.name }}</div>
                    <div
                        class="quote-value"
                        :style="{ color: row.pct >= 0 ? buyColor() : sellColor() }"
                    >
                        {{ row.value.toFixed(2) }}
                    </div>
                    <div
                        class="quote-change"
                        :style="{ color: row.pct >= 0 ? buyColor() : sellColor() }"
                    >
                        {{ signed(row.diff, 2) }}（{{ signed(row.pct, 2) }}%）
                    </div>
                    <div class="quote-meta">
                        成交 {{ (row.amount / YI).toFixed(0) }} 億　{{ (row.volume / 10000).toFixed(0) }} 萬張　{{ row.time || "--" }}
                    </div>
                </div>
                <p v-if="!data?.indexes?.length" class="quote-meta">目前沒有指數報價</p>
            </div>
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>類股資金分布</h2>
                <p class="panel-note">
                    面積為成交金額，顏色為成交金額加權的漲跌幅（±{{ PCT_CAP }}% 以上為最深色）；
                    合計 {{ (totalAmount / YI).toFixed(0) }} 億，共 {{ industries.length }} 個類股
                </p>
            </div>
            <VChart
                v-if="industries.length"
                class="chart chart-tall"
                :option="treemapOption"
                autoresize
            />
            <p v-else class="notice">目前沒有可顯示的資料</p>
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>類股強弱</h2>
                <p class="panel-note">依成交金額取前 {{ TOP_INDUSTRIES }} 個類股，長度為加權漲跌幅</p>
            </div>
            <VChart
                v-if="industries.length"
                class="chart"
                :option="strengthOption"
                autoresize
            />
        </section>

        <section class="panel">
            <div class="panel-head">
                <h2>成交金額排行</h2>
                <p class="panel-note">
                    開盤至今成交金額最大的 {{ Math.min(stocks.length, TOP_STOCKS) }} 檔，
                    全市場共 {{ stocks.length }} 檔有成交
                </p>
            </div>
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>代號</th><th>名稱</th><th>類股</th>
                            <th class="num">成交價</th><th class="num">漲跌幅</th>
                            <th class="num">成交金額（億）</th><th class="num">成交量（張）</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="!stocks.length" class="empty-row">
                            <td colspan="7">無資料</td>
                        </tr>
                        <tr v-for="row in stocks.slice(0, TOP_STOCKS)" :key="row.code">
                            <td>{{ row.code }}</td>
                            <td>{{ row.name }}</td>
                            <td>{{ row.industry }}</td>
                            <td class="num">{{ row.price.toFixed(2) }}</td>
                            <td class="num" :class="row.pct >= 0 ? 'val-buy' : 'val-sell'">
                                {{ signed(row.pct, 2) }}%
                            </td>
                            <td class="num">{{ (row.amount / YI).toFixed(1) }}</td>
                            <td class="num">{{ row.volume.toLocaleString() }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>
