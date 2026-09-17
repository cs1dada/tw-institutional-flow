/** 格式化工具。與舊版 app.js 的行為完全一致，避免遷移後數字長相改變。 */

/** 一億元 */
export const YI = 1e8

/** 金額轉億元字串，一律帶正負號作為顏色以外的次要編碼 */
export function toYi(amount: number, digits = 1): string {
    const value = amount / YI
    const fixed = value.toFixed(digits)
    return (value > 0 ? "+" : "") + fixed
}

/** 20260916 轉為 2026-09-16 */
export function formatDate(dateStr: string | null | undefined): string {
    if (!dateStr || dateStr.length !== 8) {
        return dateStr ?? ""
    }
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

/** 2026-09-16 轉回 20260916 */
export function toCompactDate(value: string): string {
    return value.replace(/-/g, "")
}

/** 帶正負號的數值，null 顯示為 -- */
export function signed(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined) {
        return "--"
    }
    return (value > 0 ? "+" : "") + value.toFixed(digits)
}
