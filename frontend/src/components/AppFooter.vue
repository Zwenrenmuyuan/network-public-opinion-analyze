<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const sectionLabel = computed(() => {
  const map: Record<string, string> = {
    overview: 'SECTION I / OVERVIEW',
    topics: 'SECTION II / TOPICS',
    actors: 'SECTION III / ACTORS',
    model: 'SECTION IV / MODEL',
    'data-quality': 'SECTION V / DATA QUALITY',
  }
  return map[String(route.name ?? '')] ?? 'NPO'
})
</script>

<template>
  <footer class="signature">
    <span>{{ sectionLabel }}</span>
    <em>"To watch is not to predict, but to interpret."</em>
    <span>NPO · 2026 RESEARCH</span>
  </footer>
</template>

<style scoped>
.signature {
  padding: 40px var(--shell-pad-x);
  display: flex; justify-content: space-between; align-items: center; gap: 20px;
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--muted);
  border-top: 1px solid var(--line);
}
.signature em {
  font-style: italic; font-family: var(--serif);
  font-variation-settings: "SOFT" 50, "opsz" 144;
  font-size: 15px; letter-spacing: 0; color: var(--ink-2);
  text-transform: none; font-weight: 300;
}
@media (max-width: 1100px) {
  .signature { flex-direction: column; align-items: flex-start; gap: 12px; padding: 32px var(--shell-pad-x); }
}
</style>
