/**
 * ECharts 按需引入。
 *
 * vue-echarts 7 不會自動註冊圖表與元件，必須在這裡 use 過才畫得出來。
 * 舊版載入的是 1007 KB 的完整版，這裡只引入實際用到的圖表，
 * 打包後的體積小很多，對 PWA 的首次載入有感。
 */
import {
    BarChart,
    CandlestickChart,
    LineChart,
    ScatterChart,
    TreemapChart,
} from "echarts/charts"
import {
    AxisPointerComponent,
    DataZoomComponent,
    GridComponent,
    LegendComponent,
    MarkAreaComponent,
    MarkLineComponent,
    TooltipComponent,
} from "echarts/components"
import { use } from "echarts/core"
import { CanvasRenderer } from "echarts/renderers"

use([
    CanvasRenderer,
    // 圖表類型：K 線、均線、長條、類股資金分布、經理人買點
    CandlestickChart,
    LineChart,
    BarChart,
    TreemapChart,
    ScatterChart,
    // 座標軸、提示框、圖例與縮放
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
    AxisPointerComponent,
    // 共識價帶與參考線
    MarkAreaComponent,
    MarkLineComponent,
])
