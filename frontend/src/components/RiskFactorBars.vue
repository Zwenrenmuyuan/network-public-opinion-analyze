<script setup lang="ts">
import type { TopicMeta } from '@/types/api'

defineProps<{ meta: TopicMeta }>()

const FACTOR_MAX: Record<string, number> = {
  negative_ratio: 25,
  negative_growth: 20,
  interaction_growth: 20,
  anger_fear: 15,
  kol_verified: 10,
  source_diversity: 10,
}

const ORDER = ['negative_ratio', 'negative_growth', 'interaction_growth', 'anger_fear', 'kol_verified', 'source_diversity']

function pct(v: number, key: string): number {
  return Math.min(100, (v / (FACTOR_MAX[key] || 25)) * 100)
}
</script>

<template>
  <div class="bars">
    <div v-for="key in ORDER" :key="key" class="row">
      <div class="lbl">{{ meta.risk_factor_labels?.[key] ?? key }}</div>
      <div class="track">
        <div class="fill" :style="{ width: pct(meta.risk_factors[key] ?? 0, key) + '%' }"></div>
      </div>
      <div class="val">{{ (meta.risk_factors[key] ?? 0).toFixed(1) }}</div>
    </div>
  </div>
</template>

<style scoped>
.bars { display: grid; gap: 14px; }
.row {
  display: grid;
  grid-template-columns: 110px 1fr 48px;
  align-items: center;
  gap: 14px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.04em;
}
.lbl {
  font-family: var(--sans-cn);
  color: var(--ink-2);
  font-size: 13px;
  letter-spacing: 0;
}
.track {
  height: 6px;
  background: rgba(255,255,255,0.05);
  overflow: hidden;
}
.fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--alert));
  transition: width 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.val {
  text-align: right;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
</style>
