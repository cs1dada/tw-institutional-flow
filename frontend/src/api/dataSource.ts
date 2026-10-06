/**
 * 雙模式資料來源。
 *
 * 本機由 FastAPI 提供頁面並注入 mode=api，走 /api 端點；
 * GitHub Pages 上為匯出的靜態頁，mode=static，直接讀 JSON 檔。
 * 兩者格式相同，因此之後的篩選與衍生計算都在前端完成。
 *
 * 這一層是舊版 app.js「資料層」區塊的等價物，差別只在於改用模組匯出。
 */
import type {
    DayData,
    EtfCostDetail,
    EtfCostSummary,
    EtfDailyData,
    EtfDailyDates,
    EtfData,
    HistoryData,
    IndexPayload,
    Meta,
} from "@/types"

const MODE: "api" | "static" = window.APP_MODE === "static" ? "static" : "api"

export const isStatic = MODE === "static"

/** 靜態模式下資料檔的版本號，由 meta.generated_at 提供 */
let dataVersion: string | null = null

/**
 * 以 meta 的產生時間作為版本號。資料更新後版本改變，訪客會取得新內容；
 * 未更新時仍可沿用瀏覽器快取。
 */
function versioned(path: string): string {
    return dataVersion ? `${path}?v=${dataVersion}` : path
}

const SOURCES = {
    static: {
        // meta 很小且必須是最新的，加上時間戳避開 GitHub Pages 的快取
        meta: () => `data/meta.json?t=${Date.now()}`,
        day: (date: string) => versioned(`data/day/${date}.json`),
        history: () => versioned("data/history.json"),
        etf: () => versioned("data/etf.json"),
        index: () => versioned("data/index.json"),
        etfCost: () => versioned("data/etf_cost.json"),
        etfCostDetail: (code: string) => versioned(`data/etf_cost/${code}.json`),
        etfDailyDates: () => versioned("data/etf_daily.json"),
        etfDaily: (date: string) => versioned(`data/etf_daily/${date}.json`),
    },
    api: {
        meta: () => "/api/meta",
        day: (date: string) => `/api/day/${date}`,
        history: () => "/api/history",
        etf: () => "/api/etf-data",
        index: () => "/api/index-data",
        etfCost: () => "/api/etf-cost",
        etfCostDetail: (code: string) => `/api/etf-cost/${code}`,
        etfDailyDates: () => "/api/etf-daily",
        etfDaily: (date: string) => `/api/etf-daily/${date}`,
    },
} as const

async function fetchJson<T>(url: string): Promise<T> {
    const resp = await fetch(url)
    if (!resp.ok) {
        // FastAPI 的錯誤放在 detail，靜態檔則只有狀態文字
        const text = await resp.text()
        let detail = resp.statusText
        try {
            detail = (JSON.parse(text) as { detail?: string }).detail ?? text
        } catch {
            detail = text || resp.statusText
        }
        throw new Error(detail)
    }
    return resp.json() as Promise<T>
}

/* 各資料檔只會載入一次，切換頁面時不重新請求 */
const cache: {
    meta: Meta | null
    days: Map<string, DayData>
    history: HistoryData | null
    etf: EtfData | null
    index: IndexPayload | null
    etfCost: EtfCostSummary | null
    etfCostDetails: Map<string, EtfCostDetail>
    etfDailyDates: EtfDailyDates | null
    etfDaily: Map<string, EtfDailyData>
} = {
    meta: null,
    days: new Map(),
    history: null,
    etf: null,
    index: null,
    etfCost: null,
    etfCostDetails: new Map(),
    etfDailyDates: null,
    etfDaily: new Map(),
}

export async function loadMeta(): Promise<Meta> {
    if (cache.meta) {
        return cache.meta
    }
    const meta = await fetchJson<Meta>(SOURCES[MODE].meta())
    cache.meta = meta
    dataVersion = meta.generated_at
    return meta
}

export async function loadDay(date: string): Promise<DayData> {
    const cached = cache.days.get(date)
    if (cached) {
        return cached
    }
    // 靜態模式的檔名帶版本號，必須先取得 meta
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<DayData>(SOURCES[MODE].day(date))
    cache.days.set(date, data)
    return data
}

export async function loadHistory(): Promise<HistoryData> {
    if (cache.history) {
        return cache.history
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<HistoryData>(SOURCES[MODE].history())
    cache.history = data
    return data
}

export async function loadEtf(): Promise<EtfData> {
    if (cache.etf) {
        return cache.etf
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<EtfData>(SOURCES[MODE].etf())
    cache.etf = data
    return data
}

export async function loadIndex(): Promise<IndexPayload> {
    if (cache.index) {
        return cache.index
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<IndexPayload>(SOURCES[MODE].index())
    cache.index = data
    return data
}

export async function loadEtfCost(): Promise<EtfCostSummary> {
    if (cache.etfCost) {
        return cache.etfCost
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<EtfCostSummary>(SOURCES[MODE].etfCost())
    cache.etfCost = data
    return data
}

/** 個股疊圖資料，點選個股時才下載 */
export async function loadEtfCostDetail(code: string): Promise<EtfCostDetail> {
    const cached = cache.etfCostDetails.get(code)
    if (cached) {
        return cached
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<EtfCostDetail>(SOURCES[MODE].etfCostDetail(code))
    cache.etfCostDetails.set(code, data)
    return data
}

export async function loadEtfDailyDates(): Promise<EtfDailyDates> {
    if (cache.etfDailyDates) {
        return cache.etfDailyDates
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<EtfDailyDates>(SOURCES[MODE].etfDailyDates())
    cache.etfDailyDates = data
    return data
}

/** ETF 每日榜單，切換日期時才下載 */
export async function loadEtfDaily(date: string): Promise<EtfDailyData> {
    const cached = cache.etfDaily.get(date)
    if (cached) {
        return cached
    }
    if (isStatic && !dataVersion) {
        await loadMeta()
    }
    const data = await fetchJson<EtfDailyData>(SOURCES[MODE].etfDaily(date))
    cache.etfDaily.set(date, data)
    return data
}
