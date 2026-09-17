import { fileURLToPath, URL } from "node:url"

import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

// GitHub Pages 的網址含 repo 名稱，資源路徑必須帶上這一層，
// 否則 /assets/... 會被解讀成 cs1dada.github.io/assets/... 而失效
const BASE = "/tw-institutional-flow/"

export default defineConfig(({ command }) => ({
    base: command === "build" ? BASE : "/",
    plugins: [vue()],
    resolve: {
        alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
        },
    },
    server: {
        port: 5173,
        proxy: {
            // 開發時前端跑在 5173，API 由本機的 FastAPI 提供
            "/api": {
                target: "http://127.0.0.1:8000",
                changeOrigin: true,
            },
        },
    },
    build: {
        // 輸出到專案根目錄之外的 dist/，docs/ 仍由舊版靜態站使用，
        // 兩者並存到切換部署為止
        outDir: "../dist",
        emptyOutDir: true,
    },
}))
