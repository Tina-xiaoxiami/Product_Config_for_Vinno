import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    children: [
      {
        path: '',
        redirect: '/config'
      },
      {
        path: 'series',
        name: 'Series',
        component: () => import('../views/Series.vue'),
        meta: { title: '系列管理' }
      },
      {
        path: 'models',
        name: 'Models',
        component: () => import('../views/Models.vue'),
        meta: { title: '型号管理' }
      },
      {
        path: 'config',
        name: 'Config',
        component: () => import('../views/Config.vue'),
        meta: { title: '配置管理' }
      },
      {
        path: 'compare',
        name: 'Compare',
        component: () => import('../views/Compare.vue'),
        meta: { title: '配置对比' }
      },
      {
        path: 'versions',
        name: 'Versions',
        component: () => import('../views/Versions.vue'),
        meta: { title: '版本历史' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router