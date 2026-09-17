<script setup lang="ts">
/** 側邊導覽。盤中觀察需要後端代抓 MIS，靜態站與功能關閉時都不顯示。 */
import { computed } from "vue"
import { isStatic } from "@/api/dataSource"

interface NavItem {
    to: string
    label: string
    desc: string
    /** 只在本機模式且功能開啟時顯示 */
    apiOnly?: boolean
}

const ITEMS: NavItem[] = [
    { to: "/", label: "類股資金流向", desc: "三大法人買賣超" },
    { to: "/etf", label: "主動式 ETF", desc: "持股與資金動向" },
    { to: "/intraday", label: "盤中觀察", desc: "類股即時強弱", apiOnly: true },
    { to: "/index", label: "大盤指數", desc: "加權指數 K 線" },
]

const intradayEnabled = !isStatic && window.APP_INTRADAY === "on"

const items = computed(() => ITEMS.filter((item) => !item.apiOnly || intradayEnabled))
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
