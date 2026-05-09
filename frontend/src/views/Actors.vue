<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import RangeTabs from '@/components/RangeTabs.vue'
import InfluenceScatter from '@/components/InfluenceScatter.vue'
import ActorList from '@/components/ActorList.vue'
import { EMOTION_COLORS, EMOTION_ORDER } from '@/api/echarts-theme'
import type { Actor, InfluenceEmotionPoint, RangeKey } from '@/types/api'

const metaStore = useMetaStore()
const { data: meta, range } = storeToRefs(metaStore)

const actors = ref<Actor[]>([])
const scatter = ref<InfluenceEmotionPoint[]>([])
const errorMsg = ref('')

async function loadAll() {
  errorMsg.value = ''
  const [a, s] = await Promise.allSettled([
    api.actors(range.value, 30),
    api.influenceEmotion(range.value, 80),
  ])
  if (a.status === 'fulfilled') actors.value = a.value
  if (s.status === 'fulfilled') scatter.value = s.value
  const failed = [a, s].filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
  if (failed.length) errorMsg.value = failed.map((f) => String(f.reason)).join(' / ')
}

function setRange(v: RangeKey) {
  metaStore.setRange(v)
}

onMounted(async () => {
  await metaStore.load()
  await loadAll()
})

watch(range, () => loadAll())
</script>

<template>
  <section class="page-head">
    <div class="reveal">
      <p class="page-eyebrow">SECTION III / ACTORS</p>
      <h1 class="page-title">关键<em>账号</em></h1>
      <p class="page-lead">舆情场域中影响力较高的账号，已做角色化脱敏。点击账号卡懒加载该账号在窗口内的代表样本。</p>
    </div>
    <div class="page-meta reveal">
      <RangeTabs v-if="meta" :model-value="range" :options="meta.time_range_options" @update:model-value="setRange" />
    </div>
  </section>

  <section class="scatter-section reveal">
    <div class="section-head">
      <div>
        <p class="eyebrow">INFLUENCE × NEGATIVE</p>
        <h2 class="section-title">影响力 × 负面率<em>scatter</em></h2>
      </div>
      <div class="scatter-legend">
        <span v-for="l in EMOTION_ORDER" :key="l">
          <i :style="{ background: EMOTION_COLORS[l] }"></i>{{ l }}
        </span>
        <span class="muted">尺寸 = 互动量</span>
      </div>
    </div>
    <div class="scatter-card">
      <InfluenceScatter :data="scatter" />
    </div>
    <p class="scatter-hint">
      横轴为账号综合影响力分（互动量 + 粉丝段位 + 认证），纵轴为该账号在窗口内推断样本的负面情绪占比，
      点的尺寸映射互动量。右上方密集的点意味着影响力高且情绪偏负面，是研判优先关注的账号。
    </p>
  </section>

  <section class="list-section">
    <div class="section-head">
      <div>
        <p class="eyebrow">ACTORS / TOP {{ actors.length }}</p>
        <h2 class="section-title">账号列表<em>top movers</em></h2>
      </div>
    </div>
    <ActorList :actors="actors" :range="range" />
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
  line-height: 0.96; letter-spacing: -0.04em; color: var(--ink);
  margin-top: 24px;
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
.page-meta { padding-bottom: 6px; }

.scatter-section {
  padding: 40px var(--shell-pad-x) 32px;
  border-top: 1px solid var(--line);
}
.list-section {
  padding: 40px var(--shell-pad-x) 80px;
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

.scatter-legend {
  display: flex; gap: 14px; flex-wrap: wrap;
  font-family: var(--mono); font-size: 11px;
  color: var(--muted);
}
.scatter-legend span { display: flex; align-items: center; gap: 6px; }
.scatter-legend i { width: 8px; height: 8px; border-radius: 50%; }
.scatter-legend .muted { color: var(--muted-2); }

.scatter-card {
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.012);
  padding: 18px 14px 6px;
}
.scatter-hint {
  margin-top: 14px;
  font-size: 12px; line-height: 1.8;
  color: var(--muted);
  max-width: 720px;
}

.error-line {
  padding: 16px var(--shell-pad-x);
  color: var(--alert); font-family: var(--mono); font-size: 12px;
}
</style>
