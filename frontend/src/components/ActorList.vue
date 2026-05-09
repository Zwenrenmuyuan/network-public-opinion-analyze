<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import type { Actor, EvidenceSample, RangeKey } from '@/types/api'
import { EMOTION_COLORS } from '@/api/echarts-theme'
import { formatDate, formatLargeNumber } from '@/utils/format'

const props = defineProps<{
  actors: Actor[]
  range: RangeKey
  topicId?: string | null
  compact?: boolean
}>()

const ROLE_LABEL: Record<string, string> = {
  entry_kol: '入口 KOL',
  verified_actor: '认证',
  high_follower_actor: '高粉',
  high_interaction: '高互动',
  negative_polarized: '负面极化',
  active_voice: '活跃发言',
  cross_topic: '跨话题',
  ordinary_actor: '普通',
}

const expandedId = ref<string | null>(null)
const samplesByActor = ref<Record<string, EvidenceSample[]>>({})
const loadingActor = ref<string | null>(null)
const errorByActor = ref<Record<string, string>>({})

async function toggle(a: Actor) {
  if (expandedId.value === a.actor_id) {
    expandedId.value = null
    return
  }
  expandedId.value = a.actor_id
  if (samplesByActor.value[a.actor_id] || !a.evidence_token) return
  loadingActor.value = a.actor_id
  errorByActor.value = { ...errorByActor.value, [a.actor_id]: '' }
  try {
    const r = await api.evidence({
      range: props.range,
      topicId: props.topicId,
      actorId: a.evidence_token,
      limit: 3,
    })
    samplesByActor.value = { ...samplesByActor.value, [a.actor_id]: r.samples }
  } catch (e) {
    errorByActor.value = { ...errorByActor.value, [a.actor_id]: (e as Error).message }
  } finally {
    loadingActor.value = null
  }
}
</script>

<template>
  <div class="actor-list" :class="{ compact }">
    <article v-for="a in actors" :key="a.actor_id" class="actor" :class="{ expanded: expandedId === a.actor_id }">
      <button class="actor-head-btn" @click="toggle(a)" :aria-expanded="expandedId === a.actor_id">
        <div class="head">
          <strong class="name">{{ a.display_name }}</strong>
          <span class="influence">影响力 {{ a.actor_influence_score.toFixed(0) }}</span>
        </div>
        <div class="meta">
          <span>互动 {{ formatLargeNumber(a.interaction_count) }}</span>
          <span>样本 {{ a.sample_count }}</span>
          <span>负面率 {{ (a.negative_ratio * 100).toFixed(0) }}%</span>
          <span class="follower">{{ a.followers_bucket }}</span>
        </div>
        <div class="chips">
          <span class="chip emo" :style="{ background: EMOTION_COLORS[a.dominant_emotion], color: '#0a0c10' }">
            {{ a.dominant_emotion }}
          </span>
          <span v-for="r in a.roles" :key="r" class="chip">{{ ROLE_LABEL[r] ?? r }}</span>
          <span class="expand-cue">{{ expandedId === a.actor_id ? '收起 ▾' : '查看代表样本 ▸' }}</span>
        </div>
      </button>

      <div v-if="expandedId === a.actor_id" class="expanded-panel">
        <p v-if="loadingActor === a.actor_id" class="muted">加载中…</p>
        <p v-else-if="errorByActor[a.actor_id]" class="error">加载失败：{{ errorByActor[a.actor_id] }}</p>
        <template v-else>
          <article v-for="s in (samplesByActor[a.actor_id] || [])" :key="s.sample_id" class="sub-sample">
            <p class="sub-text">{{ s.content }}</p>
            <div class="sub-meta">
              <span class="chip emo" :style="{ background: EMOTION_COLORS[s.pred_label], color: '#0a0c10' }">
                {{ s.pred_label }} · {{ (s.confidence * 100).toFixed(0) }}%
              </span>
              <span v-if="s.source === 'comment'" class="chip warn">采样评论</span>
              <span class="chip">互动 {{ s.interaction_count }}</span>
              <time class="ts">{{ formatDate(s.created_at) }}</time>
            </div>
          </article>
          <p v-if="(samplesByActor[a.actor_id] || []).length === 0" class="muted">本窗口下该账号暂无可展示的代表样本</p>
        </template>
      </div>
    </article>
    <p v-if="!actors.length" class="empty">本窗口暂无关键账号</p>
  </div>
</template>

<style scoped>
.actor-list { display: grid; gap: 12px; }
.actor-list.compact { gap: 8px; }
.actor {
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.015);
  transition: background 0.2s, border-color 0.2s;
}
.actor:hover { border-color: var(--line-2); }
.actor.expanded { border-color: var(--accent); background: rgba(245,195,74,0.025); }

.actor-head-btn {
  display: grid; gap: 8px;
  width: 100%;
  padding: 14px 16px;
  text-align: left;
  background: transparent;
}
.head {
  display: flex; justify-content: space-between; align-items: baseline;
}
.name { font-family: var(--serif-cn); font-size: 16px; font-weight: 700; color: var(--ink); }
.influence {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.meta {
  display: flex; flex-wrap: wrap; gap: 14px;
  font-family: var(--mono); font-size: 11px;
  color: var(--muted); letter-spacing: 0.04em;
}
.meta .follower { color: var(--ink-2); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
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
.expand-cue {
  margin-left: auto;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent);
}

.expanded-panel {
  padding: 0 16px 14px;
  display: grid; gap: 10px;
  border-top: 1px solid var(--line);
  margin-top: 4px;
  padding-top: 14px;
}
.sub-sample {
  border-left: 2px solid var(--accent);
  padding: 10px 14px;
  background: rgba(255,255,255,0.02);
  display: grid; gap: 8px;
}
.sub-text {
  color: var(--ink-2);
  font-size: 13px; line-height: 1.7;
  font-family: var(--sans-cn);
}
.sub-meta {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
}
.ts {
  margin-left: auto;
  font-family: var(--mono); font-size: 10px;
  color: var(--muted); letter-spacing: 0.06em;
}

.muted, .error, .empty {
  color: var(--muted); font-family: var(--mono); font-size: 12px; padding: 4px 0;
}
.error { color: var(--alert); }
.empty { padding: 20px 0; }
</style>
