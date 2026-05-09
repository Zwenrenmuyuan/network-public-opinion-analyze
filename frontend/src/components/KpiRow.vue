<script setup lang="ts">
import { computed } from 'vue'
import type { OverviewResponse, EmotionTimeseriesPoint } from '@/types/api'
import { formatLargeNumber, formatPercent } from '@/utils/format'

const props = defineProps<{
  overview: OverviewResponse | null
  timeseries: EmotionTimeseriesPoint[]
}>()

interface KpiCard {
  label: string
  value: string
  sparkColor?: string
  sparkPoints?: number[]
}

const kpis = computed<KpiCard[]>(() => {
  const o = props.overview
  const series = props.timeseries
  const totals = series.map((p) => Object.values(p.counts).reduce((a, b) => a + b, 0))
  const negs = series.map((p) => p.negative_ratio)
  return [
    { label: '帖子数', value: formatLargeNumber(o?.post_count), sparkColor: '#4ade80', sparkPoints: totals },
    { label: '负面率', value: formatPercent(o?.negative_ratio), sparkColor: '#ff4d52', sparkPoints: negs },
    { label: '采样评论', value: formatLargeNumber(o?.sampled_comment_count) },
    { label: '活跃话题', value: formatLargeNumber(o?.active_topic_count) },
    { label: '互动总量', value: formatLargeNumber(o?.latest_interactions) },
  ]
})

function buildPath(points: number[] | undefined): string {
  if (!points || points.length < 2) return ''
  const max = Math.max(...points, 1)
  const min = Math.min(...points, 0)
  const range = max - min || 1
  const w = 92, h = 28
  return points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * w
      const y = h - ((v - min) / range) * h
      return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1)
    })
    .join(' ')
}
</script>

<template>
  <section class="kpi-row">
    <div
      v-for="(k, i) in kpis" :key="k.label"
      class="kpi reveal"
      :style="{ animationDelay: `${0.05 + i * 0.05}s` }"
    >
      <div class="kpi-label">{{ k.label }}</div>
      <div class="kpi-num">{{ k.value }}</div>
      <svg
        v-if="k.sparkPoints && k.sparkPoints.length > 1"
        class="kpi-spark" viewBox="0 0 92 28" preserveAspectRatio="none"
      >
        <path :d="buildPath(k.sparkPoints)" fill="none" :stroke="k.sparkColor" stroke-width="1.4" />
      </svg>
    </div>
  </section>
</template>

<style scoped>
.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin: 0 var(--shell-pad-x);
}
.kpi {
  padding: 30px 28px 26px;
  border-right: 1px solid var(--line);
  position: relative; overflow: hidden;
  transition: background 0.3s;
}
.kpi:hover { background: rgba(245,195,74,0.025); }
.kpi:last-child { border-right: 0; }
.kpi-label {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--muted);
}
.kpi-num {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 50, "opsz" 144;
  font-weight: 400;
  font-size: 44px; line-height: 1.1; letter-spacing: -0.04em;
  color: var(--ink); margin-top: 14px;
  font-variant-numeric: tabular-nums;
}
.kpi-spark {
  position: absolute; right: 18px; top: 28px;
  width: 92px; height: 30px; opacity: 0.6;
}
@media (max-width: 1100px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .kpi:nth-child(2n) { border-right: 0; }
  .kpi:nth-child(-n+4) { border-bottom: 1px solid var(--line); }
}
</style>
