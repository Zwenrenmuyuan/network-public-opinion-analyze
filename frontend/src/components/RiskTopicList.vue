<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { RiskTopic } from '@/types/api'
import { EMOTION_COLORS, EMOTION_ORDER } from '@/api/echarts-theme'
import { formatLargeNumber } from '@/utils/format'

defineProps<{ topics: RiskTopic[] }>()
const router = useRouter()

const LEVEL_LABEL: Record<string, string> = {
  high: '高风险', medium_high: '中高风险', medium: '中风险', low: '低风险',
}
const LEVEL_CLASS: Record<string, string> = {
  high: 'high', medium_high: 'high', medium: 'medium', low: 'low',
}

function stack(t: RiskTopic): { color: string; pct: number }[] {
  const total = EMOTION_ORDER.reduce((a, l) => a + (t.emotion_counts[l] || 0), 0)
  if (!total) return []
  return EMOTION_ORDER.map((l) => ({
    color: EMOTION_COLORS[l],
    pct: (t.emotion_counts[l] || 0) / total * 100,
  })).filter((x) => x.pct > 0)
}

function topFactor(t: RiskTopic): string {
  const entries = Object.entries(t.risk_factors).sort(([, a], [, b]) => Number(b) - Number(a))
  const [key] = entries[0] ?? ['']
  return t.risk_factor_labels?.[key] ?? '风险因子'
}

function open(t: RiskTopic) {
  router.push(`/topics/${t.topic_id}`)
}
</script>

<template>
  <div class="risk-list">
    <article
      v-for="(t, i) in topics" :key="t.topic_id"
      class="risk-item reveal"
      :style="{ animationDelay: `${0.1 + i * 0.05}s` }"
      @click="open(t)"
    >
      <div class="risk-num">{{ String(i + 1).padStart(2, '0') }}</div>
      <div class="risk-body">
        <div class="risk-tag"># {{ t.dominant_emotion }} · {{ topFactor(t) }}</div>
        <div class="risk-title">{{ t.title || '（无标题）' }}</div>
        <div class="risk-meta">
          <span>负面率 <b>{{ (t.negative_ratio * 100).toFixed(1) }}%</b></span>
          <span>样本 <b>{{ formatLargeNumber(t.sample_count) }}</b></span>
          <span>互动 <b>{{ t.interaction_growth_label }}</b></span>
        </div>
        <div class="risk-stack">
          <span v-for="(s, j) in stack(t)" :key="j" :style="{ background: s.color, width: s.pct + '%' }"></span>
        </div>
      </div>
      <div class="risk-score">
        <div class="v" :class="LEVEL_CLASS[t.risk_level]">{{ t.risk_score.toFixed(1) }}</div>
        <div class="lvl">{{ LEVEL_LABEL[t.risk_level] ?? t.risk_level }}</div>
      </div>
    </article>
    <p v-if="!topics.length" class="empty">本窗口暂无风险话题</p>
  </div>
</template>

<style scoped>
.risk-list { display: grid; }
.risk-item {
  display: grid;
  grid-template-columns: 60px 1fr auto;
  gap: 28px;
  padding: 22px 0;
  border-top: 1px solid var(--line);
  align-items: center;
  cursor: pointer;
  transition: background 0.3s, padding 0.3s;
}
.risk-item:hover { background: rgba(245,195,74,0.02); padding-left: 8px; padding-right: 8px; }
.risk-item:last-child { border-bottom: 1px solid var(--line); }

.risk-num {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 30;
  font-size: 38px; font-weight: 300;
  color: var(--muted-2);
  font-variant-numeric: tabular-nums;
}
.risk-body { min-width: 0; }
.risk-tag {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--accent);
  margin-bottom: 6px;
  text-transform: uppercase;
}
.risk-title {
  font-family: var(--serif-cn); font-weight: 700;
  font-size: 20px; letter-spacing: -0.01em;
  color: var(--ink);
  margin-bottom: 10px; line-height: 1.4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.risk-meta {
  font-family: var(--mono); font-size: 11px;
  color: var(--muted); letter-spacing: 0.04em;
  display: flex; gap: 18px; flex-wrap: wrap;
}
.risk-meta b { color: var(--ink-2); font-weight: 500; }
.risk-stack {
  display: flex; height: 6px; max-width: 280px; gap: 1px; margin-top: 12px;
}
.risk-stack span { display: block; height: 100%; }
.risk-score { text-align: right; min-width: 90px; }
.risk-score .v {
  font-family: var(--serif);
  font-variation-settings: "SOFT" 0;
  font-size: 56px; font-weight: 400;
  line-height: 1; letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}
.risk-score .v.high { color: var(--alert); }
.risk-score .v.medium { color: var(--accent); }
.risk-score .v.low { color: var(--muted); }
.risk-score .lvl {
  font-family: var(--mono); font-size: 9px;
  letter-spacing: 0.2em; text-transform: uppercase;
  margin-top: 8px; color: var(--muted);
}
.empty {
  color: var(--muted); padding: 22px 0;
  font-family: var(--mono); font-size: 12px;
}
</style>
