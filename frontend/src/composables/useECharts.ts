import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import * as echarts from 'echarts'

export function useECharts(target: Ref<HTMLElement | null>, optionRef: Ref<unknown>) {
  let chart: echarts.ECharts | null = null
  let observer: ResizeObserver | null = null

  onMounted(() => {
    if (!target.value) return
    chart = echarts.init(target.value)
    if (optionRef.value) chart.setOption(optionRef.value as echarts.EChartsCoreOption, true)
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(target.value)
  })

  watch(optionRef, (opt) => {
    if (chart && opt) chart.setOption(opt as echarts.EChartsCoreOption, true)
  }, { deep: true })

  onBeforeUnmount(() => {
    observer?.disconnect()
    chart?.dispose()
    chart = null
  })
}
