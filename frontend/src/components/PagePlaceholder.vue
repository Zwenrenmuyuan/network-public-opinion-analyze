<script setup lang="ts">
defineProps<{ eyebrow: string; title: string; hint?: string }>()
</script>

<template>
  <section class="page reveal">
    <p class="page-eyebrow">{{ eyebrow }}</p>
    <h1 class="page-title">{{ title }}</h1>
    <p v-if="hint" class="page-hint">{{ hint }}</p>
  </section>
</template>

<style scoped>
.page {
  padding: 90px var(--shell-pad-x) 70px;
  max-width: 920px;
}
.page-eyebrow {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--accent);
  display: flex; align-items: center; gap: 14px;
}
.page-eyebrow::before {
  content: ''; width: 40px; height: 1px; background: var(--accent);
}
.page-title {
  font-family: var(--serif-cn); font-weight: 900;
  font-size: clamp(48px, 7vw, 88px);
  line-height: 0.96;
  letter-spacing: -0.04em;
  color: var(--ink);
  margin-top: 32px;
}
.page-hint {
  margin-top: 36px;
  color: var(--ink-2); font-size: 16px; line-height: 1.85;
  max-width: 600px;
}
</style>
