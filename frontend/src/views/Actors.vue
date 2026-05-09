<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMetaStore } from '@/stores/meta'
import { api } from '@/api/client'
import RangeTabs from '@/components/RangeTabs.vue'
import ActorList from '@/components/ActorList.vue'
import type { Actor, RangeKey } from '@/types/api'

const metaStore = useMetaStore()
const { data: meta, range } = storeToRefs(metaStore)

const actors = ref<Actor[]>([])
const errorMsg = ref('')
const selectedRoles = ref<Set<string>>(new Set())

const ROLE_FILTERS = [
  { key: 'entry_kol', label: '入口 KOL' },
  { key: 'verified_actor', label: '认证' },
  { key: 'high_follower_actor', label: '高粉' },
  { key: 'high_interaction', label: '高互动' },
  { key: 'negative_polarized', label: '负面极化' },
  { key: 'active_voice', label: '活跃发言' },
  { key: 'cross_topic', label: '跨话题' },
]

const filteredActors = computed(() => {
  if (selectedRoles.value.size === 0) return actors.value
  return actors.value.filter((a) => a.roles.some((r) => selectedRoles.value.has(r)))
})

const roleCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const r of ROLE_FILTERS) counts[r.key] = 0
  for (const a of actors.value) {
    for (const r of a.roles) {
      if (counts[r] !== undefined) counts[r] += 1
    }
  }
  return counts
})

function toggleRole(key: string) {
  const s = new Set(selectedRoles.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  selectedRoles.value = s
}

function clearRoles() {
  selectedRoles.value = new Set()
}

async function loadActors() {
  errorMsg.value = ''
  try {
    actors.value = await api.actors(range.value, 50)
  } catch (e) {
    errorMsg.value = (e as Error).message
  }
}

function setRange(v: RangeKey) {
  metaStore.setRange(v)
}

onMounted(async () => {
  await metaStore.load()
  await loadActors()
})

watch(range, () => loadActors())
</script>

<template>
  <section class="page-head">
    <div class="reveal">
      <p class="page-eyebrow">SECTION III / ACTORS</p>
      <h1 class="page-title">关键<em>账号</em></h1>
      <p class="page-lead">
        多维 OR 评判：账号只要满足"入口 KOL / 认证 / 高粉 / 高互动 / 负面极化 / 活跃 / 跨话题"任一标签即纳入。
        排序按匹配标签数 DESC。点击账号卡懒加载该账号在窗口内的代表样本。
      </p>
    </div>
    <div class="page-meta reveal">
      <RangeTabs v-if="meta" :model-value="range" :options="meta.time_range_options" @update:model-value="setRange" />
    </div>
  </section>

  <section class="filter-section reveal">
    <div class="filter-row">
      <button
        class="chip-btn"
        :class="{ active: selectedRoles.size === 0 }"
        @click="clearRoles"
      >
        全部 <small>{{ actors.length }}</small>
      </button>
      <button
        v-for="r in ROLE_FILTERS" :key="r.key"
        class="chip-btn"
        :class="{ active: selectedRoles.has(r.key) }"
        @click="toggleRole(r.key)"
      >
        {{ r.label }} <small>{{ roleCounts[r.key] }}</small>
      </button>
    </div>
    <p class="filter-hint">
      多选 OR：勾选多个标签 = 显示满足任一的账号。当前显示
      <strong>{{ filteredActors.length }}</strong> / {{ actors.length }} 个。
    </p>
  </section>

  <section class="list-section">
    <ActorList :actors="filteredActors" :range="range" />
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
  margin-top: 22px; max-width: 720px;
  color: var(--ink-2); font-size: 14px; line-height: 1.85;
}
.page-meta { padding-bottom: 6px; }

.filter-section {
  padding: 28px var(--shell-pad-x) 12px;
  border-top: 1px solid var(--line);
}
.filter-row {
  display: flex; flex-wrap: wrap; gap: 8px;
}
.chip-btn {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.12em;
  padding: 8px 14px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.02);
  color: var(--muted);
  transition: color 0.2s, border-color 0.2s, background 0.2s;
  display: flex; align-items: center; gap: 8px;
}
.chip-btn small {
  font-size: 10px;
  color: var(--muted-2);
  font-variant-numeric: tabular-nums;
}
.chip-btn:hover { color: var(--ink-2); border-color: var(--line-2); }
.chip-btn.active {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(245,195,74,0.06);
}
.chip-btn.active small { color: var(--accent); }

.filter-hint {
  margin-top: 14px;
  font-family: var(--mono); font-size: 11px;
  color: var(--muted); letter-spacing: 0.04em;
}
.filter-hint strong { color: var(--accent); font-variant-numeric: tabular-nums; }

.list-section {
  padding: 24px var(--shell-pad-x) 80px;
}

.error-line {
  padding: 16px var(--shell-pad-x);
  color: var(--alert); font-family: var(--mono); font-size: 12px;
}
</style>
