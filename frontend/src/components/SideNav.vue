<script setup lang="ts">
/**
 * 側邊導覽。
 *
 * 盤中觀察需要後端代抓 MIS，即時行情需要後端代抓富果與期交所
 * (金鑰不能放進前端)，兩者在靜態站與功能關閉時都不顯示。
 */
import { computed } from "vue"
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
            </RouterLink>
        </div>
    </nav>
</template>
