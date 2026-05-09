<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ counts: Record<string, number> }>()

const SOURCE_LABEL: Record<string, string> = {
  hot: '热搜', keyword: '关键词', kol: 'KOL', retweet: '转发',
}
const ORDER = ['hot', 'keyword', 'kol', 'retweet']

const total = computed(() => ORDER.reduce((a, k) => a + (props.counts[k] || 0), 0))
const items = computed(() =>
  ORDER.map((k) => {
    const v = props.counts[k] || 0
    return { key: k, label: SOURCE_LABEL[k] ?? k, v, pct: total.value ? v / total.value : 0 }
  }),
)
</script>

<template>
  <div class="src-bars">
    <div v-for="it in items" :key="it.key" class="row">
      <div class="lbl">{{ it.label }}</div>
      <div class="track"><div class="fill" :style="{ width: it.pct * 100 + '%' }"></div></div>
      <div class="val">{{ it.v }}</div>
    </div>
  </div>
</template>

<style scoped>
.src-bars { display: grid; gap: 12px; padding: 18px 4px; }
.row {
  display: grid;
  grid-template-columns: 56px 1fr 40px;
  gap: 14px;
  align-items: center;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.lbl { font-family: var(--sans-cn); color: var(--ink-2); font-size: 13px; }
.track { height: 8px; background: rgba(255,255,255,0.05); overflow: hidden; }
.fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), rgba(245,195,74,0.4));
  transition: width 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.val { text-align: right; color: var(--ink); font-variant-numeric: tabular-nums; }
</style>
