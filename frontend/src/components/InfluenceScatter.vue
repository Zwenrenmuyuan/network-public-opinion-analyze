<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { EMOTION_COLORS, baseDark } from '@/api/echarts-theme'
import type { InfluenceEmotionPoint } from '@/types/api'

const props = withDefaults(defineProps<{ data: InfluenceEmotionPoint[]; height?: number }>(), {
  height: 480,
})

const chartEl = ref<HTMLElement | null>(null)

const option = computed(() => ({
  ...baseDark,
  grid: { left: 64, right: 32, top: 30, bottom: 56 },
  tooltip: {
    ...baseDark.tooltip,
    trigger: 'item' as const,
    formatter: (p: { data: { name: string; topic: string; roles: string[]; value: number[] } }) => {
      const d = p.data
      return `<strong style="font-size:14px">${d.name}</strong><br/>` +
        `话题：${d.topic}<br/>` +
        `影响力 ${d.value[0].toFixed(0)} · 负面率 ${(d.value[1] * 100).toFixed(0)}%<br/>` +
        `互动 ${d.value[2].toLocaleString()}`
    },
  },
  xAxis: {
    type: 'value' as const,
    name: 'INFLUENCE',
    nameLocation: 'middle' as const,
    nameGap: 36,
    nameTextStyle: { color: '#7d8694', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 'bold' as const },
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    axisLabel: { color: '#7d8694', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    min: 0, max: 100,
  },
  yAxis: {
    type: 'value' as const,
    name: 'NEGATIVE %',
    nameLocation: 'middle' as const,
    nameGap: 48, nameRotate: 90,
    nameTextStyle: { color: '#7d8694', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 'bold' as const },
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    axisLabel: {
      color: '#7d8694', fontSize: 10, fontFamily: 'JetBrains Mono, monospace',
      formatter: (v: number) => (v * 100).toFixed(0),
    },
    min: 0, max: 1,
  },
  series: [{
    type: 'scatter' as const,
    symbolSize: (val: number[]) => {
      const interaction = val[2] || 0
      return Math.max(8, Math.min(48, Math.log10(Math.max(interaction, 1)) * 7 + 6))
    },
    data: props.data.map((p) => ({
      name: p.display_name,
      topic: p.topic_title,
      roles: p.roles,
      value: [p.influence_score, p.negative_ratio, p.interaction_count],
      itemStyle: {
        color: EMOTION_COLORS[p.dominant_emotion],
        opacity: 0.7,
        borderColor: 'rgba(255,255,255,0.25)',
        borderWidth: 1,
      },
    })),
  }],
}))

useECharts(chartEl, option)
</script>

<template>
  <div ref="chartEl" :style="{ width: '100%', height: height + 'px' }"></div>
</template>
