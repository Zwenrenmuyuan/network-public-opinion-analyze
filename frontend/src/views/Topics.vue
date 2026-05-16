<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import RangeTabs from '@/components/RangeTabs.vue'
import RiskFactorBars from '@/components/RiskFactorBars.vue'
import EmotionTrendChart from '@/components/EmotionTrendChart.vue'
import TopicEmotionPie from '@/components/TopicEmotionPie.vue'
import TopicEngagementChart from '@/components/TopicEngagementChart.vue'
import TopicSourceMix from '@/components/TopicSourceMix.vue'
import ActorList from '@/components/ActorList.vue'
import EvidenceList from '@/components/EvidenceList.vue'
import InfluenceScatter from '@/components/InfluenceScatter.vue'
import AiInsightCard from '@/components/AiInsightCard.vue'
import { EMOTION_COLORS, EMOTION_ORDER } from '@/api/echarts-theme'
import { formatLargeNumber } from '@/utils/format'
import type { InfluenceEmotionPoint, RangeKey, RiskTopic, TopicDetailResponse } from '@/types/api'

const route = useRoute()
const router = useRouter()
const metaStore = useMetaStore()
const { data: meta, range } = storeToRefs(metaStore)

const topics = ref<RiskTopic[]>([])
const detail = ref<TopicDetailResponse | null>(null)
const scatter = ref<InfluenceEmotionPoint[]>([])
const loadingList = ref(false)
const loadingDetail = ref(false)
const errorMsg = ref('')

const selectedId = computed(() => (route.params.id ? String(route.params.id) : null))

async function loadList() {
  loadingList.value = true
  try {
    topics.value = await api.riskTopics(range.value, 30)
  } catch (e) {
    errorMsg.value = (e as Error).message
  } finally {
    loadingList.value = false
  }
}

async function loadDetail(id: string) {
  loadingDetail.value = true
  detail.value = null
  scatter.value = []
  errorMsg.value = ''
  try {
    const [detailR, scatterR] = await Promise.allSettled([
      api.topicDetail(id, range.value, { limit: 6, actorLimit: 6 }),
      api.influenceEmotion(range.value, 200, id),
    ])
    if (detailR.status === 'fulfilled') detail.value = detailR.value
    if (scatterR.status === 'fulfilled') scatter.value = scatterR.value
    const failed = [detailR, scatterR].filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
    if (failed.length) errorMsg.value = failed.map((f) => String(f.reason)).join(' / ')
  } finally {
    loadingDetail.value = false
  }
}

function selectTopic(t: RiskTopic) {
  router.push(`/topics/${t.topic_id}`)
}

function setRange(v: RangeKey) {
  metaStore.setRange(v)
}

function stack(emoCounts: Record<string, number>) {
  const total = EMOTION_ORDER.reduce((a, l) => a + (emoCounts[l] || 0), 0)
  if (!total) return []
  return EMOTION_ORDER.map((l) => ({
    color: EMOTION_COLORS[l],
    pct: ((emoCounts[l] || 0) / total) * 100,
  })).filter((x) => x.pct > 0)
}

const LEVEL_LABEL: Record<string, string> = {
  high: '高风险', medium_high: '中高风险', medium: '中风险', low: '低风险',
}
const LEVEL_CLASS: Record<string, string> = {
  high: 'high', medium_high: 'high', medium: 'medium', low: 'low',
}

onMounted(async () => {
  await metaStore.load()
  await loadList()
  if (selectedId.value) await loadDetail(selectedId.value)
})

watch(range, async () => {
  await loadList()
  if (selectedId.value) await loadDetail(selectedId.value)
})

watch(selectedId, (id) => { if (id) loadDetail(id) })
</script>

<template>
  <section class="page-head">
    <div class="reveal">
      <p class="page-eyebrow">SECTION II / TOPICS</p>
      <h1 class="page-title">话题<em>详情</em></h1>
      <p class="page-lead">在左侧选择话题，右侧呈现风险因子拆解、情绪结构、互动曲线、入口分布、关键账号与证据样本。</p>
    </div>
    <div class="page-meta reveal">
      <RangeTabs v-if="meta" :model-value="range" :options="meta.time_range_options" @update:model-value="setRange" />
    </div>
  </section>

  <section class="topic-grid">
    <aside class="master">
      <div class="master-head">
        <p class="eyebrow">RISK / TOP TOPICS</p>
        <span class="count">{{ topics.length }} 条</span>
      </div>
      <div class="master-list">
        <button
          v-for="(t, i) in topics" :key="t.topic_id"
          class="master-item"
          :class="{ active: t.topic_id === selectedId }"
          @click="selectTopic(t)"
        >
          <div class="m-head">
            <span class="m-num">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="m-score" :class="LEVEL_CLASS[t.risk_level]">{{ t.risk_score.toFixed(1) }}</span>
          </div>
          <div class="m-title">{{ t.title || '（无标题）' }}</div>
          <div class="m-meta">
            <span>{{ LEVEL_LABEL[t.risk_level] ?? t.risk_level }}</span>
            <span>负面 {{ (t.negative_ratio * 100).toFixed(0) }}%</span>
            <span>{{ formatLargeNumber(t.sample_count) }} 样本</span>
          </div>
          <div class="m-stack">
            <span v-for="(s, j) in stack(t.emotion_counts)" :key="j"
                  :style="{ background: s.color, width: s.pct + '%' }"></span>
          </div>
        </button>
        <p v-if="!topics.length && !loadingList" class="empty">暂无话题</p>
      </div>
    </aside>

    <article class="detail">
      <div v-if="!selectedId" class="placeholder">
        <p class="eyebrow">SELECT A TOPIC</p>
        <h2 class="ph-title">请从左侧<em>选择</em>一个话题</h2>
        <p class="ph-lead">详情会展示该话题的风险因子拆解、情绪结构与趋势、互动曲线、入口分布、关键账号与证据样本。</p>
      </div>

      <template v-else-if="detail">
        <div class="topic-meta-block reveal">
          <div class="t-head">
            <h2 class="t-title">{{ detail.topic.title || '（无标题）' }}</h2>
            <div class="t-score" :class="LEVEL_CLASS[detail.topic.risk_level]">
              <strong>{{ detail.topic.risk_score.toFixed(1) }}</strong>
              <small>{{ LEVEL_LABEL[detail.topic.risk_level] ?? detail.topic.risk_level }}</small>
            </div>
          </div>
          <p v-if="detail.topic.lead" class="t-lead">{{ detail.topic.lead }}</p>
          <div class="t-stats">
            <div><span>样本</span><strong>{{ formatLargeNumber(detail.topic.sample_count) }}</strong></div>
            <div><span>负面率</span><strong>{{ (detail.topic.negative_ratio * 100).toFixed(1) }}%</strong></div>
            <div><span>互动总量</span><strong>{{ formatLargeNumber(detail.topic.latest_interactions) }}</strong></div>
            <div><span>互动增长</span><strong>{{ detail.topic.interaction_growth_label }}</strong></div>
            <div><span>主导情绪</span><strong>{{ detail.topic.dominant_emotion }}</strong></div>
            <div><span>KOL 入口</span><strong>{{ detail.topic.kol_entry_count }}</strong></div>
          </div>
        </div>

        <AiInsightCard :range="range" :topic-id="selectedId" title="AI 话题研判" />

        <div class="risk-bars-block reveal">
          <h3 class="block-title"><span class="eyebrow">RISK / FACTORS</span>风险因子拆解</h3>
          <RiskFactorBars :meta="detail.topic" />
        </div>

        <div class="charts-grid reveal">
          <div class="chart-card">
            <h3 class="block-title"><span class="eyebrow">EMOTION / DIST</span>情绪结构</h3>
            <TopicEmotionPie :counts="detail.emotion_distribution.counts" />
          </div>
          <div class="chart-card">
            <h3 class="block-title"><span class="eyebrow">EMOTION / TIMELINE</span>情绪趋势</h3>
            <EmotionTrendChart :data="detail.timeline" :height="220" />
          </div>
          <div class="chart-card">
            <h3 class="block-title"><span class="eyebrow">ENGAGEMENT</span>互动曲线（平台快照）</h3>
            <TopicEngagementChart :data="detail.engagement_curve" />
          </div>
          <div class="chart-card">
            <h3 class="block-title"><span class="eyebrow">DISCOVERY / SOURCE</span>入口结构</h3>
            <TopicSourceMix :counts="detail.source_counts" />
          </div>
        </div>

        <div class="actor-block reveal">
          <h3 class="block-title"><span class="eyebrow">KOL × EMOTION</span>影响力 × 负面率</h3>
          <div class="scatter-card">
            <InfluenceScatter
              :data="scatter"
              :height="400"
              :reference-y="detail.topic.negative_ratio"
              reference-label="话题整体负面率"
            />
          </div>
          <p class="scatter-hint">
            横轴 = 该账号在<strong>本话题内</strong>的影响力分；纵轴 = 在本话题样本里的负面率；点尺寸 = 互动量；颜色 = 主导情绪。
            琥珀虚线 = 本话题整体负面率，<strong>大圈在线上方</strong> → KOL 比一般用户更负面，可能在带节奏；<strong>大圈在线下方</strong> → KOL 较克制，话题负面由普通用户驱动。
          </p>
        </div>

        <div class="actor-block reveal">
          <h3 class="block-title"><span class="eyebrow">ACTORS / TOP</span>关键账号</h3>
          <ActorList :actors="detail.top_actors" :range="range" :topic-id="selectedId" />
        </div>

        <div class="evidence-section reveal">
          <h3 class="block-title"><span class="eyebrow">EVIDENCE / SAMPLES</span>证据样本</h3>
          <EvidenceList :range="range" :topic-id="selectedId" />
        </div>
      </template>

      <p v-else-if="loadingDetail" class="loading">加载中…</p>
      <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
    </article>
  </section>
</template>

<style scoped>
.page-head {
  display: flex; justify-content: space-between; align-items: end;
  padding: 56px var(--shell-pad-x) 36px;
  gap: 32px; flex-wrap: wrap;
}
.page-eyebrow {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--accent);
  display: flex; align-items: center; gap: 14px;
}
.page-eyebrow::before { content: ''; width: 40px; height: 1px; background: var(--accent); }
.page-title {
  font-family: var(--serif-cn); font-weight: 900;
  font-size: clamp(40px, 5vw, 64px);
  line-height: 0.96; letter-spacing: -0.04em; color: var(--ink);
  margin-top: 24px;
}
.page-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  font-variation-settings: "SOFT" 100, "opsz" 144;
  color: var(--accent);
}
.page-lead {
  margin-top: 22px; max-width: 560px;
  color: var(--ink-2); font-size: 14px; line-height: 1.85;
}
.page-meta { padding-bottom: 6px; }

.topic-grid {
  display: grid;
  grid-template-columns: minmax(320px, 380px) 1fr;
  border-top: 1px solid var(--line);
}
.master {
  border-right: 1px solid var(--line);
  padding: 28px var(--shell-pad-x) 60px 0;
  margin-left: var(--shell-pad-x);
  position: sticky; top: 32px;
  align-self: start;
  max-height: calc(100vh - 60px);
  overflow-y: auto;
}
.master-head {
  display: flex; justify-content: space-between; align-items: end;
  margin-bottom: 20px; padding-right: 12px;
}
.master-head .count {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.master-list { display: grid; gap: 8px; padding-right: 12px; }
.master-item {
  display: grid; gap: 8px;
  padding: 14px 12px;
  border: 1px solid var(--line);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}
.master-item:hover { background: rgba(245,195,74,0.025); border-color: var(--line-2); }
.master-item.active {
  border-color: var(--accent);
  background: rgba(245,195,74,0.06);
}
.m-head { display: flex; justify-content: space-between; align-items: baseline; }
.m-num {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.18em; color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.m-score {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 0;
  font-size: 22px; font-weight: 400; line-height: 1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.m-score.high { color: var(--alert); }
.m-score.medium { color: var(--accent); }
.m-score.low { color: var(--muted); }
.m-title {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 14px; color: var(--ink);
  line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.m-meta {
  display: flex; gap: 12px;
  font-family: var(--mono); font-size: 10px;
  color: var(--muted); letter-spacing: 0.04em;
}
.m-stack { display: flex; height: 4px; gap: 1px; }
.m-stack span { display: block; height: 100%; }

.detail {
  padding: 32px var(--shell-pad-x) 80px;
  display: grid; gap: 40px;
  min-width: 0;
}

.placeholder {
  padding: 80px 0;
  display: grid; gap: 18px;
  max-width: 480px;
}
.ph-title {
  font-family: var(--serif-cn); font-weight: 800;
  font-size: clamp(32px, 4vw, 48px);
  line-height: 1.1; letter-spacing: -0.03em;
  color: var(--ink); margin-top: 14px;
}
.ph-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  color: var(--accent);
}
.ph-lead { color: var(--ink-2); font-size: 14px; line-height: 1.85; }

.topic-meta-block { display: grid; gap: 18px; }
.t-head { display: flex; justify-content: space-between; align-items: end; gap: 24px; }
.t-title {
  font-family: var(--serif-cn); font-weight: 800;
  font-size: clamp(28px, 3vw, 40px);
  line-height: 1.15; letter-spacing: -0.02em; color: var(--ink);
  flex: 1;
}
.t-score { text-align: right; }
.t-score strong {
  display: block;
  font-family: var(--serif);
  font-variation-settings: "SOFT" 0;
  font-size: 56px; font-weight: 400; line-height: 1; letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}
.t-score.high strong { color: var(--alert); }
.t-score.medium strong { color: var(--accent); }
.t-score.low strong { color: var(--muted); }
.t-score small {
  display: block; margin-top: 8px;
  font-family: var(--mono); font-size: 9px;
  letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted);
}
.t-lead { color: var(--ink-2); font-size: 14px; line-height: 1.8; max-width: 720px; }
.t-stats {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.t-stats > div {
  padding: 16px 18px;
  border-right: 1px solid var(--line);
}
.t-stats > div:last-child { border-right: 0; }
.t-stats span {
  display: block;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted);
  margin-bottom: 8px;
}
.t-stats strong {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 30;
  font-size: 22px; font-weight: 400; color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.block-title {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 18px; color: var(--ink);
  margin-bottom: 18px;
  display: flex; align-items: baseline; gap: 14px;
}
.block-title .eyebrow {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted);
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}
.chart-card {
  border: 1px solid var(--line);
  padding: 22px 18px 14px;
  background: rgba(255,255,255,0.012);
}

.scatter-card {
  border: 1px solid var(--line);
  padding: 18px 14px 6px;
  background: rgba(255,255,255,0.012);
}
.scatter-hint {
  margin-top: 14px;
  font-size: 12px; line-height: 1.85;
  color: var(--muted);
  max-width: 760px;
}
.scatter-hint strong { color: var(--ink-2); font-weight: 500; }

.loading, .error { font-family: var(--mono); font-size: 12px; padding: 40px 0; }
.error { color: var(--alert); }
.empty { color: var(--muted); font-family: var(--mono); font-size: 12px; padding: 20px 0; }

@media (max-width: 1100px) {
  .topic-grid { grid-template-columns: 1fr; }
  .master {
    border-right: 0; border-bottom: 1px solid var(--line);
    margin-left: 0; padding: 28px var(--shell-pad-x);
    position: static; max-height: none;
  }
  .charts-grid { grid-template-columns: 1fr; }
  .t-stats { grid-template-columns: repeat(2, 1fr); }
  .t-stats > div:nth-child(2n) { border-right: 0; }
}
</style>
