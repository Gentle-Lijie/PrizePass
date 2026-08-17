import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { createNotivue } from 'notivue'
import 'notivue/animations.css'
import 'notivue/notification.css'

import App from './App.vue'
import router from './router'
import { applyTheme, readInitialTheme } from './stores/theme'
import './style.css'

// 在挂载前应用主题，避免深浅模式闪烁
applyTheme(readInitialTheme())

const notivue = createNotivue()

createApp(App).use(notivue).use(createPinia()).use(router).mount('#app')
