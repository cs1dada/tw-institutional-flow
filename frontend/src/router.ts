import { createRouter, createWebHistory } from "vue-router"

import BacktestView from "@/views/BacktestView.vue"
import DailyView from "@/views/DailyView.vue"
import IndexChartView from "@/views/IndexChartView.vue"
import IndustryFlowView from "@/views/IndustryFlowView.vue"
import LiquidityView from "@/views/LiquidityView.vue"
import IntradayView from "@/views/IntradayView.vue"
import QuoteView from "@/views/QuoteView.vue"
import ReportView from "@/views/ReportView.vue"
import SinoQuoteView from "@/views/SinoQuoteView.vue"
import ThemesView from "@/views/ThemesView.vue"
import ValuationView from "@/views/ValuationView.vue"
import EtfTrendView from "@/views/EtfTrendView.vue"
import EtfHubView from "@/views/EtfHubView.vue"
import EtfView from "@/views/EtfView.vue"
import HoldersView from "@/views/HoldersView.vue"

/**
 * 用 history 模式，網址不帶 # (例如 /tw-institutional-flow/etf/daily)。
 *
 * GitHub Pages 只會送檔案，直接開啟 /etf 這種路徑本來會得到 404；
 * 建置時把 index.html 複製一份為 404.html (見 vite.config.ts)，
 * 找不到的路徑就會拿到網站本身，再由這裡依網址顯示對應頁面。
 *
 * 根目錄取自 index.html 的 <base>：GitHub Pages 為 /tw-institutional-flow/，其他環境為 /
 */
export const router = createRouter({
    history: createWebHistory(new URL(document.baseURI).pathname),
    routes: [
        { path: "/", component: IndustryFlowView },
        {
            // 主動式 ETF 四個子頁共用一個外框，頂端用分頁列切換
            path: "/etf",
            component: EtfHubView,
            children: [
                { path: "", redirect: "/etf/overview" },
                { path: "overview", component: EtfView },
                { path: "daily", component: DailyView },
                { path: "reports", component: ReportView },
                { path: "trend", component: EtfTrendView },
            ],
        },
        // 舊網址導向新位置，已存的書籤與 PWA 捷徑才不會失效
        { path: "/daily", redirect: "/etf/daily" },
        { path: "/reports", redirect: "/etf/reports" },
        { path: "/trend", redirect: "/etf/trend" },
        { path: "/intraday", component: IntradayView },
        { path: "/quote", component: QuoteView },
        { path: "/sino", component: SinoQuoteView },
        { path: "/index", component: IndexChartView },
        { path: "/liquidity", component: LiquidityView },
        { path: "/themes", component: ThemesView },
        { path: "/valuation", component: ValuationView },
        { path: "/holders", component: HoldersView },
        { path: "/backtest", component: BacktestView },
        { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
})
