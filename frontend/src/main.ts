import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { applyTheme, readInitialTheme } from './stores/theme'
import './style.css'

// 在挂载前应用主题，避免深浅模式闪烁
applyTheme(readInitialTheme())

createApp(App).use(createPinia()).use(router).mount('#app')
