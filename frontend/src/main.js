import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import FeatureNameMark from './components/FeatureNameMark.vue'
import { loadFeatureNameStandardFlags } from './utils/featureNameStandard'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 功能名称标准提示：全局可用，启动时后台预取标记
app.component('FeatureNameMark', FeatureNameMark)
loadFeatureNameStandardFlags()

app.mount('#app')