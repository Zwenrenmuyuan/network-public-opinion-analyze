<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import type { EvidenceSample, RangeKey } from '@/types/api'
import { EMOTION_COLORS } from '@/api/echarts-theme'
import { formatDate } from '@/utils/format'

const props = defineProps<{
  range: RangeKey
  topicId?: string | null
}>()

const query = ref('')
const samples = ref<EvidenceSample[]>([])
const cursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')

async function loadFirst() {
  loading.value = true
  error.value = ''
  try {
    const r = await api.evidence({
      range: props.range,
      topicId: props.topicId,
      q: query.value,
      limit: 10,
    })
    samples.value = r.samples
    cursor.value = r.next_cursor
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!cursor.value || loading.value) return
  loading.value = true
  try {
    const r = await api.evidence({
      range: props.range,
      topicId: props.topicId,
      q: query.value,
      cursor: cursor.value,
      limit: 10,
    })
    samples.value.push(...r.samples)
    cursor.value = r.next_cursor
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function onSearch() { loadFirst() }

watch(() => [props.range, props.topicId] as const, () => loadFirst(), { immediate: true })
</script>

<template>
  <div class="evidence-block">
    <div class="search-row">
      <input
        v-model="query"
        type="search"
        class="search-input"
        placeholder="搜索关键字（回车）"
        maxlength="80"
        @keydown.enter="onSearch"
        @search="onSearch"
      />
    </div>

    <div v-if="error" class="error">加载失败：{{ error }}</div>

    <article v-for="s in samples" :key="s.sample_id" class="evidence-item">
      <p class="text">{{ s.content }}</p>
      <div class="meta">
        <span
          class="chip emo"
          :style="{ background: EMOTION_COLORS[s.pred_label], color: '#0a0c10' }"
        >{{ s.pred_label }} · {{ (s.confidence * 100).toFixed(0) }}%</span>
        <span v-if="s.source === 'comment'" class="chip warn">采集评论</span>
        <span class="chip">互动 {{ s.interaction_count }}</span>
        <span class="chip">{{ s.evidence_reason }}</span>
        <time class="ts">{{ formatDate(s.created_at) }}</time>
      </div>
    </article>

    <button v-if="cursor" class="more-btn" :disabled="loading" @click="loadMore">
      {{ loading ? '加载中…' : '加载更多' }}
    </button>
    <p v-else-if="!samples.length && !loading" class="empty">本窗口没有匹配的证据样本</p>
  </div>
</template>

<style scoped>
.evidence-block { display: grid; gap: 14px; }
.search-row { display: flex; }
.search-input {
  flex: 1;
  padding: 10px 14px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--line);
  color: var(--ink);
  font-family: var(--sans-cn);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, background 0.2s;
}
.search-input:focus { border-color: var(--accent); background: rgba(255,255,255,0.05); }
.search-input::placeholder { color: var(--muted); }

.evidence-item {
  border: 1px solid var(--line);
  padding: 16px 18px;
  background: rgba(255,255,255,0.015);
  display: grid; gap: 12px;
}
.text {
  color: var(--ink);
  font-size: 14px;
  line-height: 1.7;
  font-family: var(--sans-cn);
}
.meta {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
}
.chip {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.1em;
  padding: 3px 8px;
  background: rgba(255,255,255,0.04);
  color: var(--muted);
  border: 1px solid var(--line);
}
.chip.emo { font-weight: 700; border-color: transparent; }
.chip.warn { color: var(--alert); border-color: rgba(255,77,82,0.4); }
.ts {
  margin-left: auto;
  font-family: var(--mono); font-size: 10px;
  color: var(--muted); letter-spacing: 0.06em;
}
.more-btn {
  padding: 12px;
  border: 1px dashed var(--line-2);
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent);
  transition: background 0.2s, border-color 0.2s;
}
.more-btn:hover:not(:disabled) { background: rgba(245,195,74,0.04); border-color: var(--accent); }
.more-btn:disabled { color: var(--muted); cursor: not-allowed; }
.empty, .error {
  color: var(--muted); font-family: var(--mono); font-size: 12px; padding: 20px 0;
}
.error { color: var(--alert); }
</style>
