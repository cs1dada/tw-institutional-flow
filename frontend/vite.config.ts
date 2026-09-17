import { fileURLToPath, URL } from "node:url"

import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

// 用相對路徑，放在哪一層子目錄都能運作。
// GitHub Pages 的網址含 repo 名稱 (cs1dada.github.io/tw-institutional-flow/)，
// 若用絕對路徑 /assets/... 會被解讀成 cs1dada.github.io/assets/... 而失效
const BASE = "./"

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
