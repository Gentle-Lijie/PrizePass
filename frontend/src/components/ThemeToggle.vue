<script setup lang="ts">
import { computed } from 'vue'
import { Moon, Sun } from 'lucide-vue-next'
import { useRoute } from 'vue-router'

import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
const route = useRoute()

// 有 sticky 底部操作栏的兑换页，切换按钮上移到顶部，避免遮挡
const avoidBottom = ['/redeem/prizes', '/redeem/confirm']
const atBottomBar = computed(() => avoidBottom.includes(route.path))
</script>

<template>
  <button
    type="button"
    class="fixed z-50 grid h-9 w-9 place-items-center rounded-full border border-slate-200 bg-white/80 text-slate-600 shadow-sm backdrop-blur transition hover:text-ink hover:shadow-md dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
    :class="atBottomBar ? 'right-4 top-4' : 'bottom-4 right-4'"
    :aria-label="
      themeStore.theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'
    "
    @click="themeStore.toggle()"
  >
    <Sun v-if="themeStore.theme === 'dark'" class="h-[18px] w-[18px]" />
    <Moon v-else class="h-[18px] w-[18px]" />
  </button>
</template>
