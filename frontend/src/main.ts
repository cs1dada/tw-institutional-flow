import { createApp } from "vue"

import App from "@/App.vue"
import { router } from "@/router"
import { setupAnalytics } from "@/utils/analytics"
import { markDevEnvironment } from "@/utils/devMark"

// 註冊 ECharts 用到的圖表與元件，沒有這一行圖表會是空白
import "@/utils/echarts"

import "@/styles/style.css"

// 流量統計，只在正式站啟用
setupAnalytics()

// 本機開發版換成藍色圖示與「(本機)」標題，跟正式網站分得出來
markDevEnvironment()

createApp(App).use(router).mount("#app")
