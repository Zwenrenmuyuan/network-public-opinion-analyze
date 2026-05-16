<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { InsightResponse, RangeKey } from '@/types/api'
import { formatDate } from '@/utils/format'

const props = withDefaults(defineProps<{
  range: RangeKey
  topicId?: string | null
  title?: string
}>(), {
  topicId: null,
  title: 'AI 辅助研判',
})

const insight = ref<InsightResponse | null>(null)
const loading = ref(false)
const error = ref('')

const scopeLabel = computed(() => (props.topicId ? '话题研判' : '总览研判'))

async function generate() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    insight.value = await api.insights(props.range, props.topicId)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(() => [props.range, props.topicId] as const, () => {
  insight.value = null
  error.value = ''
})
</script>

<template>
  <section class="ai-card">
    <div class="ai-head">
      <div>
        <p class="eyebrow">LLM / INSIGHT</p>
        <h2 class="ai-title">{{ title }} <em>{{ scopeLabel }}</em></h2>
      </div>
      <button class="generate-btn" :disabled="loading" @click="generate">
        {{ loading ? '生成中...' : insight ? '重新获取' : '生成研判' }}
      </button>
    </div>

    <p class="ai-note">由大语言模型基于结构化指标和 Top 证据样本生成，仅供辅助研判；情绪标签和风险分仍以后端模型与规则为准。</p>

    <p v-if="error" class="error">生成失败：{{ error }}</p>

    <div v-if="insight" class="insight-body">
      <div class="summary-block">
        <span class="label">摘要</span>
        <p>{{ insight.summary }}</p>
      </div>

      <div class="insight-grid">
        <div v-if="insight.key_findings.length" class="panel">
          <h3>关键发现</h3>
          <ul>
            <li v-for="item in insight.key_findings" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div v-if="insight.risk_drivers.length" class="panel">
          <h3>风险驱动</h3>
          <ul>
            <li v-for="item in insight.risk_drivers" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div v-if="insight.actor_insights.length" class="panel">
          <h3>账号观察</h3>
          <ul>
            <li v-for="item in insight.actor_insights" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div v-if="insight.recommended_actions.length" class="panel">
          <h3>建议动作</h3>
          <ul>
            <li v-for="item in insight.recommended_actions" :key="item">{{ item }}</li>
          </ul>
        </div>
      </div>

      <div class="foot-row">
        <span>模型 {{ insight.llm_model }}</span>
        <span>{{ formatDate(insight.generated_at) }}</span>
        <span v-if="insight.evidence_refs.length">证据 {{ insight.evidence_refs.join(' / ') }}</span>
      </div>

      <div v-if="insight.caveats.length" class="caveats">
        <span>口径限制</span>
        <p>{{ insight.caveats.join('；') }}</p>
      </div>
    </div>

    <div v-else-if="!error" class="empty-state">
      点击生成当前{{ scopeLabel }}，系统会汇总风险话题、关键账号、证据样本和数据口径限制。
    </div>
  </section>
</template>

<style scoped>
.ai-card {
  margin: 48px var(--shell-pad-x) 0;
  padding: 26px;
  border: 1px solid rgba(245,195,74,0.28);
  background:
    radial-gradient(circle at 0 0, rgba(245,195,74,0.12), transparent 34%),
    rgba(255,255,255,0.018);
}
.ai-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}
.ai-title {
  margin-top: 10px;
  font-family: var(--serif-cn);
  font-size: 26px;
  line-height: 1.15;
  color: var(--ink);
  letter-spacing: -0.02em;
}
.ai-title em {
  margin-left: 12px;
  font-family: var(--serif);
  font-style: italic;
  font-weight: 300;
  color: var(--accent);
  font-size: 0.62em;
}
.generate-btn {
  padding: 10px 14px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  transition: background 0.2s, color 0.2s;
  white-space: nowrap;
}
.generate-btn:hover:not(:disabled) {
  background: var(--accent);
  color: #0a0c10;
}
.generate-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}
.ai-note {
  margin-top: 14px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
}
.error {
  margin-top: 18px;
  color: var(--alert);
  font-family: var(--mono);
  font-size: 12px;
}
.insight-body {
  margin-top: 22px;
  display: grid;
  gap: 18px;
}
.summary-block {
  display: grid;
  gap: 8px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.summary-block .label,
.caveats span {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  color: var(--accent);
  text-transform: uppercase;
}
.summary-block p {
  color: var(--ink);
  font-family: var(--serif-cn);
  font-size: 20px;
  line-height: 1.65;
}
.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.panel {
  padding: 16px;
  border: 1px solid var(--line);
  background: rgba(0,0,0,0.12);
}
.panel h3 {
  margin-bottom: 10px;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  color: var(--muted);
  text-transform: uppercase;
}
.panel ul {
  display: grid;
  gap: 8px;
  padding-left: 16px;
  color: var(--ink-2);
  font-size: 13px;
  line-height: 1.75;
}
.foot-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
}
.caveats {
  display: grid;
  gap: 8px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
}
.caveats p,
.empty-state {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
}
.empty-state { margin-top: 18px; }
@media (max-width: 900px) {
  .ai-card { padding: 20px; }
  .ai-head { flex-direction: column; }
  .insight-grid { grid-template-columns: 1fr; }
}
</style>
