<script setup lang="ts">
/**
 * 逐週淨額的迷你長條：中線為零軸，買超往上、賣超往下，高度以該列最大的一週為基準。
 */
import { computed } from "vue"

const props = defineProps<{
    /** 逐週淨額 (億)，由舊到新 */
    weekly: number[]
    /** 各週的標籤，提示框與無障礙說明用 */
    labels: string[]
}>()

const max = computed(() => Math.max(...props.weekly.map(Math.abs)))

function signed(value: number): string {
    return (value > 0 ? "+" : "") + value.toFixed(2)
}

/** 零軸在中線，因此最高只到一半 */
function height(value: number): string {
    return max.value && value ? `${Math.max(4, (Math.abs(value) / max.value) * 50)}%` : "0"
}

const aria = computed(() => props.weekly.map((v, i) => `${props.labels[i] ?? ""} ${signed(v)} 億`).join("，"))
</script>

<template>
    <div class="spark" role="img" :aria-label="aria">
        <span v-for="(v, i) in weekly" :key="i" class="spark-cell" :title="`${labels[i] ?? ''}　${signed(v)} 億`">
            <span class="spark-bar" :class="v > 0 ? 'is-buy' : 'is-sell'" :style="{ height: height(v) }" />
        </span>
    </div>
</template>

<style scoped>
.spark {
    display: flex;
    align-items: center;
    gap: 2px;
    width: max-content;
    height: 28px;
}

.spark-cell {
    position: relative;
    width: 8px;
    height: 100%;
}

.spark-cell::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    border-top: 1px solid var(--border);
}

.spark-bar {
    position: absolute;
    left: 0;
    right: 0;
    border-radius: 1px;
}

.spark-bar.is-buy {
    bottom: 50%;
    background: var(--buy);
}

.spark-bar.is-sell {
    top: 50%;
    background: var(--sell);
}
</style>
