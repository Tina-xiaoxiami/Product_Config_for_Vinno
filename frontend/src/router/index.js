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
      },
      {
        path: 'probe-models',
        name: 'ProbeModelsView',
        component: () => import('../views/ProbeModelsView.vue'),
        meta: { title: '探头管理' }
      },
      {
        path: 'applications',
        name: 'ApplicationsView',
        component: () => import('../views/ApplicationsView.vue'),
        meta: { title: '应用管理' }
      },
      {
        path: 'feature-manage',
        name: 'FeatureManage',
        component: () => import('../views/FeatureManage.vue'),
        meta: { title: '功能管理' }
      },
      {
        path: 'template-features',
        name: 'TemplateFeatures',
        component: () => import('../views/TemplateFeatures.vue'),
        meta: { title: '模板管理' }
      },
      {
        path: 'probe-config',
        name: 'ProbeConfig',
        component: () => import('../views/ProbeConfig.vue'),
        meta: { title: '探头配置管理' }
      },
      {
        path: 'probe-versions',
        name: 'ProbeVersions',
        component: () => import('../views/ProbeVersions.vue'),
        meta: { title: '探头版本历史' }
      },
      {
        path: 'knowledge',
        name: 'KnowledgeHub',
        component: () => import('../views/KnowledgeHub.vue'),
        meta: { title: '产品知识库' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
