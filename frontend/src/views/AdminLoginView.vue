<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const password = ref('')
const error = ref('')
const busy = ref(false)
const auth = useAuthStore()
const router = useRouter()

async function enter() {
  busy.value = true
  error.value = ''
  auth.adminPassword = password.value
  try {
    await api<{ ok: boolean }>('/api/admin/check')
    await router.push('/admin/events')
  } catch (caught) {
    auth.clearAdminPassword()
    error.value =
      caught instanceof ApiError ? caught.message : '暂时无法连接服务器'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="grid min-h-screen place-items-center p-6">
    <form class="card w-full max-w-sm" @submit.prevent="enter">
      <p
        class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400"
      >
        PrizePass
      </p>
      <h1 class="mt-2 text-2xl font-bold">管理员入口</h1>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
        密码仅保存在当前页面内存，刷新后需要重新输入。
      </p>
      <label class="mt-6 block text-sm font-medium" for="password"
        >管理员密码</label
      >
      <input
        id="password"
        v-model="password"
        class="field mt-2"
        type="password"
        required
        autocomplete="current-password"
      />
      <p
        v-if="error"
        class="mt-3 text-sm text-red-600 dark:text-red-400"
        role="alert"
      >
        {{ error }}
      </p>
      <button
        class="btn-primary mt-5 w-full"
        type="submit"
        :disabled="busy || !password"
      >
        {{ busy ? '验证中…' : '进入后台' }}
      </button>
    </form>
  </main>
</template>
