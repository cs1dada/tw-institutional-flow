import { fileURLToPath, URL } from "node:url"

import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"

// 用相對路徑，放在哪一層子目錄都能運作。
// GitHub Pages 的網址含 repo 名稱 (cs1dada.github.io/tw-institutional-flow/)，
// 若用絕對路徑 /assets/... 會被解讀成 cs1dada.github.io/assets/... 而失效
const BASE = "./"

export default defineConfig(({ command }) => ({
    base: command === "build" ? BASE : "/",
    plugins: [
        vue(),
        VitePWA({
            registerType: "autoUpdate",
            includeAssets: ["apple-touch-icon.png"],
            manifest: {
                name: "台股法人動向",
                short_name: "法人動向",
                description: "台股三大法人類股資金流向、主動式 ETF 持股與大盤指數 K 線",
                lang: "zh-Hant-TW",
                theme_color: "#fcfcfb",
                background_color: "#f5f5f3",
                display: "standalone",
                orientation: "any",
                // 相對路徑，放在子目錄也能安裝
                start_url: "./",
                scope: "./",
                icons: [
                    { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
                    { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
                    {
                        src: "pwa-maskable-512.png",
                        sizes: "512x512",
                        type: "image/png",
                        // Android 會把圖示裁成圓形，這一版四周留白
                        purpose: "maskable",
                    },
                ],
            },
            workbox: {
                globPatterns: ["**/*.{js,css,html,png,svg}"],
                // 資料檔另外用 runtime 快取處理，不預先下載 (day/*.json 有數十個)
                globIgnores: ["**/data/**"],
                navigateFallback: "index.html",
                runtimeCaching: [
                    {
                        // 某一天的資料一旦產生就不會再變，看過一次就永久留在裝置上
                        urlPattern: /\/data\/day\/\d{8}\.json/,
                        handler: "CacheFirst",
                        options: {
                            cacheName: "day-data",
                            expiration: { maxEntries: 90, maxAgeSeconds: 60 * 60 * 24 * 180 },
                            cacheableResponse: { statuses: [0, 200] },
                        },
                    },
                    {
                        // meta 決定其他檔案的版本號，必須優先取最新的
                        urlPattern: /\/data\/meta\.json/,
                        handler: "NetworkFirst",
                        options: {
                            cacheName: "meta-data",
                            networkTimeoutSeconds: 5,
                            expiration: { maxEntries: 4 },
                            cacheableResponse: { statuses: [0, 200] },
                        },
                    },
                    {
                        // 其餘資料檔每天會更新，先用快取再背景更新
                        urlPattern: /\/data\/(history|etf|index)\.json/,
                        handler: "StaleWhileRevalidate",
                        options: {
                            cacheName: "aggregate-data",
                            expiration: { maxEntries: 12 },
                            cacheableResponse: { statuses: [0, 200] },
                        },
                    },
                ],
            },
            devOptions: {
                // 開發時預設關閉，避免 service worker 快取干擾熱更新
                enabled: false,
            },
        }),
    ],
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
        // 輸出到專案根目錄之外的 dist/，再由 scripts/deploy_web.py 複製到 docs/
        outDir: "../dist",
        emptyOutDir: true,
    },
}))
