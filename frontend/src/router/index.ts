import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'overview', component: () => import('@/views/Overview.vue'), meta: { label: '总览' } },
  { path: '/topics/:id?', name: 'topics', component: () => import('@/views/Topics.vue'), meta: { label: '话题' } },
  { path: '/actors', name: 'actors', component: () => import('@/views/Actors.vue'), meta: { label: '账号' } },
  { path: '/model', name: 'model', component: () => import('@/views/Model.vue'), meta: { label: '模型' } },
  { path: '/data-quality', name: 'data-quality', component: () => import('@/views/DataQuality.vue'), meta: { label: '数据口径' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() { return { top: 0 } },
})
