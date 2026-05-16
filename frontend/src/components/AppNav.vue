<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const tabs = [
  { name: 'overview', label: '总览', to: '/' },
  { name: 'topics', label: '话题', to: '/topics' },
  { name: 'actors', label: '账号', to: '/actors' },
  { name: 'model', label: '模型', to: '/model' },
  { name: 'data-quality', label: '数据口径', to: '/data-quality' },
]

const now = ref(new Date())
let id: number | undefined
onMounted(() => { id = window.setInterval(() => { now.value = new Date() }, 1000) })
onUnmounted(() => { if (id) window.clearInterval(id) })

const time = computed(() => {
  const d = now.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})
</script>

<template>
  <nav class="nav reveal">
    <RouterLink to="/" class="brand">
      <div class="brand-mark" aria-hidden="true">
        <img src="/favicon.svg" alt="" />
      </div>
      <div class="brand-text">
        NPO · NETWORK PUBLIC OPINION
        <strong>舆情研判驾驶舱</strong>
      </div>
    </RouterLink>

    <div class="tabs">
      <RouterLink
        v-for="t in tabs" :key="t.name" :to="t.to"
        class="tab" active-class="active"
        :exact-active-class="t.name === 'overview' ? 'active' : ''"
      >
        {{ t.label }}
      </RouterLink>
    </div>

    <div class="meta">
      LAST SYNC<br/>
      <strong>{{ time }} CST</strong>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: 32px var(--shell-pad-x) 0;
  gap: 24px;
  position: relative;
}
.brand { display: flex; align-items: center; gap: 14px; cursor: pointer; }
.brand-mark {
  width: 42px; height: 42px;
  border: 1px solid var(--line-2);
  border-radius: 50%;
  position: relative; display: grid; place-items: center;
  flex: 0 0 auto;
  background: rgba(255,255,255,0.025);
}
.brand-mark img {
  width: 34px;
  height: 34px;
  display: block;
}
.brand-mark::after {
  content: ''; position: absolute; inset: -6px;
  border: 1px dashed rgba(245, 195, 74, 0.22);
  border-radius: 50%;
  animation: spin 24s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.brand-text {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--muted);
}
.brand-text strong {
  display: block; font-family: var(--serif-cn); color: var(--ink);
  font-size: 15px; letter-spacing: 0.04em; font-weight: 500;
  text-transform: none; margin-top: 2px;
}

.tabs { display: flex; }
.tab {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--muted);
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
  transition: color 0.2s, border-color 0.2s;
}
.tab:hover { color: var(--ink-2); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

.meta {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--muted);
  text-align: right;
}
.meta strong {
  color: var(--ink); display: block;
  font-size: 13px; letter-spacing: 0.06em; margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1100px) {
  .nav { flex-wrap: wrap; }
  .tabs { order: 3; width: 100%; overflow-x: auto; }
  .meta { order: 2; }
}
</style>
