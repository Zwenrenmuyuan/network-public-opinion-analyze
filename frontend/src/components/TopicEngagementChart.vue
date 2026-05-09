<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { baseDark } from '@/api/echarts-theme'
import type { EngagementPoint } from '@/types/api'

const props = withDefaults(defineProps<{ data: EngagementPoint[]; height?: number }>(), { height: 220 })

const chartEl = ref<HTMLElement | null>(null)

const option = computed(() => ({
  ...baseDark,
  grid: { left: 50, right: 16, top: 20, bottom: 28 },
  tooltip: { ...baseDark.tooltip, trigger: 'axis' as const },
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
    axisLine: { show: false }, axisTick: { show: false },
    axisLabel: { color: '#7d8694', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
  },
  series: [{
    type: 'line' as const,
    smooth: true,
    symbol: 'circle' as const,
    symbolSize: 5,
    data: props.data.map((p) => p.interaction_count),
    itemStyle: { color: '#f5c34a' },
    lineStyle: { color: '#f5c34a', width: 2 },
    areaStyle: { color: 'rgba(245,195,74,0.12)' },
  }],
}))

useECharts(chartEl, option)
</script>

<template>
  <div ref="chartEl" :style="{ width: '100%', height: height + 'px' }"></div>
</template>
