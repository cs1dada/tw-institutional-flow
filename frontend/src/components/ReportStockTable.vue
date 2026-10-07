<script setup lang="ts">
/**
 * ETF 日報共用的個股表格：買賣家數、金額與出手的 ETF。
 *
 * 各指標只差在排序與額外的一欄 (例如共識升溫的家數變化)，
 * 額外欄位由 extra 插槽提供。
 */
import type { EtfReportStockRow } from "@/types"

defineProps<{
    rows: EtfReportStockRow[]
    etfLabel: (code: string) => string
    extraHead?: string
}>()

function amt(value: number): string {
    if (!value) {
        return ""
    }
    return (value > 0 ? "+" : "") + value.toFixed(2)
}

function polarity(value: number): string {
    if (!value) {
        return ""
    }
    return value > 0 ? "val-buy" : "val-sell"
}
</script>

<template>
    <div class="table-wrap">
        <table class="data-table">
            <thead>
                <tr>
                    <th>代號</th><th>名稱</th><th>類股</th>
                    <th v-if="extraHead" class="num">{{ extraHead }}</th>
                    <th class="num">加碼家數</th>
                    <th class="num">加碼（億）</th>
                    <th class="num">減碼家數</th>
                    <th class="num">減碼（億）</th>
                    <th class="num">淨額（億）</th>
                    <th>ETF</th>
                </tr>
            </thead>
            <tbody>
                <tr v-if="!rows.length" class="empty-row">
                    <td :colspan="extraHead ? 10 : 9">無資料</td>
                </tr>
                <tr v-for="row in rows" :key="row.code">
                    <td>{{ row.code }}</td>
                    <td>{{ row.name ?? "" }}</td>
                    <td class="muted">{{ row.industry ?? "" }}</td>
                    <td v-if="extraHead" class="num"><slot name="extra" :row="row" /></td>
                    <td class="num">{{ row.buy_count || "" }}</td>
                    <td class="num val-buy">{{ amt(row.buy_amt) }}</td>
                    <td class="num">{{ row.sell_count || "" }}</td>
                    <td class="num val-sell">{{ amt(row.sell_amt) }}</td>
                    <td class="num" :class="polarity(row.net_amt)">{{ amt(row.net_amt) }}</td>
                    <td class="etf-list">
                        <span v-for="code in row.buy_etfs" :key="`b${code}`" class="val-buy" :title="etfLabel(code)">{{ code }}</span>
                        <span v-for="code in row.sell_etfs" :key="`s${code}`" class="val-sell" :title="etfLabel(code)">{{ code }}</span>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style scoped>
.muted {
    color: var(--text-secondary);
    font-size: 12px;
}

.etf-list {
    font-size: 12px;
}

.etf-list span + span {
    margin-left: 6px;
}
</style>
