<script setup lang="ts">
import type { EmotionLabel, ModelEvalSlice } from '@/types/api'
import { EMOTION_COLORS, EMOTION_ORDER } from '@/api/echarts-theme'

const props = defineProps<{
  business: ModelEvalSlice | null
  smp: ModelEvalSlice | null
}>()

function pct(n: number | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return (n * 100).toFixed(1)
}

function widthPct(n: number | undefined): number {
  return Math.max(0, Math.min(100, (Number(n) || 0) * 100))
}
</script>

<template>
  <div class="per-class">
    <div class="head">
      <span class="lbl">类别</span>
      <span class="biz">业务集 F1</span>
      <span class="smp">SMP 测试 F1</span>
    </div>
    <div v-for="label in EMOTION_ORDER" :key="label" class="row">
      <span class="emo" :style="{ color: EMOTION_COLORS[label as EmotionLabel] }">{{ label }}</span>
      <div class="bars">
        <div class="bar-row">
          <div class="bar"><div class="fill biz" :style="{ width: widthPct(props.business?.per_class_f1?.[label]) + '%', background: EMOTION_COLORS[label as EmotionLabel] }"></div></div>
          <div class="val">{{ pct(props.business?.per_class_f1?.[label]) }}</div>
        </div>
        <div class="bar-row" v-if="props.smp">
          <div class="bar"><div class="fill smp" :style="{ width: widthPct(props.smp?.per_class_f1?.[label]) + '%' }"></div></div>
          <div class="val">{{ pct(props.smp?.per_class_f1?.[label]) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.per-class { display: grid; gap: 18px; }
.head {
  display: grid; grid-template-columns: 80px 1fr 1fr;
  gap: 16px;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted);
  padding-bottom: 8px; border-bottom: 1px solid var(--line);
}
.head .biz { text-align: left; }
.head .smp { text-align: left; }

.row {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 16px; align-items: center;
}
.emo {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 16px;
}
.bars { display: grid; gap: 6px; }
.bar-row { display: grid; grid-template-columns: 1fr 56px; gap: 12px; align-items: center; }
.bar {
  height: 8px;
  background: rgba(255,255,255,0.04);
  overflow: hidden;
}
.fill {
  height: 100%;
  transition: width 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fill.smp {
  background: repeating-linear-gradient(90deg, rgba(245,195,74,0.4) 0 4px, transparent 4px 8px);
}
.val {
  text-align: right;
  font-family: var(--mono); font-size: 12px;
  color: var(--ink); font-variant-numeric: tabular-nums;
}
</style>
