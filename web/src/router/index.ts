import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
  ],
})

// 登录守卫：未登录跳 /login，已登录访问 /login 跳回 /
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!auth.isLoggedIn && to.name !== 'login') {
    return { name: 'login' }
  }
  if (auth.isLoggedIn && to.name === 'login') {
    return { name: 'chat' }
  }
})

export default router
