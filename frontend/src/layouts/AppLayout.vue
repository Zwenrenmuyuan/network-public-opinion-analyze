<script setup lang="ts">
import AppTicker from '@/components/AppTicker.vue'
import AppNav from '@/components/AppNav.vue'
import AppFooter from '@/components/AppFooter.vue'
</script>

<template>
  <AppTicker />
  <AppNav />
  <main class="layout-main">
    <RouterView />
  </main>
  <AppFooter />
</template>

<style scoped>
.layout-main { flex: 1 1 auto; }
</style>
