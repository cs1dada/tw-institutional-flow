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
    foreign: "--series-foreign",
    trust: "--series-trust",
    dealer: "--series-dealer",
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
