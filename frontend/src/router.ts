import { createRouter, createWebHashHistory } from "vue-router"

import IndexChartView from "@/views/IndexChartView.vue"
import PendingView from "@/views/PendingView.vue"

/**
 * 用 hash 模式而非 history 模式：GitHub Pages 只會送檔案，
 * 直接開啟 /etf 這種路徑會得到 404，hash 路由則不需要伺服器配合。
 */
export const router = createRouter({
    history: createWebHashHistory(),
    routes: [
        {
            path: "/",
            component: PendingView,
            props: { title: "類股資金流向", note: "三大法人買賣超，依產業別聚合" },
        },
        {
            path: "/etf",
            component: PendingView,
            props: { title: "主動式 ETF", note: "持股與資金動向" },
        },
        {
            path: "/intraday",
            component: PendingView,
            props: { title: "盤中觀察", note: "類股即時強弱" },
        },
        { path: "/index", component: IndexChartView },
        { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
})
