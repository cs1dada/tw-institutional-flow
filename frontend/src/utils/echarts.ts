/**
 * ECharts 按需引入。
 *
 * vue-echarts 7 不會自動註冊圖表與元件，必須在這裡 use 過才畫得出來。
 * 舊版載入的是 1007 KB 的完整版，這裡只引入實際用到的四種圖表，
 * 打包後的體積小很多，對 PWA 的首次載入有感。
 */
import {
    BarChart,
    CandlestickChart,
    LineChart,
    TreemapChart,
} from "echarts/charts"
import {
    AxisPointerComponent,
    DataZoomComponent,
    GridComponent,
    LegendComponent,
    TooltipComponent,
} from "echarts/components"
import { use } from "echarts/core"
import { CanvasRenderer } from "echarts/renderers"

use([
    CanvasRenderer,
    // 圖表類型：K 線、均線、長條、類股資金分布
    CandlestickChart,
    LineChart,
    BarChart,
    TreemapChart,
    // 座標軸、提示框、圖例與縮放
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
    AxisPointerComponent,
])
