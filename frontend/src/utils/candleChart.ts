/**
 * K 線圖的 ECharts 設定。
 *
 * 大盤指數與個股用的是同一種圖：K 棒 + 均線 + 成交金額副圖 + 縮放軸，
 * 只有座標軸名稱與小數位數不同，因此設定抽在這裡由兩頁共用，
 * 改配色或版面時只要改一個地方。
 *
 * 純函式，不碰 DOM 也不碰 Vue。
 */
import type { Bar, ZoomRange } from "@/types"
import { movingAverage } from "./indexBars"
import { signed } from "./format"
import { baseTooltip, buyColor, colors, sellColor } from "./theme"

export interface CandleOptions {
    /** 均線參數，例如日線的 [5, 20, 60] */
    maSizes: number[]
    /** 顯示區間對應的 K 棒索引。K 棒本身仍是全部資料，均線才不會斷頭 */
    zoom: ZoomRange
    /** 價格軸的名稱，例如「指數」或「股價」 */
    priceName: string
    /** 價格的小數位數 */
    digits?: number
    /** 成交量副圖的軸名。個股是成交金額，期貨則是口數 */
    turnoverLabel?: string
    /** 成交量在提示框裡的單位 */
    turnoverUnit?: string
}

export function buildCandleOption(bars: Bar[], options: CandleOptions) {
    if (!bars.length) {
        return {}
    }
    const {
        maSizes, zoom, priceName, digits = 2,
        turnoverLabel = "成交金額（億）", turnoverUnit = "億",
    } = options
    const c = colors()
    const labels = bars.map((bar) => bar.label)
    const maColors = [c.foreign, c.trust, c.dealer]

    const maSeries = maSizes.map((size, index) => ({
        name: `MA${size}`,
        type: "line",
        data: movingAverage(bars, size),
        smooth: true,
        symbol: "none",
        lineStyle: { width: 1.5, color: maColors[index] },
        itemStyle: { color: maColors[index] },
        z: 3,
    }))

    return {
        animation: false,
        legend: {
            data: maSizes.map((size) => `MA${size}`),
            top: 0,
            icon: "roundRect",
            itemWidth: 10,
            itemHeight: 10,
            itemGap: 18,
            textStyle: { color: c.secondary, fontSize: 12 },
        },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
            ...baseTooltip(),
            trigger: "axis",
            axisPointer: { type: "cross", label: { backgroundColor: c.secondary } },
            formatter: (params: any[]) => {
                const bar = bars[params[0].dataIndex]
                if (!bar) {
                    return ""
                }
                const color = bar.diff === null || bar.diff >= 0 ? buyColor() : sellColor()
                const lines = [
                    `<strong>${bar.label}${bar.days > 1 ? `　${bar.days} 個交易日` : ""}</strong>`,
                    `開盤　${bar.open.toFixed(digits)}`,
                    `最高　${bar.high.toFixed(digits)}`,
                    `最低　${bar.low.toFixed(digits)}`,
                    `收盤　${bar.close.toFixed(digits)}`,
                    `漲跌　<span style="color:${color}">${signed(bar.diff)}（${signed(bar.pct)}%）</span>`,
                    turnoverUnit === "億"
                        ? `成交金額　${bar.turnover.toFixed(bar.turnover >= 100 ? 0 : 1)} 億`
                        : `成交量　${bar.turnover.toLocaleString()} ${turnoverUnit}`,
                ]
                for (const item of params) {
                    if (item.seriesType === "line" && item.data !== "-") {
                        lines.push(`${item.marker}${item.seriesName}　${item.data}`)
                    }
                }
                return lines.join("<br>")
            },
        },
        grid: [
            { left: 68, right: 24, top: 36, height: 350 },
            { left: 68, right: 24, top: 410, height: 84 },
        ],
        xAxis: [
            {
                type: "category",
                data: labels,
                axisLine: { lineStyle: { color: c.border } },
                axisTick: { show: false },
                // 日期只標在下方的成交量副圖，兩張圖之間不再夾一排文字
                axisLabel: { show: false },
                splitLine: { show: false },
                min: "dataMin",
                max: "dataMax",
            },
            {
                type: "category",
                gridIndex: 1,
                data: labels,
                axisLine: { lineStyle: { color: c.border } },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                splitLine: { show: false },
                min: "dataMin",
                max: "dataMax",
            },
        ],
        yAxis: [
            {
                scale: true,
                name: priceName,
                nameTextStyle: { color: c.muted, fontSize: 11 },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
            {
                gridIndex: 1,
                name: turnoverLabel,
                nameGap: 10,
                nameTextStyle: { color: c.muted, fontSize: 11, align: "left" },
                splitNumber: 2,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: c.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
            },
        ],
        dataZoom: [
            {
                type: "inside",
                xAxisIndex: [0, 1],
                startValue: zoom.start,
                endValue: zoom.end,
            },
            {
                type: "slider",
                xAxisIndex: [0, 1],
                startValue: zoom.start,
                endValue: zoom.end,
                bottom: 12,
                height: 20,
                borderColor: c.border,
                fillerColor: "rgba(42, 120, 214, 0.12)",
                handleStyle: { color: c.surface, borderColor: c.muted },
                textStyle: { color: c.muted, fontSize: 11 },
            },
        ],
        series: [
            {
                name: "K 線",
                type: "candlestick",
                data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
                itemStyle: {
                    // ECharts 的 color 為收高於開的陽線，台股慣例為紅漲綠跌
                    color: buyColor(),
                    color0: sellColor(),
                    borderColor: buyColor(),
                    borderColor0: sellColor(),
                },
                z: 2,
            },
            ...maSeries,
            {
                name: turnoverLabel,
                type: "bar",
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: bars.map((bar) => ({
                    value: +bar.turnover.toFixed(bar.turnover >= 100 ? 0 : 2),
                    itemStyle: {
                        color: bar.close >= bar.open ? buyColor() : sellColor(),
                        opacity: 0.55,
                    },
                })),
            },
        ],
    }
}
