<script setup lang="ts">
/**
 * 側邊導覽。
 *
 * 盤中觀察需要後端代抓 MIS，即時行情需要後端代抓富果與期交所
 * (金鑰不能放進前端)，兩者在靜態站與功能關閉時都不顯示。
 *
 * 目前所在的頁籤下方會展開該頁各區塊的捷徑。區塊由各頁面以 data-nav 屬性標記，
 * 這裡自動從畫面上找出來，各頁面不需要另外登記。有些區塊要等資料載入或使用者
 * 操作後才出現，因此監看內容區的 DOM 變化隨時更新。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"

import { isStatic } from "@/api/dataSource"

interface NavItem {
    to: string
    label: string
    desc: string
    /** 盤中觀察：只在本機模式且 INTRADAY_ENABLED 為開時顯示 */
    apiOnly?: boolean
    /** 即時行情：只在本機模式且後端有設定富果金鑰時顯示 */
    quoteOnly?: boolean
    /** 永豐行情：只在本機模式且後端有設定 Shioaji 金鑰時顯示 */
    sinoOnly?: boolean
}

const ITEMS: NavItem[] = [
    { to: "/", label: "類股資金流向", desc: "三大法人買賣超" },
    { to: "/etf", label: "主動式 ETF", desc: "持股與資金動向" },
    { to: "/daily", label: "ETF 每日榜單", desc: "被買最兇、被賣最重、最擁擠" },
    { to: "/intraday", label: "盤中觀察", desc: "類股即時強弱", apiOnly: true },
    { to: "/quote", label: "即時行情", desc: "富果：微台、大盤與個股", quoteOnly: true },
    { to: "/sino", label: "永豐行情", desc: "Shioaji：微台、大盤與個股", sinoOnly: true },
    { to: "/index", label: "大盤指數", desc: "加權指數 K 線" },
]

const intradayEnabled = !isStatic && window.APP_INTRADAY === "on"
const quoteEnabled = !isStatic && window.APP_QUOTE === "on"
const sinoEnabled = !isStatic && window.APP_SINO === "on"

const items = computed(() =>
    ITEMS.filter(
        (item) =>
            (!item.apiOnly || intradayEnabled)
            && (!item.quoteOnly || quoteEnabled)
            && (!item.sinoOnly || sinoEnabled),
    ),
)

/* ===== 區塊捷徑 ===== */

interface Section {
    id: string
    label: string
}

const SECTION_SELECTOR = ".content section[data-nav]"
// 區塊頂端捲到視窗上緣這個距離內，就視為目前所在的區塊
const CURRENT_OFFSET = 120

const route = useRoute()
const sections = ref<Section[]>([])
const current = ref<string | null>(null)

let observer: MutationObserver | null = null
let pending = 0

function sectionElements(): HTMLElement[] {
    return [...document.querySelectorAll<HTMLElement>(SECTION_SELECTOR)]
}

function scan() {
    pending = 0
    const found = sectionElements().map((el, i) => {
        if (!el.id) {
            el.id = `section-${i}`
        }
        return { id: el.id, label: el.dataset.nav ?? "" }
    })
    // 內容沒變就不更新，避免無謂的重新渲染
    const same = found.length === sections.value.length
        && found.every((s, i) => s.id === sections.value[i].id && s.label === sections.value[i].label)
    if (!same) {
        sections.value = found
    }
    updateCurrent()
}

/** DOM 一次可能變動很多處，合併到下一個畫格再掃描 */
function scheduleScan() {
    if (!pending) {
        pending = requestAnimationFrame(scan)
    }
}

function updateCurrent() {
    const els = sectionElements()
    if (!els.length) {
        current.value = null
        return
    }
    // 已捲到頁面底部時，最後幾個區塊可能碰不到上緣，直接標示最後一個
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4
    if (atBottom) {
        current.value = els[els.length - 1].id
        return
    }
    let id = els[0].id
    for (const el of els) {
        if (el.getBoundingClientRect().top <= CURRENT_OFFSET) {
            id = el.id
        }
    }
    current.value = id
}

function jump(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })
    current.value = id
}

onMounted(() => {
    const content = document.querySelector(".content")
    if (content) {
        observer = new MutationObserver(scheduleScan)
        observer.observe(content, { childList: true, subtree: true })
    }
    window.addEventListener("scroll", updateCurrent, { passive: true })
    scan()
})

onBeforeUnmount(() => {
    observer?.disconnect()
    window.removeEventListener("scroll", updateCurrent)
    if (pending) {
        cancelAnimationFrame(pending)
    }
})

// 切換頁籤時先清空，等新頁面渲染後再掃描
watch(
    () => route.path,
    async () => {
        sections.value = []
        await nextTick()
        scheduleScan()
    },
)
</script>

<template>
    <nav class="sidebar">
        <div class="sidebar-brand">台股法人動向</div>
        <div v-for="item in items" :key="item.to" class="nav-group">
            <RouterLink v-slot="{ isActive, navigate }" :to="item.to" custom>
                <button
                    type="button"
                    class="nav-item"
                    :class="{ 'is-active': isActive }"
                    @click="navigate"
                >
                    <span class="nav-label">{{ item.label }}</span>
                    <span class="nav-desc">{{ item.desc }}</span>
                </button>
                <div v-if="isActive && sections.length" class="sub-nav">
                    <button
                        v-for="section in sections"
                        :key="section.id"
                        type="button"
                        class="sub-item"
                        :class="{ 'is-current': section.id === current }"
                        @click="jump(section.id)"
                    >
                        {{ section.label }}
                    </button>
                </div>
            </RouterLink>
        </div>
    </nav>
</template>
