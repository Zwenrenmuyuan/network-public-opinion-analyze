<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { EMOTION_COLORS, EMOTION_ORDER, baseDark } from '@/api/echarts-theme'
import type { EmotionCounts } from '@/types/api'

const props = withDefaults(defineProps<{ counts: EmotionCounts; height?: number }>(), { height: 220 })

const chartEl = ref<HTMLElement | null>(null)

const option = computed(() => ({
  ...baseDark,
  tooltip: {
    ...baseDark.tooltip,
    trigger: 'item' as const,
    formatter: (p: { name: string; value: number; percent: number }) =>
      `${p.name}<br/><strong>${p.value.toLocaleString()}</strong> · ${p.percent}%`,
  },
  series: [{
    type: 'pie' as const,
    radius: ['56%', '88%'],
    center: ['50%', '50%'],
    avoidLabelOverlap: true,
    label: { show: false },
    labelLine: { show: false },
    itemStyle: { borderColor: '#0d1117', borderWidth: 2 },
    data: EMOTION_ORDER.map((l) => ({
      name: l,
      value: props.counts[l] || 0,
      itemStyle: { color: EMOTION_COLORS[l] },
    })),
  }],
}))

useECharts(chartEl, option)
</script>

<template>
  <div ref="chartEl" :style="{ width: '100%', height: height + 'px' }"></div>
</template>
