<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const now = ref(new Date())
let timer: number | undefined
onMounted(() => { timer = window.setInterval(() => { now.value = new Date() }, 1000) })
onUnmounted(() => { if (timer) window.clearInterval(timer) })

const stamp = computed(() => {
  const d = now.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}·${pad(d.getMonth() + 1)}·${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const items = [
  { label: 'MODEL', text: 'ERNIE-USUAL-MIXED-V2' },
  { label: 'CACHE', text: 'REDIS · TTL 5MIN' },
  { label: 'DATA', text: '同源 API · CK' },
  { label: 'STATUS', text: '系统在线 · 实时同步' },
]
</script>

<template>
  <div class="ticker">
    <div class="pulse" aria-hidden="true"></div>
    <div class="stream">
      <span><em>{{ stamp }}</em>NPO · 舆情研判驾驶舱</span>
      <span v-for="it in items" :key="it.label"><em>{{ it.label }}</em>{{ it.text }}</span>
      <span><em>{{ stamp }}</em>NPO · 舆情研判驾驶舱</span>
      <span v-for="it in items" :key="`d-${it.label}`"><em>{{ it.label }}</em>{{ it.text }}</span>
    </div>
  </div>
</template>

<style scoped>
.ticker {
  position: sticky; top: 0; z-index: 50;
  background: var(--bg-0);
  border-bottom: 1px solid var(--line);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  display: flex; align-items: center;
  height: 32px; overflow: hidden;
}
.pulse {
  width: 8px; height: 8px;
  background: var(--alert); border-radius: 50%;
  margin: 0 14px; flex: 0 0 auto;
  box-shadow: 0 0 14px var(--alert);
  animation: pulse 1.4s ease infinite;
}
.stream {
  white-space: nowrap;
  animation: marquee 56s linear infinite;
  display: flex; gap: 48px;
}
.stream span { flex: 0 0 auto; }
.stream em { font-style: normal; color: var(--accent); margin-right: 8px; }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes pulse {
  0%, 100% { opacity: 0.5; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.4); }
}
</style>
