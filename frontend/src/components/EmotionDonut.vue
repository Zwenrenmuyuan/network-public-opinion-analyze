<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { EMOTION_COLORS, EMOTION_ORDER, baseDark } from '@/api/echarts-theme'
import type { EmotionTimeseriesPoint, EmotionLabel } from '@/types/api'
import { formatPercent } from '@/utils/format'

const props = defineProps<{ data: EmotionTimeseriesPoint[] }>()

const chartEl = ref<HTMLElement | null>(null)

const aggregated = computed<Record<EmotionLabel, number>>(() => {
  const sum: Record<EmotionLabel, number> = {
    '积极': 0, '愤怒': 0, '悲伤': 0, '恐惧': 0, '惊讶': 0, '中性': 0,
  }
  for (const p of props.data) {
    for (const lbl of EMOTION_ORDER) sum[lbl] += p.counts[lbl] || 0
  }
  return sum
})

const total = computed(() => EMOTION_ORDER.reduce((a, l) => a + aggregated.value[l], 0))
const negativeRatio = computed(() => {
  if (!total.value) return 0
  return (aggregated.value['愤怒'] + aggregated.value['悲伤'] + aggregated.value['恐惧']) / total.value
})

const legendItems = computed(() =>
  EMOTION_ORDER.map((label) => {
    const v = aggregated.value[label]
    const r = total.value ? v / total.value : 0
    return { label, color: EMOTION_COLORS[label], pct: (r * 100).toFixed(1) + '%' }
  })
)

const option = computed(() => ({
  ...baseDark,
  tooltip: {
    ...baseDark.tooltip,
    trigger: 'item' as const,
    formatter: (p: { name: string; value: number; percent: number }) =>
      `${p.name}<br/><strong style="font-size:14px">${p.value.toLocaleString()}</strong> · ${p.percent}%`,
  },
  series: [{
    type: 'pie' as const,
    radius: ['62%', '88%'],
    center: ['50%', '50%'],
    avoidLabelOverlap: true,
    label: { show: false },
    labelLine: { show: false },
    itemStyle: { borderColor: '#0d1117', borderWidth: 2 },
    data: EMOTION_ORDER.map((label) => ({
      name: label,
      value: aggregated.value[label],
      itemStyle: { color: EMOTION_COLORS[label] },
    })),
  }],
}))

useECharts(chartEl, option)
</script>

<template>
  <div class="donut-wrap">
    <div ref="chartEl" class="donut-chart"></div>
    <div class="donut-center">
      <strong>{{ formatPercent(negativeRatio).replace('%','') }}</strong>
      <small>负面占比 %</small>
    </div>
  </div>
  <div class="donut-legend">
    <div v-for="it in legendItems" :key="it.label">
      <i :style="{ background: it.color }"></i>{{ it.label }}<b>{{ it.pct }}</b>
    </div>
  </div>
</template>

<style scoped>
.donut-wrap {
  position: relative;
  display: grid; place-items: center;
}
.donut-chart { width: 280px; height: 280px; }
.donut-center {
  position: absolute;
  text-align: center;
  pointer-events: none;
}
.donut-center strong {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 30, "opsz" 144;
  font-size: 56px; font-weight: 400;
  color: var(--ink); line-height: 1;
  display: block;
  font-variant-numeric: tabular-nums;
}
.donut-center small {
  display: block; margin-top: 8px;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--muted);
}
.donut-legend {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px 24px;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
  border-top: 1px solid var(--line);
  padding-top: 22px; margin-top: 24px;
}
.donut-legend div { display: flex; align-items: center; gap: 10px; }
.donut-legend i { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.donut-legend b { color: var(--ink-2); font-weight: 500; margin-left: auto; font-variant-numeric: tabular-nums; }
</style>
