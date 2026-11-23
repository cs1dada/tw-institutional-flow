/**
 * 流動性觀察：美元指數 (DXY) × 美債殖利率曲線 (10Y-2Y) 四象限的定義與判讀。
 *
 * 判讀方式：比較最新一天與 N 個交易日前的數值。
 * - 美元：DXY 漲跌決定走強或走弱
 * - 曲線：10Y-2Y 利差擴大為趨陡、縮小為趨平
 * - 哪一端在動：2Y 與 10Y 平均變動為正是「熊市」(殖利率整體上升)，為負是「牛市」
 *
 * 四象限的典型情境各自對應一種曲線型態 (例如美元走強 + 趨平通常是熊市趨平)，
 * 實際資料不一定吻合，不吻合時頁面會另外提醒。
 */
import type { LiquidityData } from "@/types"

export type Dxy = "up" | "down"
export type Curve = "steep" | "flat"
export type RegimeId = "tight" | "split" | "release" | "haven"
/** 曲線型態：熊市趨平、熊市趨陡、牛市趨陡、牛市趨平 */
export type CurveShape = "bear-flat" | "bear-steep" | "bull-steep" | "bull-flat"

export interface Regime {
    id: RegimeId
    dxy: Dxy
    curve: Curve
    /** 此象限典型的曲線型態 */
    shape: CurveShape
    /** 殖利率曲線的變動細節：哪一端動得比較快 */
    curveDetail: string
    label: string
    /** 白話結論：資金鬆緊與對台股的大方向 */
    headline: string
    /** 白話說明：發生了什麼事 */
    story: string
    /** 對台股的典型影響 */
    taiwan: string
    /** 已通過色盲辨識度驗證的四色 (dataviz validate_palette，all-pairs) */
    color: string
    background: string
    driver: string
    liquidity: string
    /** 相對抗跌或受惠的資產 */
    winners: string[]
    /** 相對承壓的資產 */
    losers: string[]
}

export const SHAPE_LABEL: Record<CurveShape, string> = {
    "bear-flat": "熊市趨平 (Bear Flattening)",
    "bear-steep": "熊市趨陡 (Bear Steepening)",
    "bull-steep": "牛市趨陡 (Bull Steepening)",
    "bull-flat": "牛市趨平 (Bull Flattening)",
}

export const REGIMES: Regime[] = [
    {
        id: "tight",
        dxy: "up",
        curve: "flat",
        shape: "bear-flat",
        curveDetail: "2Y 上升比 10Y 快",
        label: "流動性最緊縮",
        headline: "資金最緊，對台股不利",
        story: "美元在漲，錢往美國回流；市場認為聯準會短期內不降息，甚至可能升息，借錢成本變高。",
        taiwan: "外資容易賣超台股，高本益比的科技股、成長股壓力最大。",
        color: "#b42335",
        background: "#fbf1f2",
        driver: "緊縮預期升溫 (如通膨反彈、聯準會轉鷹)，資金成本直接被抬高。",
        liquidity: "殺估值：對高估值科技股、加密貨幣、黃金與新興市場同步承壓；短債與美元現金最抗跌。",
        winners: ["美元現金", "短天期美債"],
        losers: ["高估值科技股", "加密貨幣", "黃金", "新興市場"],
    },
    {
        id: "split",
        dxy: "up",
        curve: "steep",
        shape: "bear-steep",
        curveDetail: "10Y 上升比 2Y 快",
        label: "結構性分化",
        headline: "美國獨強，對台股偏不利",
        story: "美國經濟很熱或政府大量發債，長天期利率往上走，全球資金被吸往美國。",
        taiwan: "外資資金偏向美國，出口與原物料相關類股承壓，金融股相對撐得住。",
        color: "#c27800",
        background: "#fbf5ea",
        driver: "美國經濟過熱或財政發債壓力大，長端期限溢價上升，同時吸引全球資本流入美國。",
        liquidity: "強美元壓抑大宗商品與跨國企業海外營收，但美國本土價值股、金融股相對抗跌；長久期資產 (如 TLT) 受創。",
        winners: ["美國本土價值股", "金融股"],
        losers: ["大宗商品", "跨國企業", "長天期美債 (TLT)"],
    },
    {
        id: "release",
        dxy: "down",
        curve: "steep",
        shape: "bull-steep",
        curveDetail: "2Y 下跌比 10Y 快",
        label: "流動性釋放初期",
        headline: "資金轉寬鬆，對台股有利",
        story: "聯準會開始降息、美元走弱，錢變便宜，也開始往美國以外的市場流動。",
        taiwan: "外資容易回補台股，成長股、電子股通常最先反彈。",
        color: "#2a78d6",
        background: "#eef4fc",
        driver: "聯準會轉向寬鬆或啟動降息週期，短端資金成本快速下降。",
        liquidity: "風險偏好回升：對利率最敏感的資產率先反彈 (加密貨幣、黃金、高 Beta 成長股、新興市場)；美元與短債收益率下滑。",
        winners: ["加密貨幣", "黃金", "漲跌幅大的成長股", "新興市場"],
        losers: ["美元", "短債收益率"],
    },
    {
        id: "haven",
        dxy: "down",
        curve: "flat",
        shape: "bull-flat",
        curveDetail: "10Y 下跌比 2Y 快",
        label: "避險主導",
        headline: "市場在避險，對台股偏不利",
        story: "市場擔心經濟衰退，資金躲進長天期美債；美元雖然走弱，但不是因為大家想買股票。",
        taiwan: "外資對股市保守，景氣循環股與負債高的公司要小心，防禦型類股相對抗跌。",
        color: "#1a9480",
        background: "#edf7f5",
        driver: "經濟衰退預期主導，長端定價未來通膨與成長放緩，但聯準會尚未大幅降息。",
        liquidity: "看重防禦與確定性：長天期美債 (TLT) 表現最佳；高槓桿風險資產因獲利下修而波動加劇，需防範信用利差擴大。",
        winners: ["長天期美債 (TLT)", "防禦型資產"],
        losers: ["高槓桿風險資產", "信用債 (利差擴大)"],
    },
]

/** 用白話描述 2Y 與 10Y 怎麼動，例如「2Y、10Y 都下降，10Y 降得比較多」 */
export function describeMove(us2yBp: number, us10yBp: number): string {
    if (us2yBp >= 0 && us10yBp >= 0) {
        return `2Y、10Y 都上升，${us2yBp >= us10yBp ? "2Y" : "10Y"} 升得比較多`
    }
    if (us2yBp <= 0 && us10yBp <= 0) {
        return `2Y、10Y 都下降，${us2yBp <= us10yBp ? "2Y" : "10Y"} 降得比較多`
    }
    return `2Y ${us2yBp > 0 ? "上升" : "下降"}、10Y ${us10yBp > 0 ? "上升" : "下降"}`
}

export function regimeOf(dxy: Dxy, curve: Curve): Regime {
    return REGIMES.find((r) => r.dxy === dxy && r.curve === curve)!
}

/** 補值後的一天：美元與美債休市日不同，缺值沿用前一個有值的日子 */
export interface LiquidityPoint {
    date: string
    dxy: number
    us2y: number
    us10y: number
    /** 10Y-2Y 利差 (百分點) */
    spread: number
    /** 美元兌台幣，資料起點較晚時開頭幾天為 null */
    usdtwd: number | null
    /** 對照資產的收盤價，尚未有資料時為 null */
    assets: Record<AssetId, number | null>
}

export type AssetId = "spx" | "taiex" | "btc" | "gold"

export interface Asset {
    id: AssetId
    label: string
    /** 線尾標籤用的短名稱 */
    short: string
    /** 走勢圖用的線色，四色已通過色盲辨識度驗證 (dataviz validate_palette，all-pairs) */
    color: string
    /** 在 LiquidityData.items 裡的欄位位置 */
    column: number
}

export const ASSETS: Asset[] = [
    { id: "spx", label: "美股 (S&P 500)", short: "美股", color: "#2a78d6", column: 5 },
    { id: "taiex", label: "台股 (加權指數)", short: "台股", color: "#b42335", column: 6 },
    { id: "btc", label: "比特幣", short: "比特幣", color: "#c27800", column: 7 },
    { id: "gold", label: "黃金", short: "黃金", color: "#1a9480", column: 8 },
]

/** 各序列實際最後有值的日期 (補值前)，美債資料通常比美元晚一天 */
export interface LatestDates {
    dxy: string | null
    bond: string | null
}

export function preparePoints(data: LiquidityData): { points: LiquidityPoint[]; latest: LatestDates } {
    const points: LiquidityPoint[] = []
    let dxy: number | null = null
    let us2y: number | null = null
    let us10y: number | null = null
    let usdtwd: number | null = null
    const assets = Object.fromEntries(ASSETS.map((a) => [a.id, null])) as Record<AssetId, number | null>
    const latest: LatestDates = { dxy: null, bond: null }
    for (const item of data.items) {
        const [date, d, s, l, t] = item as [string, number | null, number | null, number | null, number | null]
        for (const asset of ASSETS) {
            const value = item[asset.column] as number | null | undefined
            if (value != null) {
                assets[asset.id] = value
            }
        }
        if (t != null) {
            usdtwd = t
        }
        if (d != null) {
            dxy = d
            latest.dxy = date
        }
        if (s != null && l != null) {
            us2y = s
            us10y = l
            latest.bond = date
        }
        // 三個序列都出現過之後才開始輸出
        if (dxy == null || us2y == null || us10y == null) {
            continue
        }
        points.push({ date, dxy, us2y, us10y, spread: +(us10y - us2y).toFixed(4), usdtwd, assets: { ...assets } })
    }
    return { points, latest }
}

export interface Reading {
    from: LiquidityPoint
    to: LiquidityPoint
    /** 美元指數變動 (%) */
    dxyPct: number
    /** 美元兌台幣變動 (%)，正值為台幣貶值；缺資料時為 null */
    twdPct: number | null
    /** 殖利率與利差變動 (bp，基點) */
    us2yBp: number
    us10yBp: number
    spreadBp: number
    dxy: Dxy
    curve: Curve
    shape: CurveShape
    regime: Regime
    /** 實際曲線型態與此象限的典型情境是否相同 */
    typical: boolean
    /** 美元或利差變化太小，方向判斷參考價值低 */
    weak: boolean
}

/** 美元變動小於此幅度 (%) 或利差變動小於此基點，視為訊號不明顯 */
const WEAK_DXY_PCT = 0.5
const WEAK_SPREAD_BP = 5

function bp(value: number): number {
    return Math.round(value * 100)
}

export function readAt(points: LiquidityPoint[], index: number, lookback: number): Reading | null {
    if (index - lookback < 0 || index >= points.length) {
        return null
    }
    const from = points[index - lookback]
    const to = points[index]
    const dxyPct = ((to.dxy - from.dxy) / from.dxy) * 100
    const twdPct = to.usdtwd != null && from.usdtwd != null
        ? ((to.usdtwd - from.usdtwd) / from.usdtwd) * 100
        : null
    const us2yBp = bp(to.us2y - from.us2y)
    const us10yBp = bp(to.us10y - from.us10y)
    const spreadBp = us10yBp - us2yBp
    const dxy: Dxy = dxyPct >= 0 ? "up" : "down"
    const curve: Curve = spreadBp >= 0 ? "steep" : "flat"
    const bear = us2yBp + us10yBp >= 0
    const shape: CurveShape = bear
        ? (curve === "flat" ? "bear-flat" : "bear-steep")
        : (curve === "flat" ? "bull-flat" : "bull-steep")
    const regime = regimeOf(dxy, curve)
    return {
        from,
        to,
        dxyPct,
        twdPct,
        us2yBp,
        us10yBp,
        spreadBp,
        dxy,
        curve,
        shape,
        regime,
        typical: shape === regime.shape,
        weak: Math.abs(dxyPct) < WEAK_DXY_PCT || Math.abs(spreadBp) < WEAK_SPREAD_BP,
    }
}

export interface RegimeSpan {
    id: RegimeId
    start: string
    end: string
}

/** 每一天以同樣的回看天數判讀，把連續相同情境的日子合併成區段，畫成歷史色帶 */
export function regimeSpans(points: LiquidityPoint[], lookback: number): RegimeSpan[] {
    const spans: RegimeSpan[] = []
    for (let i = lookback; i < points.length; i++) {
        const id = readAt(points, i, lookback)!.regime.id
        const last = spans[spans.length - 1]
        if (last && last.id === id) {
            last.end = points[i].date
        } else {
            spans.push({ id, start: points[i].date, end: points[i].date })
        }
    }
    return spans
}

/**
 * 台幣偏離：台幣實際變動減去「依美元指數推算的變動」，單位為百分點。
 *
 * 台幣通常只反映美元指數一部分的漲跌，先用全部資料回歸出連動係數 (beta)，
 * 再算每天在同樣回看天數下的殘差：
 *   偏離 = 美元兌台幣變動 (%) - beta × 美元指數變動 (%)
 * 正值表示台幣比美元指數推算的弱 (資金流出台灣，或央行壓抑升值)，
 * 負值表示台幣比推算的強 (資金流入台灣，或央行壓抑貶值)。
 */
export interface TwdDeviation {
    beta: number
    /** 與 points 對齊，資料不足的日子為 null */
    values: (number | null)[]
}

function pctChange(from: number, to: number): number {
    return ((to - from) / from) * 100
}

export function twdDeviation(points: LiquidityPoint[], lookback: number): TwdDeviation {
    const pairs: { i: number; x: number; y: number }[] = []
    for (let i = lookback; i < points.length; i++) {
        const from = points[i - lookback]
        const to = points[i]
        if (from.usdtwd == null || to.usdtwd == null) {
            continue
        }
        pairs.push({ i, x: pctChange(from.dxy, to.dxy), y: pctChange(from.usdtwd, to.usdtwd) })
    }
    const values: (number | null)[] = points.map(() => null)
    if (pairs.length < 2) {
        return { beta: 0, values }
    }
    const meanX = pairs.reduce((sum, p) => sum + p.x, 0) / pairs.length
    const meanY = pairs.reduce((sum, p) => sum + p.y, 0) / pairs.length
    let cov = 0
    let varX = 0
    for (const p of pairs) {
        cov += (p.x - meanX) * (p.y - meanY)
        varX += (p.x - meanX) ** 2
    }
    const beta = varX ? cov / varX : 0
    for (const p of pairs) {
        values[p.i] = +(p.y - beta * p.x).toFixed(3)
    }
    return { beta, values }
}

/** 偏離超過此幅度 (百分點) 才說「明顯」偏強或偏弱 */
export const TWD_GAP_NOTABLE = 1

export function describeTwdGap(gap: number): string {
    if (Math.abs(gap) < TWD_GAP_NOTABLE) {
        return "和美元指數大致同步"
    }
    return gap > 0 ? "比美元指數推算的弱" : "比美元指數推算的強"
}
