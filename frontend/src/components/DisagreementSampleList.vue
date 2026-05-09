<script setup lang="ts">
import type { DisagreementSample } from '@/types/api'
import { EMOTION_COLORS } from '@/api/echarts-theme'
import { formatDate } from '@/utils/format'

defineProps<{ samples: DisagreementSample[] }>()
</script>

<template>
  <div class="dis-list">
    <article v-for="s in samples" :key="`${s.source}-${s.source_id}`" class="dis-item">
      <p class="text">{{ s.content }}</p>
      <div class="labels">
        <div class="label-cell ernie">
          <span class="who">ERNIE</span>
          <span class="lbl" :style="{ background: EMOTION_COLORS[s.ernie_label], color: '#0a0c10' }">{{ s.ernie_label }}</span>
          <span class="conf">{{ s.ernie_confidence != null ? (s.ernie_confidence * 100).toFixed(0) + '%' : '—' }}</span>
        </div>
        <div class="vs">≠</div>
        <div class="label-cell bert">
          <span class="who">BERT</span>
          <span class="lbl" :style="{ background: EMOTION_COLORS[s.bert_label], color: '#0a0c10' }">{{ s.bert_label }}</span>
          <span class="conf">{{ s.bert_confidence != null ? (s.bert_confidence * 100).toFixed(0) + '%' : '—' }}</span>
        </div>
        <div class="meta">
          <span v-if="s.source === 'comment'" class="chip warn">采集评论</span>
          <span v-else class="chip">原帖</span>
          <time class="ts">{{ formatDate(s.created_at) }}</time>
        </div>
      </div>
    </article>
    <p v-if="!samples.length" class="empty">暂无高置信分歧样本</p>
  </div>
</template>

<style scoped>
.dis-list { display: grid; gap: 12px; }
.dis-item {
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.015);
  padding: 16px 18px;
  display: grid; gap: 14px;
}
.text {
  color: var(--ink);
  font-size: 14px; line-height: 1.7;
  font-family: var(--sans-cn);
}
.labels {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
}
.label-cell {
  display: flex; align-items: center; gap: 8px;
}
.who {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; color: var(--muted);
}
.lbl {
  font-family: var(--mono); font-size: 11px;
  font-weight: 700; padding: 4px 10px;
  letter-spacing: 0.04em;
}
.conf {
  font-family: var(--mono); font-size: 11px;
  color: var(--ink-2); font-variant-numeric: tabular-nums;
}
.vs {
  font-family: var(--serif); font-size: 22px;
  color: var(--alert); font-weight: 700;
}
.meta {
  margin-left: auto;
  display: flex; align-items: center; gap: 8px;
}
.chip {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.1em; padding: 3px 8px;
  background: rgba(255,255,255,0.04);
  color: var(--muted);
  border: 1px solid var(--line);
}
.chip.warn { color: var(--alert); border-color: rgba(255,77,82,0.4); }
.ts {
  font-family: var(--mono); font-size: 10px;
  color: var(--muted); letter-spacing: 0.06em;
}
.empty {
  color: var(--muted); font-family: var(--mono); font-size: 12px; padding: 20px 0;
}
</style>
