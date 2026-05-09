<script setup lang="ts">
import { computed } from 'vue'
import RangeTabs from './RangeTabs.vue'
import type { MetaResponse, OverviewResponse, RangeKey } from '@/types/api'
import { formatPercent, formatLargeNumber } from '@/utils/format'

const props = defineProps<{
  meta: MetaResponse | null
  overview: OverviewResponse | null
  range: RangeKey
}>()

const emit = defineEmits<{ (e: 'update:range', v: RangeKey): void }>()

const editionNo = computed(() => {
  if (!props.meta) return '—'
  return `No. ${props.meta.data_window.available_days}`
})

const samplesText = computed(() => {
  if (!props.overview) return '加载中…'
  return `本窗口 ${formatLargeNumber(props.overview.prediction_sample_count)} 条情绪推理样本`
})

const negativeBig = computed(() => {
  if (!props.overview) return '—'
  return formatPercent(props.overview.negative_ratio).replace('%', '')
})
</script>

<template>
  <section class="hero">
    <div class="hero-main reveal">
      <div class="hero-eyebrow">EDITION {{ editionNo }} / 实时研判</div>
      <h1 class="hero-title">
        当前舆情场域<br/>
        <em>正在</em>持续<em>演化</em>
      </h1>
      <p class="hero-lead">{{ samplesText }}。基于 ERNIE × BERT 双模型对照，对微博内容做六分类情绪推理与风险研判。</p>
      <RangeTabs
        v-if="meta"
        :model-value="range"
        :options="meta.time_range_options"
        @update:model-value="(v) => emit('update:range', v)"
      />
    </div>
    <aside class="hero-aside reveal">
      <div class="hero-aside-label">CURRENT NEGATIVE RATIO</div>
      <div class="hero-stat">{{ negativeBig }}</div>
      <div class="hero-aside-foot">% / 负面占比 · 当前窗口</div>
    </aside>
  </section>
</template>

<style scoped>
.hero {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 80px;
  padding: 80px var(--shell-pad-x) 60px;
  align-items: end;
}
.hero-eyebrow {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 32px;
  display: flex; align-items: center; gap: 14px;
}
.hero-eyebrow::before { content: ''; width: 40px; height: 1px; background: var(--accent); }
.hero-title {
  font-family: var(--serif-cn); font-weight: 900;
  font-size: clamp(48px, 7vw, 88px);
  line-height: 0.96; letter-spacing: -0.04em; color: var(--ink);
}
.hero-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  font-variation-settings: "SOFT" 100, "opsz" 144;
  color: var(--accent); font-size: 0.92em; letter-spacing: -0.02em;
}
.hero-lead { margin-top: 28px; max-width: 560px; color: var(--ink-2); font-size: 15px; line-height: 1.85; }
.hero-aside { border-left: 1px solid var(--line-2); padding-left: 40px; }
.hero-aside-label {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 18px;
}
.hero-stat {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 30, "opsz" 144;
  font-weight: 300;
  font-size: clamp(80px, 10vw, 128px);
  line-height: 1; letter-spacing: -0.05em; color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.hero-aside-foot {
  margin-top: 22px;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted);
}
@media (max-width: 1100px) {
  .hero { grid-template-columns: 1fr; padding: 56px var(--shell-pad-x) 40px; gap: 40px; }
  .hero-aside { border-left: 0; padding-left: 0; border-top: 1px solid var(--line-2); padding-top: 32px; }
}
</style>
