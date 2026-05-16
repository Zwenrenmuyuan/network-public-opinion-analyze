<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import HeroBanner from '@/components/HeroBanner.vue'
import KpiRow from '@/components/KpiRow.vue'
import EmotionTrendChart from '@/components/EmotionTrendChart.vue'
import EmotionDonut from '@/components/EmotionDonut.vue'
import RiskTopicList from '@/components/RiskTopicList.vue'
import AiInsightCard from '@/components/AiInsightCard.vue'
import type { OverviewResponse, EmotionTimeseriesPoint, RiskTopic, RangeKey } from '@/types/api'

const metaStore = useMetaStore()
const { data: meta, range } = storeToRefs(metaStore)

const overview = ref<OverviewResponse | null>(null)
const timeseries = ref<EmotionTimeseriesPoint[]>([])
const topics = ref<RiskTopic[]>([])
const errorMsg = ref('')

async function loadAll() {
  errorMsg.value = ''
  const [o, ts, tp] = await Promise.allSettled([
    api.overview(range.value),
    api.emotionTimeseries(range.value),
    api.riskTopics(range.value, 8),
  ])
  if (o.status === 'fulfilled') overview.value = o.value
  if (ts.status === 'fulfilled') timeseries.value = ts.value
  if (tp.status === 'fulfilled') topics.value = tp.value
  const failed = [o, ts, tp].filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
  if (failed.length) errorMsg.value = failed.map((f) => String(f.reason)).join(' / ')
}

function setRange(v: RangeKey) {
  metaStore.setRange(v)
}

onMounted(async () => {
  await metaStore.load()
  await loadAll()
})

watch(range, () => { loadAll() })
</script>

<template>
  <HeroBanner :meta="meta" :overview="overview" :range="range" @update:range="setRange" />
  <KpiRow :overview="overview" :timeseries="timeseries" />
  <AiInsightCard :range="range" />

  <section class="trend-section">
    <div class="section-head">
      <div>
        <p class="eyebrow">EMOTION / TIMELINE</p>
        <h2 class="section-title">情绪趋势 <em>by day</em></h2>
      </div>
    </div>
    <EmotionTrendChart :data="timeseries" />
  </section>

  <section class="lower-grid">
    <div class="flow">
      <div class="section-head">
        <div>
          <p class="eyebrow">RISK / TOP MOVERS</p>
          <h2 class="section-title">风险话题榜 <em>top movers</em></h2>
        </div>
      </div>
      <RiskTopicList :topics="topics" />
    </div>
    <div class="radar">
      <div class="section-head">
        <div>
          <p class="eyebrow">EMOTION / NOW</p>
          <h2 class="section-title">情绪结构 <em>aggregate</em></h2>
        </div>
      </div>
      <EmotionDonut :data="timeseries" />
    </div>
  </section>

  <p v-if="errorMsg" class="error-line">部分接口加载失败：{{ errorMsg }}</p>
</template>

<style scoped>
.trend-section, .lower-grid {
  padding: 70px var(--shell-pad-x) 0;
}
.lower-grid {
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  border-bottom: 1px solid var(--line);
}
.flow {
  padding-right: 60px;
  border-right: 1px solid var(--line);
  padding-bottom: 70px;
}
.radar {
  padding-left: 60px;
  padding-bottom: 70px;
}
.section-head {
  display: flex; justify-content: space-between; align-items: end;
  margin-bottom: 32px;
}
.section-title {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 32px; letter-spacing: -0.02em; color: var(--ink);
}
.section-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  color: var(--muted); margin-left: 14px; font-size: 0.55em;
  letter-spacing: 0.02em; vertical-align: middle;
}
.error-line {
  padding: 16px var(--shell-pad-x);
  color: var(--alert); font-family: var(--mono); font-size: 12px;
}
@media (max-width: 1100px) {
  .lower-grid { grid-template-columns: 1fr; }
  .flow { padding-right: 0; border-right: 0; padding-bottom: 40px; border-bottom: 1px solid var(--line); }
  .radar { padding-left: 0; padding-top: 40px; }
}
</style>
