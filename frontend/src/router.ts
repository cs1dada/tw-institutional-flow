import { createRouter, createWebHashHistory } from "vue-router"

import DailyView from "@/views/DailyView.vue"
import IndexChartView from "@/views/IndexChartView.vue"
import IndustryFlowView from "@/views/IndustryFlowView.vue"
import IntradayView from "@/views/IntradayView.vue"
import QuoteView from "@/views/QuoteView.vue"
import SinoQuoteView from "@/views/SinoQuoteView.vue"
import EtfView from "@/views/EtfView.vue"

/**
 * 用 hash 模式而非 history 模式：GitHub Pages 只會送檔案，
 * 直接開啟 /etf 這種路徑會得到 404，hash 路由則不需要伺服器配合。
 */
export const router = createRouter({
    history: createWebHashHistory(),
    routes: [
        { path: "/", component: IndustryFlowView },
        { path: "/etf", component: EtfView },
        { path: "/daily", component: DailyView },
        { path: "/intraday", component: IntradayView },
        { path: "/quote", component: QuoteView },
        { path: "/sino", component: SinoQuoteView },
        { path: "/index", component: IndexChartView },
        { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
})
