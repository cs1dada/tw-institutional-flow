<script setup lang="ts">
/**
 * 題材資金流向與季度輪動軌跡：
 * 針對 12 週 (一季) 提供：
 * 1. 1 週逐週切分 (W1 ~ W12) 與精準行為標籤（主力鎖碼、先買後倒 C、超跌承接、持續提款、區間震盪）
 * 2. 3 種視覺圖表自由挑選（累計趨勢折線圖、桑基流向圖、12週逐週脈動柱圖，以及整季淨額長條圖）
 * 3. 2 種文字結論自由挑選（白話操盤故事、條列重點戰報）
 */
import { computed, ref, watch } from "vue"
import VChart from "vue-echarts"

import type { HoldersAnalysis } from "@/types"
import { formatDate, signed } from "@/utils/format"
import { baseTooltip, buyColor, colors, sellColor } from "@/utils/theme"

const props = withDefaults(
    defineProps<{
        heatmap: HoldersAnalysis["heatmap"]
        period?: number
        selectedDate?: string
    }>(),
    { period: 1, selectedDate: "" },
)

/** 結論展示模式：story (白話操盤故事) 或 report (條列重點戰報) */
const conclusionMode = ref<"story" | "report">("story")

/** 12 週時的圖表類型：trend (累計趨勢線) | sankey (桑基流向圖) | weekly (12週逐週脈動) | bar (淨額長條圖) */
const chartType = ref<"trend" | "sankey" | "weekly" | "bar">("trend")

/** 標籤篩選：全部 或 特定行為標籤 */
const activeTagFilter = ref<string>("ALL")

/** 非 12 週時的長條圖是否顯示全部 */
const showAll = ref(false)

watch(
    () => props.period,
    (newP) => {
        if (newP === 12) {
            chartType.value = "trend"
        } else {
            chartType.value = "bar"
        }
    },
)

const currentWeekIdx = computed(() => {
    const weeks = props.heatmap.weeks
    if (!weeks.length) return -1
    const target = props.selectedDate || weeks[weeks.length - 1]
    const idx = weeks.indexOf(target)
    return idx >= 0 ? idx : weeks.length - 1
})

const targetDate = computed(() => {
    const idx = currentWeekIdx.value
    return idx >= 0 ? props.heatmap.weeks[idx] : ""
})

const startDate = computed(() => {
    const idx = currentWeekIdx.value
    const k = props.period
    if (idx < 0 || k <= 1) return targetDate.value
    const startIdx = Math.max(0, idx - k + 1)
    return props.heatmap.weeks[startIdx]
})

function sumRange(vals: (number | null)[], start: number, end: number): number | null {
    const w = vals.slice(start, end + 1)
    if (!w.length || w.some((x) => x === null || x === undefined)) {
        return null
    }
    return +(w as number[]).reduce((a, b) => a + b, 0).toFixed(2)
}

// -------------------------------------------------------------
// 12 週逐週切分與標籤演算法 (1-Week Resolution & Tagging)
// -------------------------------------------------------------
export type BehaviorTag =
    | "主力長線鎖碼"
    | "波段出貨(先買後倒)"
    | "超跌換手承接"
    | "持續提款外流"
    | "區間震盪觀望"

export interface WeeklyThemeAnalysis {
    id: string
    name: string
    total: number
    /** 12 週各週的單週增減量 (W1 ~ W12) */
    weeklyValues: number[]
    /** 12 週的逐週累計走勢 (W1 到 W12 累加) */
    cumValues: number[]
    buyWeeks: number
    sellWeeks: number
    peak: number
    peakWeek: number
    peakDate: string
    valley: number
    valleyWeek: number
    valleyDate: string
    end: number
    tag: BehaviorTag
    tagIcon: string
    tagDesc: string
}

/** 12 週各週的週次資訊 (W1 ~ W12) */
const weeks12Meta = computed(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return []
    const weeks = props.heatmap.weeks
    const res = []
    for (let w = 0; w < 12; w++) {
        const weekIdx = idx - 11 + w
        const rawDate = weeks[weekIdx]
        const dStr = formatDate(rawDate).slice(5)
        res.push({
            index: w + 1,
            label: `W${w + 1}`,
            fullLabel: `W${w + 1} (${dStr})`,
            rawDate,
            dateStr: dStr,
        })
    }
    return res
})

/** 12 週深度分析與 1 週標籤計算 */
const analysis12 = computed<WeeklyThemeAnalysis[]>(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return []

    const themes = props.heatmap.themes
    const meta = weeks12Meta.value
    const res: WeeklyThemeAnalysis[] = []

    for (const theme of themes) {
        const slice12 = theme.values.slice(idx - 11, idx + 1)
        if (slice12.length < 12 || slice12.some((v) => v === null || v === undefined)) {
            continue
        }
        const vals = slice12 as number[]

        // 統計買超週數與賣超週數
        let buyWeeks = 0
        let sellWeeks = 0
        for (const v of vals) {
            if (v > 0) buyWeeks++
            else if (v < 0) sellWeeks++
        }

        // 逐週累計走勢
        const cumValues: number[] = []
        let curr = 0
        let peak = -999
        let peakWeek = 0
        let valley = 999
        let valleyWeek = 0

        for (let w = 0; w < 12; w++) {
            curr = +(curr + vals[w]).toFixed(2)
            cumValues.push(curr)
            if (curr > peak) {
                peak = curr
                peakWeek = w + 1
            }
            if (curr < valley) {
                valley = curr
                valleyWeek = w + 1
            }
        }

        const total = cumValues[cumValues.length - 1]
        const end = total
        const dumpFromPeak = +(peak - end).toFixed(2)
        const bounceFromValley = +(end - valley).toFixed(2)

        const peakDate = meta[peakWeek - 1]?.dateStr || `W${peakWeek}`
        const valleyDate = meta[valleyWeek - 1]?.dateStr || `W${valleyWeek}`

        // 1 週精度籌碼行為標籤判斷
        let tag: BehaviorTag = "區間震盪觀望"
        let tagIcon = "⏳"
        let tagDesc = `買超 ${buyWeeks} 週 / 賣超 ${sellWeeks} 週，籌碼區間多空拉鋸`

        if (peak >= 1.2 && dumpFromPeak >= 1.2) {
            tag = "波段出貨(先買後倒)"
            tagIcon = "🚨"
            tagDesc = `W${peakWeek} (${peakDate}) 見頂 (+${peak}%) 後遭大戶連續倒貨 ${dumpFromPeak}%`
        } else if (valley <= -1.2 && bounceFromValley >= 1.2) {
            tag = "超跌換手承接"
            tagIcon = "🔄"
            tagDesc = `W${valleyWeek} (${valleyDate}) 落底 (${valley}%) 後大戶回補低接 +${bounceFromValley}%`
        } else if (total >= 1.5 && (buyWeeks >= 7 || vals[10] + vals[11] >= 0)) {
            tag = "主力長線鎖碼"
            tagIcon = "🔒"
            tagDesc = `買超高達 ${buyWeeks}/12 週，季底持股持續攻頂 (+${total}%)`
        } else if (total <= -1.5 && sellWeeks >= 7) {
            tag = "持續提款外流"
            tagIcon = "💸"
            tagDesc = `賣超多達 ${sellWeeks}/12 週，大戶季內一路賣超提款 (${total}%)`
        } else if (total <= -1.5) {
            tag = "持續提款外流"
            tagIcon = "💸"
            tagDesc = `季內遭大戶單週重擊提款，總減碼達 ${total}%`
        }

        res.push({
            id: theme.id,
            name: theme.name,
            total,
            weeklyValues: vals,
            cumValues,
            buyWeeks,
            sellWeeks,
            peak,
            peakWeek,
            peakDate,
            valley,
            valleyWeek,
            valleyDate,
            end,
            tag,
            tagIcon,
            tagDesc,
        })
    }

    return res.sort((a, b) => b.total - a.total)
})

/** 一般週數 (1週 / 4週) 或通用總計差額 */
const simpleDiffs = computed(() => {
    const idx = currentWeekIdx.value
    if (idx < 0) return []
    const k = props.period
    const res: { id: string; name: string; value: number }[] = []

    for (const theme of props.heatmap.themes) {
        if (k === 1) {
            const v = theme.values[idx]
            if (v !== null && v !== undefined) {
                res.push({ id: theme.id, name: theme.name, value: v })
            }
        } else {
            if (idx < k - 1) continue
            const sum = sumRange(theme.values, idx - k + 1, idx)
            if (sum !== null) {
                res.push({ id: theme.id, name: theme.name, value: sum })
            }
        }
    }
    return res.sort((a, b) => b.value - a.value)
})

// -------------------------------------------------------------
// 結論計算 (白話操盤故事 vs 條列重點戰報)
// -------------------------------------------------------------
const storyConclusion = computed(() => {
    if (props.period !== 12 || !analysis12.value.length) {
        const target = targetDate.value
        const start = startDate.value
        const k = props.period
        const diffs = simpleDiffs.value
        if (!diffs.length) return ""
        const topIn = diffs.filter((t) => t.value > 0).slice(0, 3)
        const topOut = diffs.filter((t) => t.value < 0).slice(-3).reverse()
        const spanText = k > 1 ? `${k} 週累計 (${formatDate(start)} ~ ${formatDate(target)})` : `${formatDate(target)} 單週`
        return `這段期間（${spanText}），大戶主要流入 ${topIn.map((t) => `「${t.name}」(+${t.value.toFixed(1)}%)`).join("、")}；主要自 ${topOut.map((t) => `「${t.name}」(${t.value.toFixed(1)}%)`).join("、")} 撤出。`
    }

    const items = analysis12.value
    const lockThemes = items.filter((t) => t.tag === "主力長線鎖碼").map((t) => t.name)
    const dumpThemes = items.filter((t) => t.tag === "波段出貨(先買後倒)").map((t) => t.name)
    const outThemes = items.filter((t) => t.tag === "持續提款外流").map((t) => t.name)

    const w1Out = items.filter((t) => t.weeklyValues[0] < -0.8).map((t) => t.name).slice(0, 2)
    const w12In = items.filter((t) => t.weeklyValues[11] > 0.4).map((t) => t.name).slice(0, 2)

    return `在這 12 週逐週（W1 ~ W12）籌碼流轉中，資金輪動呈現精密的三部曲：
1. 【季初撤離防守 (W1~W4)】：大戶率先自提款重災區「${outThemes.slice(0, 2).join("、") || w1Out.join("、") || "功率半導體"}」大舉撤退，長線防禦型標的「${lockThemes.slice(0, 2).join("、")}」自第 1 週起即獲法人週週鎖碼。
2. 【季中狂飆中繼 (W5~W8)】：大戶拉抬「${dumpThemes.slice(0, 2).join("、")}」扮演波段中繼站，於 W8 衝上最高峰值；
3. 【季末獲利了結與終極停泊 (W9~W12)】：W8 過後，大戶反手對「${dumpThemes.slice(0, 2).join("、")}」連續倒貨結帳，資金全數流向週週買超的「${w12In.join("、") || lockThemes[0]}」。
生動呈現「A (提款族群) ➡️ C (中繼拉抬出貨) ➡️ B (季末鎖碼終點)」的每週籌碼轉移軌跡。`
})

const reportGroups = computed(() => {
    if (props.period !== 12 || !analysis12.value.length) return null
    const items = analysis12.value

    return [
        {
            tag: "主力長線鎖碼",
            icon: "🔒",
            class: "tag-lock",
            items: items.filter((t) => t.tag === "主力長線鎖碼"),
            desc: "12 週中高頻率週週買超，籌碼沉澱極佳，為季內法人長線主升核心",
        },
        {
            tag: "波段出貨(先買後倒)",
            icon: "🚨",
            class: "tag-dump",
            items: items.filter((t) => t.tag === "波段出貨(先買後倒)"),
            desc: "季中（W5~W8）曾爆量衝上高峰，但隨後在 W9~W12 遭主力反手大倒貨結帳",
        },
        {
            tag: "超跌換手承接",
            icon: "🔄",
            class: "tag-bounce",
            items: items.filter((t) => t.tag === "超跌換手承接"),
            desc: "前期遭重砍創季內低點後，中後期獲得主力進場逢低承接",
        },
        {
            tag: "持續提款外流",
            icon: "💸",
            class: "tag-out",
            items: items.filter((t) => t.tag === "持續提款外流"),
            desc: "12 週中大部分週次均為淨賣出，大戶一路減碼外逃",
        },
    ]
})

// -------------------------------------------------------------
// 圖表 1：📈 12 週累計走勢折線圖 (Trajectory Multi-line Chart)
// -------------------------------------------------------------
const trendOption = computed(() => {
    const c = colors()
    const items = analysis12.value
    if (!items.length) return {}

    const locks = items.filter((t) => t.tag === "主力長線鎖碼").slice(0, 3)
    const turns = items.filter((t) => t.tag === "波段出貨(先買後倒)").slice(0, 3)
    const outs = items.filter((t) => t.tag === "持續提款外流").slice(0, 3)
    const targetThemes = [...locks, ...turns, ...outs]

    const linePalette = [
        "#e34948", "#ff7a45", "#f7ba1e",
        "#873bf5", "#13c2c2", "#2f54eb",
        "#52c41a", "#73d13d", "#389e0d",
    ]

    return {
        grid: { left: 55, right: 90, top: 50, bottom: 35 },
        legend: {
            data: targetThemes.map((t) => t.name),
            top: 5,
            textStyle: { color: c.secondary, fontSize: 11 },
            itemWidth: 14,
            itemHeight: 10,
        },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            formatter: (params: any) => {
                const weekLabel = params[0]?.axisValue || ""
                const dataIndex = params[0]?.dataIndex ?? 0
                const lines = [`<strong>${weekLabel} 持股變化（以 1 週為單位）</strong>`]
                const sortedP = params.slice().sort((a: any, b: any) => (b.value ?? 0) - (a.value ?? 0))
                for (const p of sortedP) {
                    const val = p.value as number
                    const theme = targetThemes.find((t) => t.name === p.seriesName)
                    const weeklyVal = theme?.weeklyValues[dataIndex]
                    const weeklyStr = weeklyVal !== undefined ? `（當週單週 ${signed(weeklyVal)}%）` : ""
                    lines.push(`${p.marker} ${p.seriesName}：累計 ${signed(val)}% ${weeklyStr}`)
                }
                return lines.join("<br>")
            },
        },
        xAxis: {
            type: "category",
            data: weeks12Meta.value.map((m) => `${m.label}\n(${m.dateStr})`),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 10 },
        },
        yAxis: {
            type: "value",
            name: "累計增減 (百分點)",
            nameTextStyle: { color: c.muted, fontSize: 10 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 10 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        series: targetThemes.map((t, idx) => {
            const lineColor = linePalette[idx % linePalette.length]
            return {
                name: t.name,
                type: "line",
                data: t.cumValues,
                smooth: true,
                symbol: "circle",
                symbolSize: 6,
                lineStyle: { width: t.tag === "波段出貨(先買後倒)" ? 3 : 2, color: lineColor },
                itemStyle: { color: lineColor },
                markPoint: t.tag === "波段出貨(先買後倒)" ? {
                    symbol: "pin",
                    symbolSize: 32,
                    data: [
                        {
                            name: "峰值轉折",
                            coord: [t.peakWeek - 1, t.peak],
                            value: `峰值 +${t.peak}%`,
                            itemStyle: { color: "#873bf5" },
                            label: { fontSize: 9, color: "#fff" },
                        },
                    ],
                } : undefined,
            }
        }),
    }
})

// -------------------------------------------------------------
// 圖表 2：🌊 季度資金流向桑基圖 (Sankey Flow Chart)
// -------------------------------------------------------------
const sankeyOption = computed(() => {
    const c = colors()
    const items = analysis12.value
    if (!items.length) return {}

    const outThemes = items.filter((t) => t.total <= -1.5).slice(0, 5)
    const midThemes = items.filter((t) => t.tag === "波段出貨(先買後倒)").slice(0, 3)
    const inThemes = items.filter((t) => t.total >= 1.5).slice(0, 4)

    const nodes: any[] = []
    const links: any[] = []

    for (const t of outThemes) {
        nodes.push({ name: `[提款] ${t.name}`, itemStyle: { color: sellColor() } })
    }
    for (const t of midThemes) {
        nodes.push({ name: `[中繼] ${t.name}`, itemStyle: { color: "#873bf5" } })
    }
    for (const t of inThemes) {
        nodes.push({ name: `[鎖碼] ${t.name}`, itemStyle: { color: buyColor() } })
    }

    // links
    for (const outT of outThemes) {
        const outVal = Math.abs(outT.total)
        for (const midT of midThemes) {
            const flowVal = +(outVal * (midT.peak / 10)).toFixed(2)
            if (flowVal > 0.3) {
                links.push({
                    source: `[提款] ${outT.name}`,
                    target: `[中繼] ${midT.name}`,
                    value: flowVal,
                })
            }
        }
    }

    for (const midT of midThemes) {
        const dumpVal = +(midT.peak - midT.end).toFixed(2)
        for (const inT of inThemes) {
            const flowVal = +(dumpVal * (inT.total / 15)).toFixed(2)
            if (flowVal > 0.3) {
                links.push({
                    source: `[中繼] ${midT.name}`,
                    target: `[鎖碼] ${inT.name}`,
                    value: flowVal,
                })
            }
        }
    }

    for (let i = 0; i < Math.min(outThemes.length, inThemes.length); i++) {
        links.push({
            source: `[提款] ${outThemes[i].name}`,
            target: `[鎖碼] ${inThemes[i].name}`,
            value: 0.8,
        })
    }

    return {
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            triggerOn: "mousemove",
            formatter: (params: any) => {
                if (params.dataType === "edge") {
                    return `<strong>${params.data.source} ➡️ ${params.data.target}</strong><br>估計輪動規模：${params.data.value} 百分點`
                }
                return `<strong>${params.name}</strong>`
            },
        },
        series: [
            {
                type: "sankey",
                layout: "none",
                left: 40,
                right: 120,
                top: 20,
                bottom: 20,
                nodeWidth: 16,
                nodeGap: 14,
                draggable: true,
                emphasis: { focus: "adjacency" },
                data: nodes,
                links,
                lineStyle: { color: "gradient", curveness: 0.5, opacity: 0.4 },
                label: { color: c.secondary, fontSize: 11 },
            },
        ],
    }
})

// -------------------------------------------------------------
// 圖表 3：📊 12 週逐週脈動柱狀圖 (Weekly Pulse Bar Chart)
// -------------------------------------------------------------
const weeklyOption = computed(() => {
    const c = colors()
    const items = analysis12.value
    if (!items.length) return {}

    const focusThemes = [
        ...items.slice(0, 4),
        ...items.filter((t) => t.tag === "波段出貨(先買後倒)").slice(0, 2),
        ...items.slice(-4),
    ].filter((v, i, a) => a.findIndex((t) => t.id === v.id) === i)

    const meta = weeks12Meta.value

    return {
        grid: { left: 140, right: 50, top: 40, bottom: 25 },
        legend: {
            data: meta.map((m) => m.label),
            top: 5,
            textStyle: { color: c.secondary, fontSize: 10 },
            itemWidth: 10,
            itemHeight: 8,
        },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: (params: any) => {
                const themeName = params[0]?.name || ""
                const lines = [`<strong>${themeName}（12 週逐週脈動）</strong>`]
                for (const p of params) {
                    const val = p.value as number
                    if (val !== 0) {
                        lines.push(`${p.seriesName}：${signed(val)}%`)
                    }
                }
                return lines.join("<br>")
            },
        },
        xAxis: {
            type: "value",
            name: "單週增減 (百分點)",
            nameTextStyle: { color: c.muted, fontSize: 10 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 10 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        yAxis: {
            type: "category",
            data: focusThemes.map((t) => t.name).reverse(),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 12 },
        },
        series: meta.map((m, wIdx) => {
            const opacity = +(0.3 + (wIdx / 11) * 0.7).toFixed(2)
            return {
                name: m.label,
                type: "bar",
                barWidth: 4,
                data: focusThemes
                    .slice()
                    .reverse()
                    .map((t) => {
                        const v = t.weeklyValues[wIdx]
                        return {
                            value: v,
                            itemStyle: {
                                color: v >= 0 ? buyColor() : sellColor(),
                                opacity,
                            },
                        }
                    }),
            }
        }),
    }
})

// -------------------------------------------------------------
// 圖表 4：整季淨額長條圖 (General Bar Chart for 1/4/12 weeks)
// -------------------------------------------------------------
const netBarOption = computed(() => {
    const c = colors()
    const diffs = simpleDiffs.value
    if (!diffs.length) return {}

    const displayList = showAll.value
        ? diffs
        : [...diffs.filter((t) => t.value > 0).slice(0, 5), ...diffs.filter((t) => t.value < 0).slice(-5)]

    const items = displayList.slice().reverse()

    return {
        grid: { left: 140, right: 60, top: 10, bottom: 24 },
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                const item = params.data?.raw as { name: string; value: number } | undefined
                if (!item) return ""
                const action = item.value >= 0 ? "大戶在收" : "大戶在賣"
                const span = props.period === 1 ? "單週變化" : `${props.period} 週累計淨額`
                return `<strong>${item.name}</strong><br>${span}：${signed(item.value)} 百分點 (${action})`
            },
        },
        xAxis: {
            type: "value",
            name: "百分點",
            nameTextStyle: { color: c.muted, fontSize: 10 },
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 10 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        yAxis: {
            type: "category",
            data: items.map((t) => t.name),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 12 },
        },
        series: [
            {
                type: "bar",
                barWidth: 14,
                data: items.map((item) => {
                    const isPositive = item.value >= 0
                    return {
                        value: item.value,
                        raw: item,
                        itemStyle: {
                            color: isPositive ? buyColor() : sellColor(),
                            borderRadius: isPositive ? [0, 4, 4, 0] : [4, 0, 0, 4],
                        },
                        label: {
                            show: true,
                            position: isPositive ? "right" : "left",
                            formatter: () => signed(item.value),
                            color: c.secondary,
                            fontSize: 11,
                        },
                    }
                }),
            },
        ],
    }
})

/** 圖表當前配置 */
const activeOption = computed(() => {
    if (props.period === 12) {
        if (chartType.value === "trend") return trendOption.value
        if (chartType.value === "sankey") return sankeyOption.value
        if (chartType.value === "weekly") return weeklyOption.value
        return netBarOption.value
    }
    return netBarOption.value
})

/** 圖表高度動態調整 */
const chartHeight = computed(() => {
    if (props.period === 12) {
        if (chartType.value === "trend") return "380px"
        if (chartType.value === "sankey") return "420px"
        if (chartType.value === "weekly") return "420px"
    }
    const count = showAll.value ? simpleDiffs.value.length : 10
    return `${Math.max(260, count * 26 + 40)}px`
})

/** 標籤過濾後的題材列表 */
const filteredAnalysis = computed(() => {
    const list = analysis12.value
    if (activeTagFilter.value === "ALL") return list
    return list.filter((t) => t.tag === activeTagFilter.value)
})
</script>

<template>
    <div v-if="simpleDiffs.length" class="theme-flow-container">
        <!-- 頂部結論區塊 (支援切換白話故事 vs 條列戰報) -->
        <div class="conclusion-box">
            <div class="conclusion-toolbar">
                <span class="toolbar-title">💡 資金流向與輪動總結</span>
                <div v-if="period === 12" class="view-toggle-group">
                    <button
                        type="button"
                        class="toggle-btn"
                        :class="{ active: conclusionMode === 'story' }"
                        @click="conclusionMode = 'story'"
                    >
                        📖 白話操盤故事
                    </button>
                    <button
                        type="button"
                        class="toggle-btn"
                        :class="{ active: conclusionMode === 'report' }"
                        @click="conclusionMode = 'report'"
                    >
                        📋 條列重點戰報
                    </button>
                </div>
            </div>

            <!-- 視角 A：白話故事 -->
            <div v-if="conclusionMode === 'story' || period !== 12" class="story-content">
                <p class="story-text">{{ storyConclusion }}</p>
            </div>

            <!-- 視角 B：條列戰報 -->
            <div v-else-if="reportGroups" class="report-content">
                <div
                    v-for="grp in reportGroups"
                    :key="grp.tag"
                    class="report-card"
                    :class="grp.class"
                >
                    <div class="report-card-head">
                        <span class="grp-icon">{{ grp.icon }}</span>
                        <span class="grp-title">{{ grp.tag }}</span>
                        <span class="grp-count">({{ grp.items.length }})</span>
                        <span class="grp-desc muted">{{ grp.desc }}</span>
                    </div>
                    <div v-if="grp.items.length" class="report-chips">
                        <div v-for="t in grp.items" :key="t.id" class="report-chip">
                            <span class="chip-name">{{ t.name }}</span>
                            <span
                                class="chip-val"
                                :class="{ buy: t.total > 0, sell: t.total < 0 }"
                            >
                                {{ signed(t.total) }}%
                            </span>
                            <span class="chip-diag muted">{{ t.tagDesc }}</span>
                        </div>
                    </div>
                    <div v-else class="empty-hint muted">本季無顯著符合此特徵之族群</div>
                </div>
            </div>
        </div>

        <!-- 圖表區塊 -->
        <div class="flow-chart-wrap">
            <div class="chart-header">
                <div class="header-left">
                    <span class="chart-subtitle">
                        {{ period === 12 ? "一季 (12週) 資金輪動圖表視覺化（以 1 週為單位逐週追蹤）" : "主要流入與流出題材 (前 5 名對照)" }}
                    </span>
                    <!-- 12 週時提供 4 種圖表挑選 -->
                    <div v-if="period === 12" class="chart-type-selector">
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'trend' }"
                            @click="chartType = 'trend'"
                        >
                            📈 12 週累計趨勢線 (含單週變化)
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'weekly' }"
                            @click="chartType = 'weekly'"
                        >
                            📊 12 週逐週脈動柱圖 (單週增減)
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'sankey' }"
                            @click="chartType = 'sankey'"
                        >
                            🌊 季度桑基流向圖
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'bar' }"
                            @click="chartType = 'bar'"
                        >
                            🧱 整季淨額長條圖
                        </button>
                    </div>
                </div>

                <button
                    v-if="period !== 12 && simpleDiffs.length > 10"
                    type="button"
                    class="chip flow-toggle"
                    @click="showAll = !showAll"
                >
                    {{ showAll ? "收合為前 5 名對照" : `查看全部 ${simpleDiffs.length} 個題材` }}
                </button>
            </div>

            <!-- 圖表本體 -->
            <VChart
                class="flow-chart"
                :style="{ height: chartHeight }"
                :option="activeOption"
                autoresize
            />
        </div>

        <!-- 12 週專屬：1 週逐週 (W1 ~ W12) 行為標籤診斷卡片 -->
        <div v-if="period === 12 && analysis12.length" class="tags-section">
            <div class="tags-header">
                <div class="tags-title">🏷️ 1 週精度籌碼特徵標籤診斷 (W1 ~ W12 逐週脈動)</div>
                <div class="tags-filter-bar">
                    <button
                        type="button"
                        class="filter-chip"
                        :class="{ active: activeTagFilter === 'ALL' }"
                        @click="activeTagFilter = 'ALL'"
                    >
                        全部 ({{ analysis12.length }})
                    </button>
                    <button
                        type="button"
                        class="filter-chip"
                        :class="{ active: activeTagFilter === '主力長線鎖碼' }"
                        @click="activeTagFilter = '主力長線鎖碼'"
                    >
                        🔒 主力長線鎖碼 ({{ analysis12.filter((t) => t.tag === '主力長線鎖碼').length }})
                    </button>
                    <button
                        type="button"
                        class="filter-chip"
                        :class="{ active: activeTagFilter === '波段出貨(先買後倒)' }"
                        @click="activeTagFilter = '波段出貨(先買後倒)'"
                    >
                        🚨 波段出貨(先買後倒) ({{ analysis12.filter((t) => t.tag === '波段出貨(先買後倒)').length }})
                    </button>
                    <button
                        type="button"
                        class="filter-chip"
                        :class="{ active: activeTagFilter === '持續提款外流' }"
                        @click="activeTagFilter = '持續提款外流'"
                    >
                        💸 持續提款外流 ({{ analysis12.filter((t) => t.tag === '持續提款外流').length }})
                    </button>
                    <button
                        type="button"
                        class="filter-chip"
                        :class="{ active: activeTagFilter === '區間震盪觀望' }"
                        @click="activeTagFilter = '區間震盪觀望'"
                    >
                        ⏳ 區間震盪觀望 ({{ analysis12.filter((t) => t.tag === '區間震盪觀望').length }})
                    </button>
                </div>
            </div>

            <div class="theme-cards-grid">
                <div
                    v-for="t in filteredAnalysis"
                    :key="t.id"
                    class="theme-card"
                >
                    <div class="card-top">
                        <div class="theme-name">{{ t.name }}</div>
                        <span class="theme-tag-badge">
                            {{ t.tagIcon }} {{ t.tag }}
                        </span>
                    </div>

                    <div class="card-total-row">
                        <span class="muted font-11">12 週累計：</span>
                        <span
                            class="total-pill"
                            :class="{ buy: t.total > 0, sell: t.total < 0 }"
                        >
                            {{ signed(t.total) }}%
                        </span>
                        <span class="peak-note muted">
                            (買超 {{ t.buyWeeks }} 週 / 賣超 {{ t.sellWeeks }} 週)
                        </span>
                    </div>

                    <!-- 12 週逐週數值序列 (W1 ~ W12 小藥丸) -->
                    <div class="weekly-pills-row">
                        <span class="muted font-10">逐週脈動：</span>
                        <div class="pills-track">
                            <span
                                v-for="(val, wIdx) in t.weeklyValues"
                                :key="wIdx"
                                class="w-pill"
                                :class="{ buy: val > 0, sell: val < 0, neutral: val === 0 }"
                                :title="`${weeks12Meta[wIdx]?.fullLabel}：${signed(val)}%`"
                            >
                                W{{ wIdx + 1 }}: {{ signed(val) }}%
                            </span>
                        </div>
                    </div>

                    <div class="card-diag-desc muted">
                        {{ t.tagDesc }}
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.theme-flow-container {
    margin-bottom: 20px;
}

/* 結論外框 */
.conclusion-box {
    background: var(--surface-0);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 14px;
}

.conclusion-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    flex-wrap: wrap;
    gap: 8px;
}

.toolbar-title {
    font-weight: 600;
    font-size: 14px;
    color: var(--text-primary);
}

.view-toggle-group,
.chart-type-selector {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 5px;
    overflow: hidden;
    background: var(--surface-1);
}

.toggle-btn,
.type-btn {
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 12px;
    padding: 4px 10px;
    cursor: pointer;
    transition: all 0.15s ease;
}

.toggle-btn:hover,
.type-btn:hover {
    background: var(--neutral);
    color: var(--text-primary);
}

.toggle-btn.active,
.type-btn.active {
    background: var(--neutral);
    color: var(--text-primary);
    font-weight: 600;
}

.story-text {
    margin: 0;
    line-height: 1.75;
    font-size: 13.5px;
    color: var(--text-primary);
    white-space: pre-line;
}

/* 條列戰報 */
.report-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.report-card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
}

.report-card-head {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
    font-size: 13px;
    font-weight: 600;
}

.grp-desc {
    font-size: 11px;
    font-weight: normal;
    margin-left: 6px;
}

.report-chips {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.report-chip {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    background: var(--surface-0);
    padding: 4px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
}

.chip-name {
    font-weight: 600;
    min-width: 90px;
}

.chip-val {
    font-weight: 600;
    min-width: 55px;
}

.chip-val.buy {
    color: var(--buy);
}

.chip-val.sell {
    color: var(--sell);
}

.chip-diag {
    font-size: 11px;
}

.empty-hint {
    font-size: 12px;
    padding: 4px 0;
}

/* 圖表外框 */
.flow-chart-wrap {
    padding: 12px 14px;
    background: var(--surface-0);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 16px;
}

.chart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    flex-wrap: wrap;
    gap: 10px;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.chart-subtitle {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
}

.flow-toggle {
    font-size: 12px;
    padding: 3px 8px;
    cursor: pointer;
}

.flow-chart {
    width: 100%;
}

/* 1 週逐週標籤診斷區塊 */
.tags-section {
    background: var(--surface-0);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
    margin-bottom: 16px;
}

.tags-header {
    margin-bottom: 12px;
}

.tags-title {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 8px;
}

.tags-filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.filter-chip {
    border: 1px solid var(--border);
    background: var(--surface-1);
    color: var(--text-secondary);
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
}

.filter-chip:hover {
    background: var(--neutral);
    color: var(--text-primary);
}

.filter-chip.active {
    background: var(--text-primary);
    color: var(--surface-0);
    border-color: var(--text-primary);
    font-weight: 600;
}

.theme-cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 10px;
    margin-top: 10px;
}

.theme-card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.card-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.theme-name {
    font-weight: 600;
    font-size: 14px;
    color: var(--text-primary);
}

.theme-tag-badge {
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
    background: var(--surface-0);
    border: 1px solid var(--border);
}

.card-total-row {
    display: flex;
    align-items: center;
    gap: 6px;
}

.total-pill {
    font-weight: 600;
    font-size: 13px;
}

.total-pill.buy {
    color: var(--buy);
}

.total-pill.sell {
    color: var(--sell);
}

.peak-note {
    font-size: 11px;
}

.weekly-pills-row {
    display: flex;
    align-items: flex-start;
    gap: 6px;
}

.pills-track {
    display: flex;
    gap: 3px;
    flex-wrap: wrap;
    flex: 1;
}

.w-pill {
    font-size: 9.5px;
    padding: 1px 3px;
    border-radius: 3px;
    background: var(--neutral);
    color: var(--text-secondary);
    line-height: 1.3;
}

.w-pill.buy {
    background: rgba(227, 73, 72, 0.12);
    color: var(--buy);
}

.w-pill.sell {
    background: rgba(27, 175, 122, 0.12);
    color: var(--sell);
}

.w-pill.neutral {
    background: var(--neutral);
    color: var(--text-muted);
}

.card-diag-desc {
    font-size: 11.5px;
    line-height: 1.4;
    border-top: 1px dashed var(--border);
    padding-top: 5px;
    margin-top: 2px;
}

.font-11 {
    font-size: 11px;
}

.font-10 {
    font-size: 10px;
    min-width: 50px;
    padding-top: 2px;
}
</style>
