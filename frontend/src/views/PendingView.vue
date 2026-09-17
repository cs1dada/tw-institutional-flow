<script setup lang="ts">
/** 尚未遷移的頁面。階段二、三會逐一換成實際內容。 */
defineProps<{ title: string; note: string }>()
</script>

<template>
    <section class="view">
        <header class="page-head">
            <div>
                <h1>{{ title }}</h1>
                <p class="subtitle">{{ note }}</p>
            </div>
        </header>
        <p class="notice">
            這一頁尚未遷移到 Vue 版，目前請使用原本的網站。
        </p>
    </section>
</template>
