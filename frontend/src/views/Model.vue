<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import PerClassF1Bars from '@/components/PerClassF1Bars.vue'
import EmotionHeatmap from '@/components/EmotionHeatmap.vue'
import DisagreementSampleList from '@/components/DisagreementSampleList.vue'
import type { ModelDisagreementResponse, ModelQualityResponse } from '@/types/api'
import { formatLargeNumber, formatPercent } from '@/utils/format'

const metaStore = useMetaStore()
const { data: meta } = storeToRefs(metaStore)

const quality = ref<ModelQualityResponse | null>(null)
const disagreement = ref<ModelDisagreementResponse | null>(null)
const errorMsg = ref('')

async function loadAll() {
  errorMsg.value = ''
  const [q, d] = await Promise.allSettled([
    api.modelQuality(),
    api.modelDisagreement(12),
  ])
  if (q.status === 'fulfilled') quality.value = q.value
  if (d.status === 'fulfilled') disagreement.value = d.value
  const failed = [q, d].filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
  if (failed.length) errorMsg.value = failed.map((f) => String(f.reason)).join(' / ')
}

const confusionCells = computed<[number, number, number][]>(() => {
  const matrix = quality.value?.confusion_matrix
  if (!matrix) return []
  const out: [number, number, number][] = []
  for (let i = 0; i < matrix.length; i++) {
    for (let j = 0; j < matrix[i].length; j++) {
      out.push([i, j, matrix[i][j] || 0])
    }
  }
  return out
})

const disagreementCells = computed<[number, number, number][]>(() => {
  const dis = disagreement.value
  if (!dis) return []
  const labelIdx = new Map(dis.labels.map((l, i) => [l, i]))
  return dis.matrix.map((c) => [
    labelIdx.get(c.ernie_label) ?? 0,
    labelIdx.get(c.bert_label) ?? 0,
    c.count,
  ])
})

onMounted(async () => {
  await metaStore.load()
  await loadAll()
})
</script>

<template>
  <section class="page-head">
    <div class="reveal">
      <p class="page-eyebrow">SECTION IV / MODEL</p>
      <h1 class="page-title">模型<em>可解释</em></h1>
      <p class="page-lead">主模型 ERNIE 在业务留出验证集 / SMP 测试集的指标，6×6 混淆矩阵，以及与对照模型 BERT 的一致率与高置信分歧样本。</p>
    </div>
    <div class="page-meta reveal" v-if="meta && quality">
      <div class="meta-line">
        <span class="meta-label">主模型</span>
        <strong>{{ meta.model.name }}</strong>
      </div>
      <div class="meta-line">
        <span class="meta-label">checkpoint</span>
        <code>{{ meta.model.checkpoint }}</code>
      </div>
    </div>
  </section>

  <section class="metrics-section reveal" v-if="quality">
    <div class="section-head">
      <div>
        <p class="eyebrow">METRICS / OFFLINE</p>
        <h2 class="section-title">主指标<em>offline eval</em></h2>
      </div>
    </div>
    <div class="metric-grid">
      <div class="metric-card">
        <p class="m-label">业务留出验证集 / held-out business eval</p>
        <div class="m-row" v-if="quality.business_eval">
          <div><span>accuracy</span><strong>{{ formatPercent(quality.business_eval.accuracy) }}</strong></div>
          <div><span>macro F1</span><strong>{{ formatPercent(quality.business_eval.macro_f1) }}</strong></div>
          <div><span>样本</span><strong>{{ formatLargeNumber(quality.business_eval.samples) }}</strong></div>
        </div>
        <p v-if="quality.business_eval" class="metric-hint">该集合未参与 mixed-v2 训练，用于评估业务域泛化效果。</p>
        <p v-else class="muted">无业务留出验证集报告</p>
      </div>
      <div class="metric-card">
        <p class="m-label">SMP 测试集 / smp test</p>
        <div class="m-row" v-if="quality.smp_test">
          <div><span>accuracy</span><strong>{{ formatPercent(quality.smp_test.accuracy) }}</strong></div>
          <div><span>macro F1</span><strong>{{ formatPercent(quality.smp_test.macro_f1) }}</strong></div>
          <div><span>样本</span><strong>{{ formatLargeNumber(quality.smp_test.samples) }}</strong></div>
        </div>
        <p v-else class="muted">无 SMP 测试集报告</p>
      </div>
    </div>
  </section>

  <section class="per-class-section reveal" v-if="quality && (quality.business_eval || quality.smp_test)">
    <div class="section-head">
      <div>
        <p class="eyebrow">PER-CLASS / F1</p>
        <h2 class="section-title">各类别 F1<em>held-out business vs smp</em></h2>
      </div>
      <div class="legend">
        <span><i class="solid"></i>业务留出验证集</span>
        <span><i class="dashed"></i>SMP 测试</span>
      </div>
    </div>
    <PerClassF1Bars :business="quality.business_eval" :smp="quality.smp_test" />
  </section>

  <section class="confusion-section reveal" v-if="quality?.confusion_matrix">
    <div class="section-head">
      <div>
        <p class="eyebrow">CONFUSION / 6×6</p>
        <h2 class="section-title">混淆矩阵<em>row = true · col = pred</em></h2>
      </div>
    </div>
    <div class="chart-card">
      <EmotionHeatmap
        :labels="quality.confusion_labels"
        :cells="confusionCells"
        row-name="TRUE"
        col-name="PRED"
        :height="420"
      />
    </div>
    <p class="hint" v-if="quality.top_confusions?.length">
      最易混淆 Top 3：
      <span v-for="(c, i) in quality.top_confusions" :key="i">
        <strong>{{ c.true }} → {{ c.pred }}</strong>（{{ c.count }}）<span v-if="i < quality.top_confusions.length - 1"> · </span>
      </span>
    </p>
  </section>

  <section class="disagreement-section reveal" v-if="disagreement">
    <div class="section-head">
      <div>
        <p class="eyebrow">ERNIE × BERT / DISAGREEMENT</p>
        <h2 class="section-title">双模型分歧<em>full sentiment_prediction</em></h2>
      </div>
      <div class="agree-meta">
        <span>一致率</span>
        <strong>{{ (disagreement.agreement_rate * 100).toFixed(2) }}%</strong>
        <span class="muted">({{ formatLargeNumber(disagreement.agreement_count) }} / {{ formatLargeNumber(disagreement.samples_total) }})</span>
      </div>
    </div>
    <div class="dis-grid">
      <div class="chart-card">
        <h3 class="block-sub">分歧矩阵（行 = ERNIE, 列 = BERT）</h3>
        <EmotionHeatmap
          :labels="disagreement.labels"
          :cells="disagreementCells"
          row-name="ERNIE"
          col-name="BERT"
          :height="380"
        />
      </div>
      <div>
        <h3 class="block-sub">高置信分歧样本</h3>
        <DisagreementSampleList :samples="disagreement.top_disagreements" />
      </div>
    </div>
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
  font-family: var(--mono); font-size: 11px;
  text-align: right;
}
.meta-line { display: flex; gap: 12px; align-items: baseline; justify-content: flex-end; }
.meta-label { color: var(--muted); letter-spacing: 0.16em; text-transform: uppercase; font-size: 10px; }
.meta-line strong { color: var(--ink); font-weight: 500; }
.meta-line code {
  color: var(--accent);
  background: rgba(245,195,74,0.08);
  padding: 2px 6px;
  font-size: 10px;
}

.metrics-section,
.per-class-section,
.confusion-section,
.disagreement-section {
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
  color: var(--muted); margin-left: 14px; font-size: 0.5em;
  letter-spacing: 0.02em; vertical-align: middle;
}

.metric-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
.metric-card {
  border: 1px solid var(--line);
  padding: 22px 24px;
  background: rgba(255,255,255,0.012);
}
.m-label {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 18px;
}
.m-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.m-row > div span {
  display: block;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--muted);
}
.m-row > div strong {
  display: block; margin-top: 6px;
  font-family: var(--serif);
  font-variation-settings: "SOFT" 50, "opsz" 144;
  font-size: 32px; font-weight: 400; color: var(--ink);
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.legend {
  display: flex; gap: 14px;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
}
.legend span { display: flex; align-items: center; gap: 6px; }
.legend i { width: 16px; height: 4px; display: inline-block; }
.legend i.solid { background: var(--accent); }
.legend i.dashed {
  background: repeating-linear-gradient(90deg, var(--accent) 0 4px, transparent 4px 8px);
}

.chart-card {
  border: 1px solid var(--line);
  padding: 18px;
  background: rgba(255,255,255,0.012);
}
.hint {
  margin-top: 16px;
  font-family: var(--sans-cn); font-size: 13px;
  color: var(--muted); line-height: 1.85;
}
.hint strong { color: var(--ink-2); font-weight: 500; }
.metric-hint {
  margin-top: 14px;
  font-family: var(--sans-cn); font-size: 12px;
  color: var(--muted); line-height: 1.7;
}

.agree-meta {
  display: flex; align-items: baseline; gap: 10px;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
  letter-spacing: 0.04em;
}
.agree-meta strong {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 50, "opsz" 144;
  font-size: 36px; font-weight: 400; color: var(--accent);
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.agree-meta .muted { color: var(--muted-2); }

.dis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 24px;
}
.block-sub {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted);
  margin-bottom: 16px;
}

.muted {
  font-family: var(--mono); font-size: 12px; color: var(--muted);
}
.error-line {
  padding: 16px var(--shell-pad-x);
  color: var(--alert); font-family: var(--mono); font-size: 12px;
}

@media (max-width: 1100px) {
  .page-head { flex-direction: column; align-items: flex-start; }
  .page-meta { text-align: left; }
  .meta-line { justify-content: flex-start; }
  .metric-grid { grid-template-columns: 1fr; }
  .dis-grid { grid-template-columns: 1fr; }
}
</style>
