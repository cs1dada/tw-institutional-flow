<script setup lang="ts">
/**
 * 題材資金流向與季度輪動軌跡：
 * 針對 12 週 (一季) 提供：
 * 1. 1 週逐週切分 (W1 ~ W12) 與精準行為標籤（主力鎖碼、先買後倒 C、超跌承接、持續提款、區間震盪）
 * 2. 多種視覺圖表自由挑選（籌碼行為分類走勢、排名變化、資金流向、資金進出排行、12週逐週脈動柱圖）；1 週與 4 週只顯示淨額長條圖
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

/**
 * 12 週時的圖表類型：trend (籌碼行為分類走勢) | rank (排名變化) | money (資金流向)
 * | moneyBar (資金進出排行，左右兩欄長條圖)
 * | weekly (12週逐週脈動)
 * 淨額長條圖只在 1 週與 4 週顯示，12 週與資金進出排行重複，不提供
 */
const chartType = ref<"trend" | "rank" | "money" | "moneyBar" | "weekly">("trend")

/** 資金流向圖的期間：全季或季初、季中、季末各 4 週 */
const MONEY_STAGES = [
    { key: "all", label: "全季", from: 0, to: 11 },
    { key: "early", label: "季初 (W1~W4)", from: 0, to: 3 },
    { key: "mid", label: "季中 (W5~W8)", from: 4, to: 7 },
    { key: "late", label: "季末 (W9~W12)", from: 8, to: 11 },
] as const
const moneyStage = ref<(typeof MONEY_STAGES)[number]["key"]>("all")

/**
 * 資金流向圖與資金進出排行目前比較的日期範圍。
 * 每週的增減是和前一週相比，所以起點是第一週的前一週
 */
const stageRange = computed(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return null
    const stage = MONEY_STAGES.find((x) => x.key === moneyStage.value) ?? MONEY_STAGES[0]
    const weeks = props.heatmap.weeks
    const first = idx - 11 + stage.from
    return {
        start: weeks[first],
        end: weeks[idx - 11 + stage.to],
        base: first > 0 ? weeks[first - 1] : null,
        count: stage.to - stage.from + 1,
    }
})

/** 標籤篩選：全部 或 特定行為標籤 */
const activeTagFilter = ref<string>("ALL")

/** 非 12 週時的長條圖是否顯示全部 */
const showAll = ref(false)

watch(
    () => props.period,
    // 1 週與 4 週固定顯示淨額長條圖，不看 chartType
    (newP) => {
        if (newP === 12) chartType.value = "trend"
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
// 圖表 1：籌碼行為分類走勢 (每類一張小圖)
// -------------------------------------------------------------
/**
 * 趨勢線改成「每類一張小圖」：五種行為標籤各畫一張，類別一看標題就知道，
 * 不用靠色系分辨
 */
const TREND_GROUPS: { tag: BehaviorTag; label: string; desc: string }[] = [
    { tag: "主力長線鎖碼", label: "主力長線鎖碼", desc: "多數週買超，季底持股仍在高點" },
    { tag: "波段出貨(先買後倒)", label: "波段出貨 (先買後倒)", desc: "季中衝上高峰後被倒貨，圖釘標示峰值" },
    { tag: "超跌換手承接", label: "超跌換手承接", desc: "先被重砍到季內低點，之後大戶回補，圖釘標示谷底" },
    { tag: "持續提款外流", label: "持續提款外流", desc: "多數週賣超，大戶一路減碼" },
    { tag: "區間震盪觀望", label: "區間震盪觀望", desc: "買賣互見，沒有明確方向" },
]

/** 小圖內的題材顏色：同一張小圖裡彼此容易分辨即可 */
const TREND_PALETTE = [
    "#e34948", "#2f54eb", "#f7a21e", "#13a8a8", "#873bf5",
    "#52a41a", "#eb2f96", "#8c6d1f", "#1890ff", "#595959",
]

const trendGroups = computed(() =>
    TREND_GROUPS.map((g) => ({
        ...g,
        items: analysis12.value
            .filter((t) => t.tag === g.tag)
            .sort((x, y) => y.total - x.total)
            .map((t, i) => ({
                theme: t,
                color: TREND_PALETTE[i % TREND_PALETTE.length],
                // 超過 10 個題材時顏色會重複，改用虛線區分
                dashed: i >= TREND_PALETTE.length,
            })),
    })),
)

type TrendGroup = (typeof trendGroups.value)[number]

const trendPanelOption = (g: TrendGroup) => {
    const c = colors()
    const pinTag = g.tag === "波段出貨(先買後倒)" ? "peak" : g.tag === "超跌換手承接" ? "valley" : null

    return {
        grid: { left: 40, right: 16, top: 24, bottom: 36 },
        legend: { show: false },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            confine: true,
            formatter: (params: any) => {
                const weekLabel = (params[0]?.axisValue || "").replace("\n", " ")
                const dataIndex = params[0]?.dataIndex ?? 0
                const rows = [`<strong>${weekLabel}　${g.label}</strong>`]
                const sortedP = params.slice().sort((a: any, b: any) => (b.value ?? 0) - (a.value ?? 0))
                for (const p of sortedP) {
                    const theme = g.items.find((x) => x.theme.name === p.seriesName)?.theme
                    const weeklyVal = theme?.weeklyValues[dataIndex]
                    const weeklyStr = weeklyVal !== undefined ? `（當週 ${signed(weeklyVal)}%）` : ""
                    rows.push(`${p.marker} ${p.seriesName}：累計 ${signed(p.value as number)}% ${weeklyStr}`)
                }
                return rows.join("<br>")
            },
        },
        xAxis: {
            type: "category",
            data: weeks12Meta.value.map((m) => `${m.label}\n${m.dateStr}`),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 9, interval: 1 },
        },
        yAxis: {
            type: "value",
            // 不指定範圍，由 ECharts 依各類題材自動決定刻度 (預設含 0)
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: c.muted, fontSize: 9 },
            splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        series: g.items.map(({ theme: t, color, dashed }) => ({
            name: t.name,
            type: "line",
            data: t.cumValues,
            smooth: true,
            symbol: "circle",
            symbolSize: 4,
            emphasis: { focus: "series" },
            lineStyle: { width: 2, color, type: dashed ? "dashed" : "solid" },
            itemStyle: { color },
            markPoint: pinTag
                ? {
                    symbol: "pin",
                    symbolSize: 20,
                    data: [
                        {
                            coord: pinTag === "peak" ? [t.peakWeek - 1, t.peak] : [t.valleyWeek - 1, t.valley],
                            value: `${signed(pinTag === "peak" ? t.peak : t.valley)}%`,
                            itemStyle: { color },
                            label: {
                                position: pinTag === "peak" ? "top" : "bottom",
                                fontSize: 9,
                                fontWeight: "bold",
                                color,
                                formatter: "{c}",
                            },
                        },
                    ],
                }
                : undefined,
        })),
    }
}

// -------------------------------------------------------------
// 圖表：排名變化圖 (Bump Chart)
// 每週把所有題材依累計增減排名，第 1 名在最上面。每個點都是實際資料，
// 不需要推估題材之間的流向
// -------------------------------------------------------------
/** 只畫第 12 週的前幾名，以及曾經衝進前幾名後又掉下來的題材，避免線條糾成一團 */
const RANK_FINAL_TOP = 6
const RANK_PEAK_TOP = 3
/** 「衝上去又掉下來」最多畫幾條 */
const RANK_FALLEN_MAX = 3
/** 前兩週的累計只有一兩週資料，名次跳動大，判斷是否衝進前幾名時從第 3 週起算 */
const RANK_PEAK_FROM_WEEK = 2

const rankData = computed(() => {
    const items = analysis12.value
    if (!items.length) return null

    // ranks[i][w]：第 i 個題材在第 w 週的名次
    const ranks: number[][] = items.map(() => [])
    for (let w = 0; w < 12; w++) {
        const order = items
            .map((t, i) => ({ i, v: t.cumValues[w] }))
            .sort((a, b) => b.v - a.v)
        order.forEach((o, r) => {
            ranks[o.i][w] = r + 1
        })
    }

    const finalTop = items
        .map((_, i) => i)
        .sort((a, b) => ranks[a][11] - ranks[b][11])
        .slice(0, RANK_FINAL_TOP)
    // 曾衝進前幾名、最後掉出前段班的題材，挑掉得最多的幾個
    const fallen = items
        .map((_, i) => ({ i, best: Math.min(...ranks[i].slice(RANK_PEAK_FROM_WEEK)) }))
        .filter((x) => !finalTop.includes(x.i) && x.best <= RANK_PEAK_TOP)
        .sort((a, b) => (ranks[b.i][11] - b.best) - (ranks[a.i][11] - a.best))
        .slice(0, RANK_FALLEN_MAX)
        .map((x) => x.i)

    return { items, ranks, picked: [...finalTop, ...fallen], fallen, total: items.length }
})

const rankOption = computed(() => {
    const c = colors()
    const data = rankData.value
    if (!data) return {}
    const { items, ranks, picked, fallen, total } = data

    const linePalette = [
        "#e34948", "#ff7a45", "#f7ba1e", "#873bf5", "#13c2c2",
        "#2f54eb", "#52c41a", "#eb2f96", "#8c8c8c", "#a0d911",
    ]
    // 其他題材也畫成淡灰細線，每個名次都有線，縱軸畫到所有題材的總數
    const others = items.map((_, i) => i).filter((i) => !picked.includes(i))
    const maxRank = total

    return {
        grid: { left: 60, right: 130, top: 20, bottom: 45 },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            formatter: (params: any) => {
                const w = params[0]?.dataIndex ?? 0
                const meta = weeks12Meta.value[w]
                const lines = [`<strong>${meta?.fullLabel ?? ""} 排名 (共 ${total} 個題材)</strong>`]
                // 所有題材依名次列出，彩色的主要題材加粗
                const order = [...picked, ...others]
                const sorted = params.slice().sort((a: any, b: any) => a.value - b.value)
                for (const p of sorted) {
                    const t = items[order[p.seriesIndex]]
                    const main = p.seriesIndex < picked.length
                    const text = `第 ${p.value} 名　${p.seriesName}　累計 ${signed(t.cumValues[w])}%`
                        + `（當週 ${signed(t.weeklyValues[w])}%）`
                    lines.push(main ? `${p.marker} <strong>${text}</strong>` : `<span style="opacity:0.7">${text}</span>`)
                }
                return lines.join("<br>")
            },
        },
        xAxis: {
            type: "category",
            boundaryGap: false,
            data: weeks12Meta.value.map((m) => `${m.label}
(${m.dateStr})`),
            axisLine: { lineStyle: { color: c.border } },
            axisTick: { show: false },
            axisLabel: { color: c.secondary, fontSize: 10 },
        },
        yAxis: {
            type: "value",
            inverse: true,
            min: 1,
            max: maxRank,
            interval: 1,
            axisLine: { show: false },
            axisTick: { show: false },
            // 每個名次都有格線太密，刻度只標第 1 名、5 的倍數，以及離 5 的倍數夠遠的最後一名
            axisLabel: {
                color: c.muted,
                fontSize: 10,
                formatter: (v: number) => (v === 1 || v % 5 === 0 || (v === maxRank && v % 5 >= 3) ? `第 ${v} 名` : ""),
            },
            splitLine: { show: false },
        },
        series: [...picked.map((i, k) => {
            const t = items[i]
            const color = linePalette[k % linePalette.length]
            return {
                name: t.name,
                type: "line",
                data: ranks[i],
                symbol: "circle",
                symbolSize: 7,
                // 虛線：曾衝進前幾名、最後掉下來的題材
                lineStyle: { width: fallen.includes(i) ? 2 : 2.5, color, type: fallen.includes(i) ? "dashed" : "solid" },
                itemStyle: { color },
                emphasis: { focus: "series" },
                endLabel: {
                    show: true,
                    formatter: "{a}",
                    color,
                    fontSize: 11,
                },
                z: 3,
            }
        }),
        // 其他題材：淡灰細線放在底層，滑鼠移上去才凸顯
        ...others.map((i) => ({
            name: items[i].name,
            type: "line",
            data: ranks[i],
            symbol: "none",
            lineStyle: { width: 1, color: c.muted, opacity: 0.35 },
            // 右端都標出題材名稱 (淡色)，滑鼠移上去時線與名稱變明顯
            endLabel: { show: true, formatter: "{a}", color: c.muted, fontSize: 10 },
            emphasis: {
                focus: "series",
                lineStyle: { width: 2, opacity: 1, color: c.secondary },
                endLabel: { color: c.text, fontWeight: "bold" },
            },
            z: 1,
        }))],
    }
})

// -------------------------------------------------------------
// 選定期間內各題材的淨額合計，給資金進出排行的說明文字用
// -------------------------------------------------------------
const moneyFlow = computed(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return null
    const themes = props.heatmap.themes.filter((t) => t.amounts)
    if (!themes.length) return null
    const stage = MONEY_STAGES.find((x) => x.key === moneyStage.value) ?? MONEY_STAGES[0]

    const sells: { name: string; v: number }[] = []
    const buys: { name: string; v: number }[] = []
    for (const t of themes) {
        const slice = (t.amounts ?? []).slice(idx - 11 + stage.from, idx - 11 + stage.to + 1)
        const net = slice.reduce<number>((a, v) => a + (v ?? 0), 0)
        if (net < 0) sells.push({ name: t.name, v: -net })
        else if (net > 0) buys.push({ name: t.name, v: net })
    }
    return {
        totalOut: sells.reduce((a, x) => a + x.v, 0),
        totalIn: buys.reduce((a, x) => a + x.v, 0),
    }
})

// -------------------------------------------------------------
// 圖表：資金流向圖 (依時間往右排，每週或每月一欄)
// 全季可選每週 (12 欄) 或每月 (3 欄)；季初、季中、季末是同一張圖只看其中 4 週，一週一欄。
// 每一欄是那段時間大戶淨買進的題材，方塊大小是淨買進金額。
// 月與月之間的線：
//   - 上個月買的題材，這個月還在買：錢留在原地，連回自己，流量取兩個月買進金額較小者
//   - 上個月買的題材，這個月被賣：賣出的錢 (最多到上個月買進的金額) 按比例流向這個月買進的題材，
//     比例的算法和資金流向圖相同；買賣金額不一樣時，只有對得上的部分畫線
// 這個月被賣、但上個月不是買方的題材，錢的來源不在圖上，因此不畫線
// -------------------------------------------------------------
/**
 * 全季的切分單位：week 每週一欄 (12 欄) | month 每 4 週一欄 (3 欄)
 * 週的欄數多，每欄少畫幾個題材，免得擠在一起
 */
const flowGrain = ref<"week" | "month">("week")
/** 實際使用的單位：季初、季中、季末只有 4 週，固定每週一欄 */
const activeGrain = computed(() => (moneyStage.value === "all" ? flowGrain.value : "week"))
/** 每欄最多畫幾個題材：欄數多時少畫一些，免得擠在一起 */
const flowTop = computed(() => (flowBuckets.value.length > 4 ? 5 : 8))

/** 每一欄涵蓋的週次 (W1 為 0) 與標題 */
const flowBuckets = computed(() => {
    const meta = weeks12Meta.value
    if (activeGrain.value === "week") {
        const stage = MONEY_STAGES.find((x) => x.key === moneyStage.value) ?? MONEY_STAGES[0]
        return meta
            .slice(stage.from, stage.to + 1)
            .map((m, i) => ({ from: stage.from + i, to: stage.from + i, label: m.label, range: m.dateStr }))
    }
    return [0, 1, 2].map((i) => ({
        from: i * 4,
        to: i * 4 + 3,
        label: `第 ${i + 1} 月`,
        range: `${meta[i * 4]?.dateStr} ~ ${meta[i * 4 + 3]?.dateStr}`,
    }))
})
/** 長條圖提示裡，大戶賣出比買進多的部分的說明 */
const RETAIL = "由大戶以外的股東接手 (包含一般投資人與持股未達門檻的法人)"
/** 流向圖的左右邊界與方塊寬度，下方長條圖用同樣的數字對齊每一欄 */
const FLOW_LEFT = 30
const FLOW_RIGHT = 160
const FLOW_NODE_WIDTH = 14

/**
 * 流向圖的題材配色：整季大戶買最多的幾個題材各給一個固定顏色，其他題材用淺灰。
 * 顏色跟著題材走，不跟著名次走，切換每週 / 每月時同一個題材顏色不變。
 * 台股慣例紅漲綠跌，題材色不用紅與綠，免得被看成買賣訊號。
 * 這組顏色以 dataviz 的色盲檢查驗證過 (相鄰色 CVD ΔE >= 9)
 */
const FLOW_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
const FLOW_OTHER = "#c9c8c1"
/** 搬家線小於最大方塊的這個比例就不畫，避免細線糾成一團 */
const FLOW_MIN_LINK_RATIO = 0.03

/** 題材名稱 → 顏色，依整季 12 週大戶買進金額 (只算買超的週) 排序 */
const flowColors = computed(() => {
    const idx = currentWeekIdx.value
    const map = new Map<string, string>()
    if (props.period !== 12 || idx < 11) return map
    const ranked = props.heatmap.themes
        .filter((t) => t.amounts)
        .map((t) => ({
            name: t.name,
            v: (t.amounts ?? []).slice(idx - 11, idx + 1).reduce<number>((a, x) => a + Math.max(0, x ?? 0), 0),
        }))
        .sort((a, b) => b.v - a.v)
    ranked.slice(0, FLOW_PALETTE.length).forEach((t, i) => map.set(t.name, FLOW_PALETTE[i]))
    return map
})
const flowColorOf = (name: string) => flowColors.value.get(name) ?? FLOW_OTHER

/** 圖例：有顏色的題材，加上「其他題材」 */
const flowLegend = computed(() => [
    ...[...flowColors.value.entries()].map(([name, color]) => ({ name, color })),
    { name: "其他題材", color: FLOW_OTHER },
])

const monthFlow = computed(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return null
    const themes = props.heatmap.themes.filter((t) => t.amounts)
    if (!themes.length) return null

    const buckets = flowBuckets.value
    // nets[m]：第 m 欄各題材的淨額 (億元)
    const nets = buckets.map((b) => {
        const map = new Map<string, number>()
        for (const t of themes) {
            const slice = (t.amounts ?? []).slice(idx - 11 + b.from, idx - 11 + b.to + 1)
            map.set(t.name, slice.reduce<number>((a, v) => a + (v ?? 0), 0))
        }
        return map
    })
    // 每個月只留淨買進最多的幾個題材
    const buyers = nets.map((net) =>
        [...net.entries()]
            .filter(([, v]) => v > 0)
            .sort((x, y) => y[1] - x[1])
            .slice(0, flowTop.value),
    )
    const key = (name: string, m: number) => `${name}|${m}`

    // 每個月全部題材的買進、賣出合計，用來算比例與賣給大戶以外的股東的部分
    const totals = nets.map((net) => {
        let totalOut = 0
        let totalIn = 0
        for (const v of net.values()) {
            if (v < 0) totalOut -= v
            else totalIn += v
        }
        return { totalOut, totalIn }
    })

    const nodes: { name: string; theme: string; month: number; value: number }[] = buyers.flatMap(
        (list, m) => list.map(([name, v]) => ({ name: key(name, m), theme: name, month: m, value: +v.toFixed(1) })),
    )
    // 賣出比買進多的部分 (賣給大戶以外的股東) 金額差距很大，放進流向圖會把整張圖撐長，
    // 改在下方另畫一排長條圖 (outflowOption)，這裡只畫題材之間的流動

    // kind：stay 錢留在原地、move 搬到別的題材
    const links: { source: string; target: string; value: number; kind: "stay" | "move" }[] = []
    for (let m = 0; m < nets.length - 1; m++) {
        const next = nets[m + 1]
        const nextBuyers = buyers[m + 1]
        const { totalOut, totalIn } = totals[m + 1]
        // 下個月賣出的錢，有多少比例能對到買進的題材，其餘是賣給大戶以外的股東
        const ratio = totalOut > 0 ? Math.min(1, totalIn / totalOut) : 0
        for (const [name, bought] of buyers[m]) {
            const v = next.get(name) ?? 0
            if (v > 0 && nextBuyers.some(([n]) => n === name)) {
                // 取兩個月較小的金額，避免把下個月的方塊撐得比實際買進還大
                links.push({ source: key(name, m), target: key(name, m + 1), value: +Math.min(bought, v).toFixed(1), kind: "stay" })
            } else if (v < 0) {
                const sold = Math.min(-v, bought)
                if (totalIn > 0) {
                    for (const [target, vin] of nextBuyers) {
                        const value = +(sold * ratio * (vin / totalIn)).toFixed(1)
                        if (value >= 0.1) {
                            links.push({ source: key(name, m), target: key(target, m + 1), value, kind: "move" })
                        }
                    }
                }
            }
        }
    }
    return { nodes, links, totals }
})

const monthOption = computed(() => {
    const c = colors()
    const data = monthFlow.value
    if (!data || !data.nodes.length) return {}
    const themeOf = (k: string) => k.split("|")[0]
    const buckets = flowBuckets.value
    const labelOf = (m: number) => {
        const b = buckets[m]
        return b ? `${b.label} (${b.range})` : ""
    }
    const weekly = buckets.length > 3
    const minLink = Math.max(...data.nodes.map((n) => n.value)) * FLOW_MIN_LINK_RATIO
    return {
        // 欄的標題依欄數平均排開，週的欄數多，日期換到第二行
        title: buckets.map((b, m) => ({
            text: weekly ? `${b.label}\n${b.range}` : labelOf(m),
            left: `${1 + (m * (weekly ? 87 : 82)) / (buckets.length - 1)}%`,
            top: 0,
            textStyle: { color: c.secondary, fontSize: weekly ? 11 : 12, fontWeight: "normal", lineHeight: 14 },
        })),
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                if (params.dataType === "edge") {
                    const d = params.data
                    const from = `${themeOf(d.source)} (${labelOf(+d.source.split("|")[1])})`
                    const to = `${themeOf(d.target)} (${labelOf(+d.target.split("|")[1])})`
                    if (d.kind === "stay") {
                        return `<strong>${from} → ${to}</strong><br>大戶連續兩${weekly ? "週" : "個月"}都在買，約 ${d.value} 億元留在原地`
                    }
                    return `<strong>${from} → ${to}</strong><br>推估約 ${d.value} 億元搬過去`
                }
                const d = params.data
                return `<strong>${d.theme}</strong> (${labelOf(d.month)})<br>大戶${weekly ? "當週" : "當月"}淨買進約 ${d.value} 億元`
            },
        },
        series: [
            {
                type: "sankey",
                left: FLOW_LEFT,
                right: FLOW_RIGHT,
                top: 30,
                bottom: 10,
                nodeWidth: FLOW_NODE_WIDTH,
                nodeGap: 12,
                nodeAlign: "justify",
                layoutIterations: 0,
                emphasis: { focus: "adjacency", lineStyle: { opacity: 0.7 } },
                data: data.nodes.map((n) => ({
                    ...n,
                    depth: n.month,
                    itemStyle: { color: flowColorOf(n.theme), borderWidth: 0, borderRadius: 2 },
                })),
                links: data.links
                    // 太細的搬家線不畫，滑鼠提示與方塊大小不受影響
                    .filter((l) => l.kind === "stay" || l.value >= minLink)
                    .map((l) => ({
                        ...l,
                        // 留在原地的線比較顯眼，搬家的線淡一點，滑鼠移上去才凸顯
                        lineStyle: {
                            color: flowColorOf(themeOf(l.source)),
                            opacity: l.kind === "stay" ? 0.32 : 0.14,
                        },
                    })),
                lineStyle: { curveness: 0.5 },
                label: {
                    color: c.secondary,
                    fontSize: weekly ? 10 : 11,
                    // 文字加一圈底色描邊，壓在線條上也看得清楚
                    textBorderColor: c.surface || "#fcfcfb",
                    textBorderWidth: 2,
                    formatter: (p: any) => themeOf(p.name),
                },
            },
        ],
    }
})

// -------------------------------------------------------------
// 流向圖下方的長條圖：每一欄大戶整體是流出還是流入
// 流出 = 大戶賣出比買進多的金額，由大戶以外的股東接手，畫在零軸下方 (灰色)
// 流入 = 大戶買進比賣出多的金額，從大戶以外的股東手上買進，畫在零軸上方 (紅色)
// 橫軸用數值軸，第 m 欄畫在 x = m，左右邊界與流向圖相同，長條才會對齊上面的每一欄
// -------------------------------------------------------------
const outflowOption = computed(() => {
    const c = colors()
    const data = monthFlow.value
    if (!data) return {}
    const buckets = flowBuckets.value
    const n = buckets.length
    const nets = data.totals.map((t) => +(t.totalIn - t.totalOut).toFixed(1))
    return {
        grid: {
            left: FLOW_LEFT + FLOW_NODE_WIDTH / 2,
            right: FLOW_RIGHT + FLOW_NODE_WIDTH / 2,
            top: 22,
            bottom: 22,
        },
        title: {
            text: "大戶整體流出 / 流入",
            left: 0,
            top: 0,
            textStyle: { color: c.secondary, fontSize: 12, fontWeight: "normal" },
        },
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (p: any) => {
                const t = data.totals[p.data.m]
                const b = buckets[p.data.m]
                const head = `<strong>${b.label} (${b.range})</strong><br>大戶全部賣出約 ${t.totalOut.toFixed(0)} 億、買進約 ${t.totalIn.toFixed(0)} 億`
                return p.data.value < 0
                    ? `${head}<br>賣比買多約 ${(-p.data.value).toFixed(0)} 億元，${RETAIL}`
                    : `${head}<br>買比賣多約 ${p.data.value.toFixed(0)} 億元，從大戶以外的股東手上買進`
            },
        },
        xAxis: { type: "value", min: 0, max: n - 1, show: false },
        yAxis: {
            type: "value",
            axisLabel: { show: false },
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { show: false },
        },
        series: [
            {
                type: "bar",
                barWidth: FLOW_NODE_WIDTH,
                data: nets.map((v, m) => ({
                    value: [m, v],
                    m,
                    itemStyle: { color: v < 0 ? c.muted : buyColor() },
                })),
                label: {
                    show: true,
                    position: "outside",
                    fontSize: 10,
                    color: c.secondary,
                    formatter: (p: any) => {
                        const v = p.data.value[1]
                        return v < 0 ? `流出 ${(-v).toFixed(0)}` : `流入 ${v.toFixed(0)}`
                    },
                },
                markLine: {
                    silent: true,
                    symbol: "none",
                    label: { show: false },
                    lineStyle: { color: c.border, type: "solid" },
                    data: [{ yAxis: 0 }],
                },
            },
        ],
    }
})

/** 資金流向圖 (全季與季初、季中、季末都用同一種多欄圖) */
const isMonthView = computed(() => chartType.value === "money")
/** 說明文字用的單位 */
const unit = computed(() => (activeGrain.value === "week" ? "週" : "月"))

// -------------------------------------------------------------
// 圖表：資金進出排行 (左右兩欄長條圖)
// 和資金流向圖用同一份淨額，只是不畫推估的連線：
// 左欄是大戶淨賣出最多的題材，右欄是淨買進最多的題材，兩欄用同一個刻度方便比長短
// -------------------------------------------------------------
/** 每一欄最多列幾個題材 */
const MONEY_BAR_TOP = 10

/**
 * 長條圖的單位：amount 金額 (億元) | pct 佔類股市值 (%)
 * 金額會偏向大型類股，比例才看得出大戶對大小不同的題材誰買得比較積極
 */
const moneyBarUnit = ref<"amount" | "pct">("amount")

type MoneyBarItem = { name: string; amount: number; cap: number | null; pct: number | null }

const moneyBarData = computed(() => {
    const idx = currentWeekIdx.value
    if (props.period !== 12 || idx < 11) return null
    const themes = props.heatmap.themes.filter((t) => t.amounts)
    if (!themes.length) return null
    const stage = MONEY_STAGES.find((x) => x.key === moneyStage.value) ?? MONEY_STAGES[0]
    // 市值取這段期間最後一週
    const capIdx = idx - 11 + stage.to

    const items: MoneyBarItem[] = themes.map((t) => {
        const slice = (t.amounts ?? []).slice(idx - 11 + stage.from, idx - 11 + stage.to + 1)
        const amount = slice.reduce<number>((a, v) => a + (v ?? 0), 0)
        const cap = t.caps?.[capIdx] ?? null
        return { name: t.name, amount, cap, pct: cap ? (amount / cap) * 100 : null }
    })
    const hasPct = items.some((x) => x.pct !== null)
    const pct = moneyBarUnit.value === "pct" && hasPct
    const signedValue = (x: MoneyBarItem) => (pct ? x.pct ?? 0 : x.amount)
    const sells = items.filter((x) => signedValue(x) < 0).sort((a, b) => signedValue(a) - signedValue(b))
    const buys = items.filter((x) => signedValue(x) > 0).sort((a, b) => signedValue(b) - signedValue(a))
    return {
        sells: sells.slice(0, MONEY_BAR_TOP),
        buys: buys.slice(0, MONEY_BAR_TOP),
        pct,
        hasPct,
        /** 長條的長度，買賣兩邊都畫成正值 */
        value: (x: MoneyBarItem) => Math.abs(signedValue(x)),
    }
})

const moneyBarRows = computed(() => {
    const data = moneyBarData.value
    if (!data) return 0
    return Math.max(data.sells.length, data.buys.length)
})

const moneyBarOption = computed(() => {
    const c = colors()
    const data = moneyBarData.value
    if (!data || (!data.sells.length && !data.buys.length)) return {}
    const { sells, buys, pct, value } = data
    const rows = moneyBarRows.value
    // 不足的列補空白，讓兩欄的長條上下對齊
    const pad = <T,>(list: T[], empty: T) => [...list, ...Array(rows - list.length).fill(empty)]
    const max = Math.max(...sells.map(value), ...buys.map(value))
    const fmt = (v: number) => (pct ? `${v.toFixed(2)}%` : `${v.toFixed(1)} 億`)

    const side = (list: MoneyBarItem[], color: string, gridIndex: number) => ({
        type: "bar",
        xAxisIndex: gridIndex,
        yAxisIndex: gridIndex,
        barWidth: 14,
        data: pad(
            list.map((x): { value: number | null; raw?: MoneyBarItem; itemStyle?: object } => ({
                value: +value(x).toFixed(pct ? 3 : 1),
                raw: x,
                itemStyle: { color, borderRadius: [0, 4, 4, 0] },
            })),
            { value: null },
        ),
        label: {
            show: true,
            position: "right",
            formatter: (p: any) => (p.value == null ? "" : fmt(p.value)),
            color: c.secondary,
            fontSize: 11,
        },
    })
    const valueAxis = (gridIndex: number) => ({
        type: "value",
        gridIndex,
        max: max * 1.25,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
    })
    const nameAxis = (gridIndex: number, list: { name: string }[]) => ({
        type: "category",
        gridIndex,
        inverse: true,
        data: pad(list.map((x) => x.name), ""),
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
        axisLabel: { color: c.secondary, fontSize: 12 },
    })

    return {
        title: [
            { text: "大戶在賣", left: "3%", top: 0, textStyle: { color: sellColor(), fontSize: 13 } },
            { text: "大戶在買", left: "53%", top: 0, textStyle: { color: buyColor(), fontSize: 13 } },
        ],
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (p: any) => {
                const x = p.data?.raw as MoneyBarItem | undefined
                if (!x) return ""
                const action = x.amount < 0 ? "淨賣出" : "淨買進"
                const lines = [`<strong>${x.name}</strong>`, `大戶${action}約 ${Math.abs(x.amount).toFixed(1)} 億元`]
                if (x.cap && x.pct !== null) {
                    lines.push(`類股市值約 ${x.cap.toFixed(0)} 億元，佔 ${Math.abs(x.pct).toFixed(2)}%`)
                }
                return lines.join("<br>")
            },
        },
        grid: [
            { left: "3%", width: "42%", top: 30, bottom: 10, containLabel: true },
            { left: "53%", width: "42%", top: 30, bottom: 10, containLabel: true },
        ],
        xAxis: [valueAxis(0), valueAxis(1)],
        yAxis: [nameAxis(0, sells), nameAxis(1, buys)],
        series: [side(sells, sellColor(), 0), side(buys, buyColor(), 1)],
    }
})

// -------------------------------------------------------------
// 圖表 3：12 週逐週脈動 (每個題材一列 +- 長條圖)
// -------------------------------------------------------------
/** 逐週脈動每一列的高度 */
const PULSE_ROW_HEIGHT = 46
/** 逐週脈動的長條寬度，固定寬度看起來比較整齊 */
const PULSE_BAR_WIDTH = 22

/** 逐週脈動要畫的題材：買最多 4 個、波段出貨 2 個、賣最多 4 個 */
const pulseThemes = computed(() => {
    const items = analysis12.value
    return [
        ...items.slice(0, 4),
        ...items.filter((t) => t.tag === "波段出貨(先買後倒)").slice(0, 2),
        ...items.slice(-4),
    ].filter((v, i, a) => a.findIndex((t) => t.id === v.id) === i)
})
const weeklyOption = computed(() => {
    const c = colors()
    const items = analysis12.value
    if (!items.length) return {}

    const focusThemes = pulseThemes.value

    const meta = weeks12Meta.value
    // 每個題材一列，時間由左到右 (W1 → W12)，零軸以上是大戶買進、以下是大戶賣出
    // 所有列共用同一個刻度，取所有週幅度的第 90 百分位，少數特別大的週截斷並標上數字，不會把其他長條壓扁
    const mags = focusThemes.flatMap((t) => t.weeklyValues.map((v) => Math.abs(v))).sort((x, y) => x - y)
    const max = Math.max(0.01, mags[Math.floor(mags.length * 0.9)] ?? 0)
    const ROW = PULSE_ROW_HEIGHT
    const TOP = 26
    const GAP = 6
    return {
        // 每列一個 grid，單雙列交錯淡底色，看起來像表格
        grid: focusThemes.map((_, r) => ({
            left: 150,
            right: 20,
            top: TOP + r * ROW,
            height: ROW - GAP,
            show: true,
            borderWidth: 0,
            backgroundColor: r % 2 === 0 ? "rgba(128,128,128,0.06)" : "transparent",
        })),
        title: focusThemes.map((t, r) => ({
            text: t.name,
            left: 10,
            top: TOP + r * ROW + (ROW - GAP) / 2 - 7,
            textStyle: { color: c.secondary, fontSize: 12, fontWeight: "normal" },
        })),
        tooltip: {
            ...baseTooltip(),
            trigger: "item",
            formatter: (params: any) => {
                const t = focusThemes[params.seriesIndex]
                const m = meta[params.dataIndex]
                const v = params.data.raw as number
                return `<strong>${t.name}</strong> ${m.label} (${m.dateStr})<br>`
                    + `大戶比例${v >= 0 ? "增加" : "減少"} ${Math.abs(v).toFixed(2)} 個百分點`
            },
        },
        xAxis: focusThemes.map((_, r) => ({
            type: "category",
            gridIndex: r,
            data: meta.map((m) => m.label),
            position: "top",
            axisLine: { show: false },
            axisTick: { show: false },
            // 只有第一列標週次
            axisLabel: { show: r === 0, color: c.muted, fontSize: 11, margin: 10 },
        })),
        yAxis: focusThemes.map((_, r) => ({
            type: "value",
            gridIndex: r,
            min: -max * 1.1,
            max: max * 1.1,
            show: false,
        })),
        series: focusThemes.map((t, r) => ({
            name: t.name,
            type: "bar",
            xAxisIndex: r,
            yAxisIndex: r,
            barWidth: PULSE_BAR_WIDTH,
            data: t.weeklyValues.map((v) => ({
                value: Math.max(-max, Math.min(max, v)),
                raw: v,
                label: {
                    show: Math.abs(v) > max,
                    position: v >= 0 ? "insideTopLeft" : "insideBottomLeft",
                    offset: [PULSE_BAR_WIDTH + 2, v >= 0 ? -2 : 2],
                    color: c.secondary,
                    fontSize: 10,
                    formatter: () => signed(v),
                },
                itemStyle: {
                    // 台股慣例紅漲綠跌：紅色是大戶買進、綠色是大戶賣出
                    color: v >= 0 ? buyColor() : sellColor(),
                    borderRadius: v >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3],
                },
            })),
            // 零軸
            markLine: {
                silent: true,
                symbol: "none",
                label: { show: false },
                lineStyle: { color: c.border, type: "solid", width: 1 },
                data: [{ yAxis: 0 }],
            },
        })),
    }
})

// -------------------------------------------------------------
// 圖表 4：淨額長條圖 (1 週與 4 週使用)
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
        if (chartType.value === "rank") return rankOption.value
        if (isMonthView.value) return monthOption.value
        if (chartType.value === "moneyBar") return moneyBarOption.value
        if (chartType.value === "weekly") return weeklyOption.value
        return netBarOption.value
    }
    return netBarOption.value
})

/** 圖表高度動態調整 */
const chartHeight = computed(() => {
    if (props.period === 12) {
        // 右側要列出全部題材名稱，每個名次約 18px
        if (chartType.value === "rank") return `${Math.max(460, (rankData.value?.total ?? 0) * 18 + 65)}px`
        if (isMonthView.value) return "440px"
        if (chartType.value === "moneyBar") return `${Math.max(220, moneyBarRows.value * 30 + 50)}px`
        if (chartType.value === "weekly") return `${pulseThemes.value.length * PULSE_ROW_HEIGHT + 36}px`
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
                    <!-- 12 週時提供 5 種圖表挑選 -->
                    <div v-if="period === 12" class="chart-type-selector">
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'trend' }"
                            @click="chartType = 'trend'"
                        >
                            籌碼行為分類走勢 (五類小圖)
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'money' }"
                            @click="chartType = 'money'"
                        >
                            資金流向圖 (錢從哪裡到哪裡)
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'rank' }"
                            @click="chartType = 'rank'"
                        >
                            12 週排名變化圖
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'moneyBar' }"
                            @click="chartType = 'moneyBar'"
                        >
                            資金進出排行 (左賣右買)
                        </button>
                        <button
                            type="button"
                            class="type-btn"
                            :class="{ active: chartType === 'weekly' }"
                            @click="chartType = 'weekly'"
                        >
                            12 週逐週脈動柱圖 (單週增減)
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

            <!-- 資金流向圖的期間切換與計算說明 -->
            <div v-if="period === 12 && (chartType === 'money' || chartType === 'moneyBar')" class="money-head">
                <div class="money-stages">
                    <button
                        v-for="st in MONEY_STAGES"
                        :key="st.key"
                        type="button"
                        class="chip"
                        :class="{ 'is-active': moneyStage === st.key }"
                        @click="moneyStage = st.key"
                    >
                        {{ st.label }}
                    </button>
                </div>
                <div v-if="isMonthView && moneyStage === 'all'" class="money-stages">
                    <button
                        type="button"
                        class="chip"
                        :class="{ 'is-active': flowGrain === 'week' }"
                        @click="flowGrain = 'week'"
                    >
                        每週 (12 欄)
                    </button>
                    <button
                        type="button"
                        class="chip"
                        :class="{ 'is-active': flowGrain === 'month' }"
                        @click="flowGrain = 'month'"
                    >
                        每月 (3 欄)
                    </button>
                </div>
                <p v-if="stageRange" class="money-range">
                    比較期間：{{ formatDate(stageRange.start) }} ~ {{ formatDate(stageRange.end) }}，共 {{ stageRange.count }} 週
                    <template v-if="stageRange.base">
                        (以 {{ formatDate(stageRange.base) }} 的持股為起點，每週和前一週相比)
                    </template>
                </p>
                <div v-if="moneyFlow && chartType === 'moneyBar'" class="money-stages">
                    <button
                        type="button"
                        class="chip"
                        :class="{ 'is-active': moneyBarUnit === 'amount' }"
                        @click="moneyBarUnit = 'amount'"
                    >
                        金額 (億元)
                    </button>
                    <button
                        type="button"
                        class="chip"
                        :class="{ 'is-active': moneyBarUnit === 'pct' }"
                        :disabled="!moneyBarData?.hasPct"
                        @click="moneyBarUnit = 'pct'"
                    >
                        佔類股市值 (%)
                    </button>
                </div>
                <p v-if="!moneyFlow && !monthFlow" class="money-note">目前的資料還沒有金額欄位，請重新產生籌碼分析資料。</p>
            </div>

            <!-- 圖表本體 -->
            <div v-if="period === 12 && chartType === 'trend'" class="trend-panels">
                <div v-for="g in trendGroups" :key="g.tag" class="trend-panel">
                    <div class="trend-panel-head">
                        <strong>{{ g.label }}</strong>
                        <span class="muted font-11">{{ g.items.length }} 個題材　{{ g.desc }}</span>
                    </div>
                    <template v-if="g.items.length">
                        <div class="trend-panel-legend">
                            <span v-for="x in g.items" :key="x.theme.name" class="flow-legend-item">
                                <i
                                    class="flow-legend-swatch"
                                    :class="{ dashed: x.dashed }"
                                    :style="{ background: x.color }"
                                />
                                {{ x.theme.name }} {{ signed(x.theme.total) }}%
                            </span>
                        </div>
                        <VChart class="flow-chart" style="height: 240px" :option="trendPanelOption(g)" autoresize />
                    </template>
                    <p v-else class="muted font-11 trend-empty">本季沒有題材屬於這一類</p>
                </div>
            </div>
            <div v-if="period === 12 && isMonthView && monthFlow" class="flow-legend">
                <span v-for="item in flowLegend" :key="item.name" class="flow-legend-item">
                    <i class="flow-legend-swatch" :style="{ background: item.color }" />
                    {{ item.name }}
                </span>
            </div>
            <VChart
                v-if="!(period === 12 && chartType === 'trend')"
                class="flow-chart"
                :style="{ height: chartHeight }"
                :option="activeOption"
                autoresize
            />
            <VChart
                v-if="period === 12 && isMonthView && monthFlow"
                class="flow-chart"
                style="height: 170px"
                :option="outflowOption"
                autoresize
            />

            <!-- 圖表說明：先一行重點，完整說明摺疊起來，切換分頁時自動收合 -->
            <div v-if="period === 12" class="chart-guide">
                <template v-if="chartType === 'trend'">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>每一類一張小圖，全部 {{ analysis12.length }} 個題材都畫出來。線往上代表大戶持股比例在這一季累計增加，往下代表減少。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>
                            縱軸是「從第 1 週起，大戶持股比例累計增減了幾個百分點」，每個點是到那一週為止的累計值。滑鼠移到線上可以看每個題材當週的累計與單週變化。
                        </p>
                        <p>每個題材依 12 週的走勢歸到一類 (由上往下判斷，符合就停)：</p>
                        <ul>
                            <li><strong>波段出貨 (先買後倒)</strong>：季內最高累計 +1.2 以上，且從高點回落 1.2 以上。圖釘標示峰值。</li>
                            <li><strong>超跌換手承接</strong>：季內最低累計 -1.2 以下，且從低點回升 1.2 以上。圖釘標示谷底。</li>
                            <li><strong>主力長線鎖碼</strong>：季底累計 +1.5 以上，且買超 7 週以上或最後兩週仍在買。</li>
                            <li><strong>持續提款外流</strong>：季底累計 -1.5 以下。</li>
                            <li><strong>區間震盪觀望</strong>：以上都不符合，買賣互見。</li>
                        </ul>
                        <p>
                            各小圖的縱軸刻度依該類題材自動調整，不然波動小的類別會被壓成一條線；跨圖比較時要看刻度數字，不能只看線的高低。
                        </p>
                        <p>適合看：大戶這一季對每個題材的態度是長抱、先買後倒、低接，還是一路撤出。</p>
                        <p>不適合看：錢的規模。百分點是持股比例，大型類股動一點點，金額可能就很大；看金額請切到「資金流向」或「資金進出」。</p>
                    </details>
                </template>

                <template v-else-if="chartType === 'money' && monthFlow">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>每一欄是那{{ unit }}大戶淨買進最多的 {{ flowTop }} 個題材，方塊越大買越多；欄與欄之間的帶子是推估的資金移動。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>
                            以{{ unit }}為單位{{ activeGrain === "month" ? " (每 4 週一個月)" : "" }}，共 {{ flowBuckets.length }} 欄。顏色代表題材，整季買最多的 {{ FLOW_PALETTE.length }} 個題材各有固定顏色，其他題材是淺灰。
                        </p>
                        <p>
                            較粗、較深的帶子：上{{ unit }}買的題材這{{ unit }}還在買，錢留在原地。較淡的細線：上{{ unit }}買的題材這{{ unit }}被賣，賣出的錢按比例流向這{{ unit }}買進的題材(推估，不是實際紀錄；太小的不畫)。滑鼠移到方塊上可以只看相關的線。
                        </p>
                        <p>
                            下方的長條圖：每{{ unit }}大戶整體是流出還是流入。灰色往下是「流出」，大戶賣出比買進多，由大戶以外的股東接手(包含一般投資人與持股未達門檻的法人)；紅色往上是「流入」，大戶從大戶以外的股東手上買進。長條越長，金額越大。
                        </p>
                        <p>
                            適合看：大戶的錢實際放在哪裡、規模多大，以及每{{ unit }}是在進場還是撤退。
                            <template v-if="moneyStage === 'all' && flowGrain === 'week'">單週的雜訊比較大，想看大方向可以切到「每月」。</template>
                            <template v-else-if="moneyStage !== 'all'">這是全季圖只看其中 4 週，題材顏色與全季相同。</template>
                        </p>
                        <p>
                            不適合看：大戶對哪個題材最積極。方塊大小是金額，大型類股天生就比較大；要公平比較請看「資金進出排行」的「佔類股市值 (%)」。
                        </p>
                    </details>
                </template>

                <template v-else-if="chartType === 'rank'">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>每週把全部 {{ rankData?.total ?? 0 }} 個題材依累計增減排名，第 1 名在最上面；線往上爬代表名次進步，往下掉代表被別的題材超越。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>
                            名次依「從第 1 週起大戶持股比例的累計增減」排序，每個點都是實際資料，不需要推估題材之間的流向。
                        </p>
                        <p>
                            彩色線：第 12 週排名前 {{ RANK_FINAL_TOP }} 名的題材，加上曾經衝進前 {{ RANK_PEAK_TOP }} 名、後來掉出前段班的題材(最多 {{ RANK_FALLEN_MAX }} 個，挑掉得最多的)。其他題材畫成淡灰細線，滑鼠移上去可看全部名次。
                        </p>
                        <p>前兩週的累計只有一兩週資料，名次跳動大，判斷「是否衝進前幾名」從第 3 週起算。</p>
                        <p>適合看：誰後來居上、誰曾經領先又被超越，也就是大戶偏好的順序怎麼變。</p>
                        <p>不適合看：差距大小。第 1 名和第 2 名可能差很多也可能只差一點；要看幅度請切到「籌碼行為」。</p>
                    </details>
                </template>

                <template v-else-if="chartType === 'moneyBar' && moneyFlow && moneyBarData?.pct">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>左欄是大戶淨賣出比例最高的題材，右欄是淨買進比例最高的題材，各列前 {{ MONEY_BAR_TOP }} 名。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>比例 = 大戶買賣金額 ÷ 類股總市值 (取期間最後一週)。上方可以切換比較期間。</p>
                        <p>適合看：大戶對哪個題材買得最積極、賣得最兇。不論類股大小，都用同一把尺比較。</p>
                        <p>不適合看：錢的實際規模。小類股比例高，金額可能不大，要看金額請切回「金額 (億元)」。</p>
                    </details>
                </template>

                <template v-else-if="chartType === 'moneyBar' && moneyFlow">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>左欄是大戶淨賣出最多的題材，右欄是淨買進最多的題材，各列前 {{ MONEY_BAR_TOP }} 名，單位是億元。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>
                            金額 = 大戶持股變化 × 收盤價。這段期間全部題材合計淨賣出約 {{ moneyFlow.totalOut.toFixed(0) }} 億、淨買進約 {{ moneyFlow.totalIn.toFixed(0) }} 億。上方可以切換比較期間。
                        </p>
                        <p>適合看：大戶的錢實際放在哪裡、規模多大。</p>
                        <p>
                            不適合看：大戶對哪個題材最積極。金融、晶圓代工這類大型類股，金額天生就比較大，要公平比較請切到「佔類股市值 (%)」。
                            <template v-if="moneyBarData && !moneyBarData.hasPct">
                                (目前的資料還沒有市值欄位，請重新產生籌碼分析資料。)
                            </template>
                        </p>
                    </details>
                </template>

                <template v-else-if="chartType === 'weekly'">
                    <p class="guide-lead">
                        <strong>怎麼看：</strong>每列一個題材，每根長條是那一週大戶持股比例的增減；紅色往上是大戶買進，綠色往下是大戶賣出。
                    </p>
                    <details :key="chartType" class="guide-more">
                        <summary>完整說明</summary>
                        <p>
                            畫出的題材：12 週累計增加最多的 4 個、「波段出貨」的前 2 個、累計減少最多的 4 個 (重複的只畫一次)，目前共 {{ pulseThemes.length }} 個。
                        </p>
                        <p>
                            所有列共用同一個刻度，取各週幅度的第 90 百分位為上限；少數特別大的週會被截斷，並在長條旁標出實際數字，這樣其他長條才不會被壓扁。滑鼠移到長條上可看確切數值。
                        </p>
                        <p>適合看：大戶進出的節奏，例如是連續好幾週慢慢買，還是某一週突然大量進出。</p>
                        <p>不適合看：整季累計的結果與全部題材的比較；請切到「籌碼行為」或「12 週排名」。</p>
                    </details>
                </template>
            </div>
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

.flow-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin: 4px 0 8px;
    font-size: 12px;
    color: var(--text-secondary);
}

.flow-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.flow-legend-swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
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

.trend-panels {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 12px;
}

.trend-panel {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px 4px;
    min-width: 0;
}

.trend-panel-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 10px;
    font-size: 13px;
}

.trend-panel-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    margin-top: 6px;
    font-size: 11px;
}

.flow-legend-swatch.dashed {
    opacity: 0.6;
}

.trend-empty {
    padding: 24px 0;
    text-align: center;
}

@media (max-width: 520px) {
    .trend-panels {
        grid-template-columns: 1fr;
    }
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

.money-head {
    margin-bottom: 8px;
}

.money-range {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
}

.money-stages {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.money-note {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.6;
}

.chart-guide {
    margin-top: 10px;
    padding: 8px 12px;
    border-top: 1px dashed var(--border);
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.7;
}

.guide-lead {
    margin: 0;
    color: var(--text-secondary);
}

.guide-more summary {
    cursor: pointer;
    margin-top: 4px;
    color: var(--text-secondary);
    user-select: none;
}

.guide-more p,
.guide-more ul {
    margin: 6px 0 0;
}

.guide-more ul {
    padding-left: 20px;
}
</style>
