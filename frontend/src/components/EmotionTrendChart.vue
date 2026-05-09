<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { EMOTION_COLORS, EMOTION_ORDER, baseDark } from '@/api/echarts-theme'
import type { EmotionTimeseriesPoint } from '@/types/api'

const props = withDefaults(defineProps<{ data: EmotionTimeseriesPoint[]; height?: number }>(), {
  height: 320,
})

const chartEl = ref<HTMLElement | null>(null)

const option = computed(() => {
  const series = EMOTION_ORDER.map((label) => ({
    name: label,
    type: 'line' as const,
    stack: 'emotion',
    smooth: true,
    symbol: 'none' as const,
    lineStyle: { width: 0 },
    areaStyle: { opacity: 0.78, color: EMOTION_COLORS[label] },
    data: props.data.map((p) => p.counts[label] || 0),
  }))

  return {
    ...baseDark,
    grid: { left: 50, right: 24, top: 40, bottom: 36 },
    legend: {
      top: 0, right: 0,
      icon: 'circle', itemWidth: 8, itemHeight: 8, itemGap: 14,
      textStyle: { color: '#7d8694', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
    },
    tooltip: { ...baseDark.tooltip, trigger: 'axis' },
    xAxis: {
      type: 'category' as const,
      data: props.data.map((p) => p.time.slice(5)),
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
      axisTick: { show: false },
      axisLabel: { color: '#7d8694', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    },
    yAxis: {
      type: 'value' as const,
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#7d8694', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    },
    series,
  }
})

useECharts(chartEl, option)
</script>

<template>
  <div ref="chartEl" class="trend-chart" :style="{ height: height + 'px' }"></div>
</template>

<style scoped>
.trend-chart { width: 100%; }
</style>
