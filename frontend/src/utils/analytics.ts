/**
 * Google Analytics 4 流量統計。
 *
 * 只在正式站 (GitHub Pages) 啟用，本機開發與 FastAPI 提供的建置版都不送資料，
 * 避免自己測試的流量混進統計。
 *
 * 網址不帶 # (例如 /tw-institutional-flow/etf/daily)，GA 直接讀得到實際頁面：
 * 進站的第一頁由 config 送出 page_view，之後切換分頁由 GA 加強型評估的
 * 「根據瀏覽記錄事件進行網頁變更」自動記錄，不需要另外手動送。
 */
const MEASUREMENT_ID = "G-4B6209S0EB"

/** 只在這個網域啟用 */
const PRODUCTION_HOST = "cs1dada.github.io"

declare global {
    interface Window {
        dataLayer: unknown[]
        gtag: (...args: unknown[]) => void
    }
}

export function setupAnalytics(): void {
    if (window.location.hostname !== PRODUCTION_HOST) {
        return
    }
    const script = document.createElement("script")
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`
    document.head.appendChild(script)

    window.dataLayer = window.dataLayer || []
    // gtag 必須推入 arguments 物件，不能改成陣列，否則 GA 不會處理
    window.gtag = function gtag() {
        window.dataLayer.push(arguments)
    }
    window.gtag("js", new Date())
    window.gtag("config", MEASUREMENT_ID)
}
