<script setup lang="ts">
import SideNav from "@/components/SideNav.vue"
</script>

<template>
    <div class="viz-root">
        <div class="layout">
            <SideNav />
            <main class="content">
                <RouterView />
                <footer class="page-foot">
                    資料來源：臺灣證券交易所、證券櫃檯買賣中心公開資料，主動式 ETF 持股取自各投信官網。
                    金額為以收盤價估算之推估值，僅供參考，非投資建議。
                </footer>
            </main>
        </div>
    </div>
</template>
