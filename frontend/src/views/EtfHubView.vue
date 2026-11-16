<script setup lang="ts">
/**
 * 主動式 ETF 的外框頁：頂端分頁列切換動向、每日榜單、日報、累積趨勢四個子頁。
 *
 * 子頁各自有路由 (/etf/overview 等)，可以加書籤、重新整理也停在同一頁。
 * 用 keep-alive 保留子頁狀態，切回來時篩選條件與已載入的資料都還在，不必重新抓取。
 */
interface HubTab {
    to: string
    label: string
}

const TABS: HubTab[] = [
    { to: "/etf/overview", label: "動向" },
    { to: "/etf/daily", label: "每日榜單" },
    { to: "/etf/reports", label: "日報" },
    { to: "/etf/trend", label: "累積趨勢" },
]
</script>

<template>
    <div class="etf-hub">
        <nav class="hub-tabs" aria-label="主動式 ETF 分頁">
            <RouterLink
                v-for="tab in TABS"
                :key="tab.to"
                :to="tab.to"
                class="hub-tab"
                active-class="is-active"
            >
                {{ tab.label }}
            </RouterLink>
        </nav>
        <RouterView v-slot="{ Component }">
            <KeepAlive>
                <component :is="Component" />
            </KeepAlive>
        </RouterView>
    </div>
</template>

<style scoped>
/*
 * 分頁列固定在視窗頂端：點側邊欄的區塊捷徑捲到頁面中段後，
 * 不必捲回最上面也能切換分頁。要有底色，捲動時下方內容才不會透出來
 */
.hub-tabs {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    background: var(--surface-0);
    border-bottom: 1px solid var(--border);
    /* 窄螢幕放不下時改為左右滑動，不換行 */
    overflow-x: auto;
    scrollbar-width: none;
}

.hub-tabs::-webkit-scrollbar {
    display: none;
}

.hub-tab {
    flex: none;
    margin-bottom: -1px;
    padding: 8px 16px;
    border-bottom: 2px solid transparent;
    color: var(--text-secondary);
    font-size: 14px;
    text-decoration: none;
    white-space: nowrap;
}

.hub-tab:hover {
    color: var(--text-primary);
}

.hub-tab.is-active {
    border-bottom-color: var(--text-primary);
    color: var(--text-primary);
    font-weight: 600;
}

/* 側邊欄捷徑捲到區塊時，預留分頁列的高度，區塊標題才不會被蓋住 */
.etf-hub :deep(section[data-nav]) {
    scroll-margin-top: 56px;
}

@media (max-width: 900px) {
    .hub-tab {
        padding: 8px 12px;
    }
}
</style>
