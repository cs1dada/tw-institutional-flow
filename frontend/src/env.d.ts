/// <reference types="vite/client" />

declare module "*.vue" {
    import type { DefineComponent } from "vue"
    const component: DefineComponent<{}, {}, any>
    export default component
}

declare global {
    interface Window {
        // 由後端或匯出腳本注入：api 走 FastAPI，static 直接讀 JSON 檔
        APP_MODE?: "api" | "static"
        APP_INTRADAY?: "on" | "off"
    }
}

export {}
