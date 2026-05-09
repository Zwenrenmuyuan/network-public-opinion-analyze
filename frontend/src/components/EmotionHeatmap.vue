<script setup lang="ts">
import { computed, ref } from 'vue'
import { useECharts } from '@/composables/useECharts'
import { baseDark } from '@/api/echarts-theme'

const props = withDefaults(defineProps<{
  labels: string[]
  /** [rowIdx, colIdx, value] cells */
  cells: [number, number, number][]
  rowName?: string
  colName?: string
  height?: number
}>(), { height: 380, rowName: '', colName: '' })

const chartEl = ref<HTMLElement | null>(null)

const maxVal = computed(() => Math.max(1, ...props.cells.map((c) => c[2])))

const option = computed(() => ({
  ...baseDark,
  grid: { left: 70, right: 30, top: 50, bottom: 70 },
  tooltip: {
    ...baseDark.tooltip,
    position: 'top' as const,
    formatter: (p: { value: number[] }) => {
      const [col, row, v] = p.value
      return `${props.rowName || '行'} <strong>${props.labels[row]}</strong> · ${props.colName || '列'} <strong>${props.labels[col]}</strong><br/>` +
        `<strong style="font-size:14px">${v.toLocaleString()}</strong>`
    },
  },
  xAxis: {
    type: 'category' as const,
    data: props.labels,
    position: 'top' as const,
    name: props.colName,
    nameTextStyle: { color: '#7d8694', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 'bold' as const },
    axisLine: { show: false },
    axisTick: { show: false },
    splitArea: { show: false },
    axisLabel: { color: '#d1d5db', fontSize: 12, fontFamily: 'Noto Sans SC' },
  },
  yAxis: {
    type: 'category' as const,
    data: props.labels,
    inverse: true,
    name: props.rowName,
    nameTextStyle: { color: '#7d8694', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 'bold' as const },
    nameLocation: 'middle' as const,
    nameRotate: 90,
    nameGap: 50,
    axisLine: { show: false },
    axisTick: { show: false },
    splitArea: { show: false },
    axisLabel: { color: '#d1d5db', fontSize: 12, fontFamily: 'Noto Sans SC' },
  },
  visualMap: {
    show: false,
    min: 0,
    max: maxVal.value,
    inRange: { color: ['#13171c', '#3a2e1d', '#7a591f', '#c08a2c', '#f5c34a', '#ff8a4d', '#ff4d52'] },
  },
  series: [{
    type: 'heatmap' as const,
    data: props.cells.map((c) => [c[1], c[0], c[2]]),
    label: {
      show: true,
      color: '#0a0c10',
      fontWeight: 'bold' as const,
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 11,
      formatter: (p: { value: number[] }) => (p.value[2] === 0 ? '' : String(p.value[2])),
    },
    itemStyle: { borderColor: '#0d1117', borderWidth: 2 },
  }],
}))

useECharts(chartEl, option)
</script>

<template>
  <div ref="chartEl" :style="{ width: '100%', height: height + 'px' }"></div>
</template>
