<script setup lang="ts">
import type { RangeKey } from '@/types/api'

defineProps<{
  modelValue: RangeKey
  options: RangeKey[]
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: RangeKey): void }>()

const LABEL: Record<RangeKey, string> = {
  all_available: '全部可用',
  '24h': '近 24 小时',
  '7d': '近 7 天',
}
</script>

<template>
  <div class="range-tabs">
    <button
      v-for="opt in options" :key="opt"
      class="tab"
      :class="{ active: opt === modelValue }"
      @click="emit('update:modelValue', opt)"
    >
      {{ LABEL[opt] }}
    </button>
  </div>
</template>

<style scoped>
.range-tabs {
  display: flex; gap: 4px;
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.12em; text-transform: uppercase;
  margin-top: 28px;
}
.tab {
  color: var(--muted);
  padding: 8px 14px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.02);
  transition: color 0.2s, border-color 0.2s, background 0.2s;
}
.tab:hover { color: var(--ink-2); border-color: var(--line-2); }
.tab.active { color: var(--accent); border-color: var(--accent); background: rgba(245,195,74,0.06); }
</style>
