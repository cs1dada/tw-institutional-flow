import { createRouter, createWebHashHistory } from "vue-router"

import DailyView from "@/views/DailyView.vue"
import IndexChartView from "@/views/IndexChartView.vue"
import IndustryFlowView from "@/views/IndustryFlowView.vue"
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
 * 用 hash 模式而非 history 模式：GitHub Pages 只會送檔案，
 * 直接開啟 /etf 這種路徑會得到 404，hash 路由則不需要伺服器配合。
 */
export const router = createRouter({
    history: createWebHashHistory(),
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
        { path: "/themes", component: ThemesView },
        { path: "/valuation", component: ValuationView },
        { path: "/holders", component: HoldersView },
        { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
})
