/**
 * 圖表用的色彩 token。
 *
 * 顏色的唯一來源是 style.css 的 CSS 變數，這裡只負責讀出來給 ECharts 用
 * (ECharts 的設定物件吃不到 CSS 變數)。沿用舊版 app.js 的作法。
 */
import { ref, watchEffect } from "vue"

let cached: Record<string, string> | null = null

const TOKENS = {
    buy: "--buy",
    sell: "--sell",
    sellCvd: "--sell-cvd",
    buyCvd: "--buy-cvd",
    neutral: "--neutral",
    text: "--text-primary",
    secondary: "--text-secondary",
    muted: "--text-muted",
    border: "--border",
    surface: "--surface-1",
    surface0: "--surface-0",
    foreign: "--series-foreign",
    trust: "--series-trust",
    dealer: "--series-dealer",
    zoneStrongSell: "--zone-strong-sell",
    zoneSell: "--zone-sell",
    zoneNeutral: "--zone-neutral",
    zoneBuy: "--zone-buy",
    zoneStrongBuy: "--zone-strong-buy",
} as const

export type ColorName = keyof typeof TOKENS

/** 讀取全部色彩 token，首次呼叫時才從 DOM 取值並快取 */
export function colors(): Record<ColorName, string> {
    if (!cached) {
        const root = document.querySelector(".viz-root") ?? document.documentElement
        const style = getComputedStyle(root)
        const values: Record<string, string> = {}
        for (const [name, token] of Object.entries(TOKENS)) {
            values[name] = style.getPropertyValue(token).trim()
        }
        cached = values
    }
    return cached as Record<ColorName, string>
}

/**
 * 色盲友善模式。紅綠對比對部分使用者不易分辨，改用紅藍。
 * 這是跨頁面的全域設定，因此放在模組層級。
 */
export const cvdMode = ref(false)

/** 台股慣例：紅漲綠跌；色盲模式下賣方改為藍色 */
export function buyColor(): string {
    return cvdMode.value ? colors().buyCvd : colors().buy
}

export function sellColor(): string {
    return cvdMode.value ? colors().sellCvd : colors().sell
}

/** 「其他」合併項的深灰色，與色階中平盤的淺灰區隔；區塊上的文字是白色，因此不用淺色的 --neutral */
export const FLAT_COLOR = "#565a63"

type Rgb = [number, number, number]

/**
 * 漲跌幅色階 (%)，參考 indusmapk 個股期熱力圖：跌越重越深綠、漲越多越深紅，平盤為灰。
 * 介於兩階之間時線性內插，超過 ±10% 以端點色呈現。
 */
const CHANGE_SCALE: [pct: number, rgb: Rgb][] = [
    [-10, [11, 74, 38]],
    [-8, [26, 110, 58]],
    [-6, [46, 139, 77]],
    [-4, [60, 160, 90]],
    [-2, [90, 190, 120]],
    [-1, [150, 200, 165]],
    [0, [180, 180, 180]],
    [1, [230, 140, 140]],
    [2, [240, 100, 100]],
    [4, [224, 60, 72]],
    [6, [209, 52, 79]],
    [8, [185, 28, 52]],
    [10, [139, 11, 34]],
]

/** 色盲友善模式的跌方色階：紅綠難分辨，跌方改為深淺藍 */
const CHANGE_SCALE_CVD_DOWN: Rgb[] = [
    [8, 48, 107],
    [8, 81, 156],
    [33, 113, 181],
    [66, 146, 198],
    [120, 175, 214],
    [160, 195, 225],
]

function changeScale(): [number, Rgb][] {
    if (!cvdMode.value) {
        return CHANGE_SCALE
    }
    return CHANGE_SCALE.map(([pct, rgb], i) => [pct, i < CHANGE_SCALE_CVD_DOWN.length ? CHANGE_SCALE_CVD_DOWN[i] : rgb])
}

function rgbText([r, g, b]: Rgb): string {
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`
}

/** 圖例用：色階上每一階的標籤與顏色 */
export function changeLegend(): { label: string; color: string }[] {
    return changeScale().map(([pct, rgb]) => ({
        label: `${pct > 0 ? "+" : ""}${pct}%`,
        color: rgbText(rgb),
    }))
}

/** 依漲跌幅上色，無漲跌資料時回傳 null */
export function changeColor(pct: number | null | undefined): string | null {
    if (pct === null || pct === undefined || Number.isNaN(pct)) {
        return null
    }
    const scale = changeScale()
    if (pct <= scale[0][0]) {
        return rgbText(scale[0][1])
    }
    for (let i = 1; i < scale.length; i++) {
        const [hiPct, hi] = scale[i]
        if (pct <= hiPct) {
            const [loPct, lo] = scale[i - 1]
            const t = (pct - loPct) / (hiPct - loPct)
            return rgbText(lo.map((v, k) => v + (hi[k] - v) * t) as Rgb)
        }
    }
    return rgbText(scale[scale.length - 1][1])
}

export function polarityColor(value: number): string {
    return value >= 0 ? buyColor() : sellColor()
}

/** 同步覆寫 CSS 變數，讓圖例色塊與表格數字的顏色跟著切換 */
watchEffect(() => {
    const root = document.querySelector<HTMLElement>(".viz-root")
    if (!root) {
        return
    }
    root.style.setProperty("--buy", buyColor())
    root.style.setProperty("--sell", sellColor())
})

/** ECharts 的 tooltip 共用樣式 */
export function baseTooltip() {
    const c = colors()
    return {
        backgroundColor: c.surface,
        borderColor: c.border,
        borderWidth: 1,
        padding: [8, 12] as [number, number],
        textStyle: { color: c.text, fontSize: 13 },
        extraCssText: "box-shadow: 0 2px 8px rgba(0,0,0,0.12); border-radius: 6px;",
    }
}

/** #rrggbb 依比例混入底色，產生同一色系的深淺 */
export function mix(color: string, base: string, ratio: number): string {
    const parse = (hex: string) => {
        const value = hex.replace("#", "")
        const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value
        return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
    }
    const a = parse(color)
    const b = parse(base)
    const rgb = a.map((v, i) => Math.round(v * ratio + b[i] * (1 - ratio)))
    return `rgb(${rgb.join(",")})`
}
