<script setup lang="ts">
/**
 * 通用 treemap：面積表示金額規模，顏色只表示買賣方向。
 * 類股層級與下鑽後的個股層級共用同一份繪製邏輯。
 *
 * childrenOf 有回傳子項時，類股區塊內會再依個股金額切分。
 * ECharts 的 upperLabel 在兩層資料下不會生效，因此類股名稱改用
 * HTML 疊加層畫在區塊上緣 (drawTitles)。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"
import VChart from "vue-echarts"

import { OTHER_MAX_RATIO } from "@/utils/flow"
import { toYi } from "@/utils/format"
import { baseTooltip, colors, polarityColor } from "@/utils/theme"

/** 只要求有金額，其餘欄位由呼叫端的 nameOf / tooltip 自行解讀 */
interface Row {
    amount: number
}

interface Child {
    amount: number
    is_other: boolean
    name?: string
}

const props = defineProps<{
    rows: Row[]
    /** 區塊名稱 */
    nameOf: (row: any) => string
    /** 子項名稱 */
    childNameOf?: (kid: any) => string
    /** 回傳子項則在區塊內再切分 */
    childrenOf?: ((row: any) => Child[] | null) | null
    /** 區塊內附帶顯示的明細行 */
    linesOf?: ((row: any) => string[] | null) | null
    tooltip: (row: any) => string
    /** 金額顯示的小數位數 */
    digits?: number
    /** 圖表高度，未指定則由 CSS 決定 */
    height?: string
}>()

const emit = defineEmits<{ select: [row: any] }>()

const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const overlay = ref<HTMLElement | null>(null)

const TITLE_BAR_HEIGHT = 20
const TITLE_MIN_WIDTH = 74
const TITLE_MIN_HEIGHT = 48

/** 母項標題的內容，只有切分成兩層時才需要 */
const titleInfo = ref<Record<string, { name: string; amount: string }>>({})

const option = computed(() => {
    const c = colors()
    const digits = props.digits
    const info: Record<string, { name: string; amount: string }> = {}

    const data = props.rows
        .filter((row) => Math.abs(row.amount) > 0)
        .map((row) => {
            const name = props.nameOf(row)
            const node: Record<string, unknown> = {
                name,
                value: Math.abs(row.amount),
                amount: row.amount,
                detail: row,
                lines: props.linesOf ? props.linesOf(row) : null,
                itemStyle: {
                    color: polarityColor(row.amount),
                    borderColor: c.surface,
                    borderWidth: 2,
                    gapWidth: 2,
                },
            }

            const kids = props.childrenOf ? props.childrenOf(row) : null
            if (kids?.length) {
                // 子項面積正規化，使其加總等於母項，母項區塊仍代表類股淨額。
                // 「其他」常常大到蓋過具名個股，因此設面積上限，
                // 超過的部分把版面讓給前幾大個股 (tooltip 仍顯示真實金額)。
                const parentAbs = Math.abs(row.amount)
                let namedSum = 0
                let otherSum = 0
                for (const kid of kids) {
                    if (kid.is_other) {
                        otherSum += Math.abs(kid.amount)
                    } else {
                        namedSum += Math.abs(kid.amount)
                    }
                }
                const total = namedSum + otherSum
                let namedScale = total > 0 ? parentAbs / total : 0
                let otherScale = namedScale
                let capped = false
                if (namedSum > 0 && otherSum * namedScale > parentAbs * OTHER_MAX_RATIO) {
                    capped = true
                    otherScale = (parentAbs * OTHER_MAX_RATIO) / otherSum
                    namedScale = (parentAbs * (1 - OTHER_MAX_RATIO)) / namedSum
                }
                info[name] = { name, amount: `${toYi(row.amount, digits)} 億` }
                node.children = kids.map((kid) => {
                    const scale = kid.is_other ? otherScale : namedScale
                    return {
                        name: props.childNameOf ? props.childNameOf(kid) : String(kid.name),
                        value: Math.abs(kid.amount) * scale,
                        amount: kid.amount,
                        detail: {
                            industry: (row as any).industry,
                            areaCapped: capped && kid.is_other,
                            ...kid,
                        },
                        // 上緣要留給類股標題，個股文字往下讓出同樣高度
                        label: { padding: [TITLE_BAR_HEIGHT + 2, 0, 0, 0] },
                        itemStyle: {
                            color: polarityColor(kid.amount),
                            borderColor: "rgba(255, 255, 255, 0.55)",
                            borderWidth: 1,
                            gapWidth: 1,
                        },
                    }
                })
            }
            return node
        })

    titleInfo.value = info

    return {
        tooltip: {
            ...baseTooltip(),
            formatter: (params: any) => {
                // 滑過區塊間隙時 ECharts 會帶入沒有 detail 的節點
                const row = params.data?.detail
                return row ? props.tooltip(row) : ""
            },
        },
        series: [
            {
                type: "treemap",
                data,
                // 關閉自動排序，改由傳入的資料順序決定版面，
                // 面積大的排在左上、「其他」排在最後而落在右下角
                sort: null,
                roam: false,
                nodeClick: false,
                breadcrumb: { show: false },
                width: "100%",
                height: "100%",
                label: {
                    show: true,
                    overflow: "truncate",
                    formatter: (params: any) => {
                        let text = `{name|${params.name}}\n{value|${toYi(params.data.amount, digits)} 億}`
                        for (const line of params.data.lines ?? []) {
                            text += `\n{stock|${line}}`
                        }
                        return text
                    },
                    rich: {
                        name: { color: "#ffffff", fontSize: 13, fontWeight: 600, lineHeight: 18 },
                        value: { color: "rgba(255,255,255,0.92)", fontSize: 12, lineHeight: 16 },
                        stock: { color: "rgba(255,255,255,0.85)", fontSize: 11, lineHeight: 16 },
                    },
                },
                itemStyle: { borderRadius: 4 },
                emphasis: { itemStyle: { borderColor: c.text, borderWidth: 2 } },
            },
        ],
    }
})

let measureCtx: CanvasRenderingContext2D | null = null

/** 量測標題文字的實際像素寬度，字體需與 .tm-title 的樣式一致 */
function measureTitle(text: string): number {
    if (!measureCtx) {
        measureCtx = document.createElement("canvas").getContext("2d")
        if (measureCtx) {
            measureCtx.font = '600 12px "Noto Sans TC", "Microsoft JhengHei", sans-serif'
        }
    }
    return measureCtx?.measureText(text).width ?? 0
}

/** 依 treemap 實際版面，把母項 (類股) 名稱疊在區塊上緣 */
function drawTitles() {
    const box = overlay.value
    if (!box) {
        return
    }
    box.innerHTML = ""
    const info = titleInfo.value
    if (!Object.keys(info).length) {
        return
    }
    let root: any
    try {
        root = (chartRef.value as any)?.chart?.getModel().getSeriesByIndex(0).getData().tree.root
    } catch {
        return
    }
    for (const node of root?.children ?? []) {
        const title = info[node.name]
        const layout = node.getLayout()
        if (!title || !layout) {
            continue
        }
        // 區塊太小時放不下標題，維持原本的區塊呈現
        if (layout.width < TITLE_MIN_WIDTH || layout.height < TITLE_MIN_HEIGHT) {
            continue
        }
        const el = document.createElement("div")
        el.className = "tm-title"
        // 寬度不足以完整顯示金額時只留類股名，避免出現「-28.」這種半截數字
        const full = `${title.name}　${title.amount}`
        el.textContent = measureTitle(full) <= layout.width - 16 ? full : title.name
        el.style.left = `${layout.x + 2}px`
        el.style.top = `${layout.y + 2}px`
        el.style.width = `${layout.width - 4}px`
        el.style.height = `${TITLE_BAR_HEIGHT}px`
        box.appendChild(el)
    }
}

function onClick(params: any) {
    if (params.data?.detail) {
        emit("select", params.data.detail)
    }
}

/** 重繪後版面才確定，標題要等下一個 tick 才畫得準 */
watch(option, () => {
    // 切換層級時舊的提示框會失去依附的節點
    ;(chartRef.value as any)?.chart?.dispatchAction({ type: "hideTip" })
    nextTick(drawTitles)
})

function onResize() {
    nextTick(drawTitles)
}

onMounted(() => {
    nextTick(drawTitles)
    window.addEventListener("resize", onResize)
})

onUnmounted(() => {
    window.removeEventListener("resize", onResize)
})
</script>

<template>
    <div class="chart-stack">
        <VChart
            ref="chartRef"
            class="chart chart-tall"
            :style="height ? { height } : undefined"
            :option="option"
            autoresize
            @click="onClick"
            @finished="onResize"
        />
        <div ref="overlay" class="chart-overlay"></div>
    </div>
</template>
