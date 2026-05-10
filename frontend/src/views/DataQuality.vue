<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import { useECharts } from '@/composables/useECharts'
import { EMOTION_COLORS, EMOTION_ORDER, baseDark } from '@/api/echarts-theme'
import type { DataQualityResponse, OverviewResponse } from '@/types/api'
import { formatDate, formatLargeNumber } from '@/utils/format'

const metaStore = useMetaStore()
const { data: meta } = storeToRefs(metaStore)

const dq = ref<DataQualityResponse | null>(null)
const overview = ref<OverviewResponse | null>(null)
const errorMsg = ref('')

const SOURCE_TABLES = [
  { layer: '内容层', tables: 'weibo.post / weibo.comment', usage: '原文、证据流、预测输入', limit: 'comment 为当前 CK 已采集评论，不代表平台全量' },
  { layer: '情绪层', tables: 'dashboard.sentiment_prediction', usage: '六分类预测、置信度、BERT 对照', limit: '查询必须过滤 model_version' },
  { layer: '热度层', tables: 'weibo.post_engagement_ts', usage: '点赞 / 评论 / 转发快照', limit: '快照稀疏，不是连续时序' },
  { layer: '话题层', tables: 'weibo.topic / weibo.post_topic', usage: '话题聚合、详情', limit: '只代表显式携带话题的帖子' },
  { layer: '传播层', tables: 'weibo.post_discovery', usage: 'hot / keyword / kol / retweet 入口', limit: '一帖可多入口，不能 count(*) 当帖子数' },
  { layer: '账号层', tables: 'weibo.user', usage: '认证、高粉、画像 tier', limit: 'followers_count 仅 profile_tier ≥ 1 可信' },
]

const tierChartEl = ref<HTMLElement | null>(null)

const tierData = computed(() => {
  if (!dq.value?.profile_tier_distribution) return []
  return Object.entries(dq.value.profile_tier_distribution)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([tier, ratio]) => ({ tier, ratio: Number(ratio) || 0 }))
})

const trustedTierRatio = computed(() => {
  return tierData.value.filter((t) => Number(t.tier) >= 1).reduce((a, t) => a + t.ratio, 0)
})

const tierOption = computed(() => ({
  ...baseDark,
  tooltip: {
    ...baseDark.tooltip,
    trigger: 'item' as const,
    formatter: (p: { name: string; value: number }) =>
      `${p.name}<br/><strong>${(p.value * 100).toFixed(2)}%</strong>`,
  },
  series: [{
    type: 'pie' as const,
    radius: ['58%', '88%'],
    avoidLabelOverlap: true,
    label: { show: false },
    labelLine: { show: false },
    itemStyle: { borderColor: '#0d1117', borderWidth: 2 },
    data: tierData.value.map((t, i) => ({
      name: `tier ${t.tier}`,
      value: t.ratio,
      itemStyle: {
        color: ['#4d5562', '#f5c34a', '#22d3a8'][i] || '#7d8694',
      },
    })),
  }],
}))

useECharts(tierChartEl, tierOption)

async function loadAll() {
  errorMsg.value = ''
  const [d, o] = await Promise.allSettled([
    api.dataQuality(),
    api.overview('all_available'),
  ])
  if (d.status === 'fulfilled') dq.value = d.value
  if (o.status === 'fulfilled') overview.value = o.value
  const failed = [d, o].filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
  if (failed.length) errorMsg.value = failed.map((f) => String(f.reason)).join(' / ')
}

onMounted(async () => {
  await metaStore.load()
  await loadAll()
})
</script>

<template>
  <section class="page-head">
    <div class="reveal">
      <p class="page-eyebrow">SECTION V / DATA QUALITY</p>
      <h1 class="page-title">数据<em>口径</em></h1>
      <p class="page-lead">这是研判工作台的数据来源、时间窗口、模型版本与采样口径声明。任何指标都应在该口径下解读。</p>
    </div>
    <div class="page-meta reveal" v-if="meta">
      <div class="meta-line"><span class="meta-label">主模型</span><strong>{{ meta.model.name }}</strong></div>
      <div class="meta-line"><span class="meta-label">checkpoint</span><code>{{ meta.model.checkpoint }}</code></div>
    </div>
  </section>

  <section class="window-section reveal" v-if="meta">
    <div class="section-head">
      <div>
        <p class="eyebrow">TIME / WINDOW</p>
        <h2 class="section-title">时间窗口<em>data window</em></h2>
      </div>
    </div>
    <div class="kv-grid">
      <div><span>稳定起点（CST）</span><strong>{{ formatDate(meta.data_window.start) }}</strong></div>
      <div><span>窗口结束</span><strong>{{ formatDate(meta.data_window.end) }}</strong></div>
      <div><span>可用天数</span><strong>{{ meta.data_window.available_days }} 天</strong></div>
      <div><span>历史是否较短</span><strong>{{ meta.data_window.is_partial_history ? '是（< 30 天）' : '否' }}</strong></div>
      <div v-if="overview"><span>帖子数</span><strong>{{ formatLargeNumber(overview.post_count) }}</strong></div>
      <div v-if="overview"><span>采集评论数</span><strong>{{ formatLargeNumber(overview.sampled_comment_count) }}</strong></div>
      <div v-if="overview"><span>累计互动（快照）</span><strong>{{ formatLargeNumber(overview.latest_interactions) }}</strong></div>
      <div v-if="overview"><span>活跃话题</span><strong>{{ formatLargeNumber(overview.active_topic_count) }}</strong></div>
    </div>
  </section>

  <section class="sources-section reveal">
    <div class="section-head">
      <div>
        <p class="eyebrow">SOURCES / 6 LAYERS</p>
        <h2 class="section-title">数据来源<em>six layers</em></h2>
      </div>
    </div>
    <table class="src-table">
      <thead>
        <tr><th>层</th><th>表</th><th>用途</th><th>口径限制</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in SOURCE_TABLES" :key="t.layer">
          <td class="layer">{{ t.layer }}</td>
          <td><code>{{ t.tables }}</code></td>
          <td>{{ t.usage }}</td>
          <td class="limit">{{ t.limit }}</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section class="labels-section reveal" v-if="meta">
    <div class="section-head">
      <div>
        <p class="eyebrow">LABELS / SCHEMA</p>
        <h2 class="section-title">情绪标签<em>label schema</em></h2>
      </div>
    </div>
    <div class="labels-row">
      <div v-for="(label, idx) in EMOTION_ORDER" :key="label" class="label-cell"
           :class="{ negative: meta.negative_labels.includes(label) }">
        <span class="lid">{{ idx }}</span>
        <span class="lblock" :style="{ background: EMOTION_COLORS[label] }"></span>
        <span class="lname">{{ label }}</span>
        <span v-if="meta.negative_labels.includes(label)" class="ltag">负面</span>
      </div>
    </div>
    <p class="hint">
      负面 = 愤怒 + 悲伤 + 恐惧。模型 logits / <code>label_id</code> 顺序与上方一致。
      跨数据集统一使用同一 <code>LABELS_ZH</code> 定义（<code>src/npo/config.py</code>）。
    </p>
  </section>

  <section class="tier-section reveal" v-if="dq">
    <div class="section-head">
      <div>
        <p class="eyebrow">USER / PROFILE TIER</p>
        <h2 class="section-title">画像覆盖<em>profile_tier</em></h2>
      </div>
      <div class="tier-trust">
        <span>tier ≥ 1 可信占比</span>
        <strong>{{ (trustedTierRatio * 100).toFixed(1) }}%</strong>
      </div>
    </div>
    <div class="tier-grid">
      <div ref="tierChartEl" class="tier-chart"></div>
      <div class="tier-legend">
        <div v-for="t in tierData" :key="t.tier" class="t-row">
          <span class="t-name">tier {{ t.tier }}</span>
          <div class="t-bar"><div class="t-fill" :style="{ width: (t.ratio * 100) + '%' }"></div></div>
          <span class="t-val">{{ (t.ratio * 100).toFixed(2) }}%</span>
        </div>
        <p class="hint">{{ dq.user_tier_notice }}</p>
      </div>
    </div>
  </section>

  <section class="notices-section reveal" v-if="dq">
    <div class="section-head">
      <div>
        <p class="eyebrow">NOTICES / KEY</p>
        <h2 class="section-title">关键口径警告<em>caveats</em></h2>
      </div>
    </div>
    <ul class="notices">
      <li>{{ dq.history_window_notice }}</li>
      <li>{{ dq.comment_sampling_notice }}</li>
      <li>{{ dq.emotion_sample_notice }}</li>
      <li>{{ dq.engagement_notice }}</li>
      <li>{{ dq.risk_score_notice }}</li>
      <li>{{ dq.risk_factor_notice }}</li>
      <li>{{ dq.post_discovery_notice }}</li>
      <li>{{ dq.timezone_notice }}</li>
    </ul>
  </section>

  <p v-if="errorMsg" class="error-line">部分接口加载失败：{{ errorMsg }}</p>
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
  line-height: 0.96; letter-spacing: -0.04em; color: var(--ink); margin-top: 24px;
}
.page-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  font-variation-settings: "SOFT" 100, "opsz" 144;
  color: var(--accent);
}
.page-lead {
  margin-top: 22px; max-width: 640px;
  color: var(--ink-2); font-size: 14px; line-height: 1.85;
}
.page-meta {
  display: grid; gap: 10px;
  font-family: var(--mono); font-size: 11px; text-align: right;
}
.meta-line { display: flex; gap: 12px; align-items: baseline; justify-content: flex-end; }
.meta-label { color: var(--muted); letter-spacing: 0.16em; text-transform: uppercase; font-size: 10px; }
.meta-line strong { color: var(--ink); font-weight: 500; }
.meta-line code { color: var(--accent); background: rgba(245,195,74,0.08); padding: 2px 6px; font-size: 10px; }

.window-section,
.sources-section,
.labels-section,
.tier-section,
.notices-section {
  padding: 40px var(--shell-pad-x);
  border-top: 1px solid var(--line);
}

.section-head {
  display: flex; justify-content: space-between; align-items: end;
  margin-bottom: 28px;
  flex-wrap: wrap; gap: 16px;
}
.section-title {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 28px; letter-spacing: -0.02em; color: var(--ink);
}
.section-title em {
  font-family: var(--serif); font-style: italic; font-weight: 300;
  color: var(--muted); margin-left: 14px; font-size: 0.55em;
  letter-spacing: 0.02em; vertical-align: middle;
}

.kv-grid {
  display: grid; grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.kv-grid > div {
  padding: 18px 22px; border-right: 1px solid var(--line);
}
.kv-grid > div:nth-child(4n) { border-right: 0; }
.kv-grid > div:nth-child(n+5) { border-top: 1px solid var(--line); }
.kv-grid span {
  display: block;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted);
  margin-bottom: 8px;
}
.kv-grid strong {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 30;
  font-size: 22px; font-weight: 400; color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.src-table {
  width: 100%; border-collapse: collapse;
  font-family: var(--sans-cn); font-size: 13px;
}
.src-table th {
  text-align: left;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted);
  padding: 12px 14px;
  border-bottom: 1px solid var(--line-2);
  font-weight: 500;
}
.src-table td {
  padding: 16px 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  color: var(--ink-2);
}
.src-table .layer {
  font-family: var(--serif-cn); font-weight: 700; color: var(--ink);
  font-size: 14px;
}
.src-table .limit {
  color: var(--muted); font-size: 12px; line-height: 1.6;
}
.src-table code {
  font-family: var(--mono); font-size: 11px;
  color: var(--accent);
  background: rgba(245,195,74,0.08);
  padding: 2px 6px;
}

.labels-row {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 14px;
}
.label-cell {
  display: flex; align-items: center; gap: 10px;
  padding: 16px 14px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.012);
}
.label-cell.negative { border-color: rgba(255,77,82,0.3); }
.lid {
  font-family: var(--mono); font-size: 11px;
  color: var(--muted); letter-spacing: 0.06em;
}
.lblock { width: 14px; height: 14px; border-radius: 2px; flex: 0 0 auto; }
.lname {
  font-family: var(--serif-cn); font-size: 16px; font-weight: 700; color: var(--ink);
}
.ltag {
  margin-left: auto;
  font-family: var(--mono); font-size: 9px;
  letter-spacing: 0.2em; text-transform: uppercase;
  color: var(--alert);
}

.hint {
  margin-top: 16px;
  font-family: var(--sans-cn); font-size: 13px;
  color: var(--muted); line-height: 1.85;
}
.hint code {
  font-family: var(--mono); font-size: 11px; color: var(--accent);
  background: rgba(245,195,74,0.08); padding: 2px 6px;
}

.tier-trust {
  display: flex; align-items: baseline; gap: 10px;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
  letter-spacing: 0.04em;
}
.tier-trust strong {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 50, "opsz" 144;
  font-size: 36px; font-weight: 400; color: var(--positive);
  font-variant-numeric: tabular-nums;
}

.tier-grid {
  display: grid; grid-template-columns: 280px 1fr; gap: 32px;
  align-items: center;
}
.tier-chart { width: 280px; height: 260px; }
.tier-legend { display: grid; gap: 10px; }
.t-row {
  display: grid; grid-template-columns: 70px 1fr 64px;
  gap: 14px; align-items: center;
}
.t-name {
  font-family: var(--mono); font-size: 11px;
  color: var(--ink-2); letter-spacing: 0.06em;
}
.t-bar { height: 8px; background: rgba(255,255,255,0.04); overflow: hidden; }
.t-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--positive)); transition: width 0.6s; }
.t-val {
  text-align: right;
  font-family: var(--mono); font-size: 11px;
  color: var(--ink); font-variant-numeric: tabular-nums;
}

.notices {
  list-style: none; padding: 0;
  display: grid; gap: 14px;
}
.notices li {
  padding: 16px 22px;
  border-left: 3px solid var(--accent);
  background: rgba(245,195,74,0.04);
  font-family: var(--sans-cn); font-size: 14px; line-height: 1.8;
  color: var(--ink-2);
}

.error-line {
  padding: 16px var(--shell-pad-x);
  color: var(--alert); font-family: var(--mono); font-size: 12px;
}

@media (max-width: 1100px) {
  .page-head { flex-direction: column; align-items: flex-start; }
  .page-meta { text-align: left; }
  .meta-line { justify-content: flex-start; }
  .kv-grid { grid-template-columns: repeat(2, 1fr); }
  .kv-grid > div:nth-child(4n) { border-right: 1px solid var(--line); }
  .kv-grid > div:nth-child(2n) { border-right: 0; }
  .labels-row { grid-template-columns: repeat(2, 1fr); }
  .tier-grid { grid-template-columns: 1fr; }
  .tier-chart { margin: 0 auto; }
}
</style>
