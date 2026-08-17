<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useRedemptionStore } from '@/stores/redemption'

const code = ref('')
const error = ref('')
const busy = ref(false)
const auth = useAuthStore()
const redemption = useRedemptionStore()
const router = useRouter()
const route = useRoute()

const codeErrorMessages: Record<string, string> = {
  invalid_redemption_code: '兑换码不存在，请检查后重试',
  redemption_code_redeemed: '该兑换码已使用',
  redemption_code_disabled: '该兑换码已被撤销，请联系管理员',
  event_not_active: '比赛尚未开放兑换，请稍后再试',
  event_closed: '比赛兑换已关闭',
  redemption_expired: '该比赛已超过兑换截止时间',
}

async function verify() {
  busy.value = true
  error.value = ''
  auth.redemptionCode = code.value.trim().toUpperCase()
  redemption.resetSelection()
  try {
    await api('/api/public/code/verify', { method: 'POST' })
    await router.push('/redeem/prizes')
  } catch (caught) {
    auth.clearRedemptionCode()
    error.value =
      caught instanceof ApiError ? (codeErrorMessages[caught.code] ?? caught.message) : '暂时无法连接服务器，请稍后重试'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  const queryCode = Array.isArray(route.query.code) ? route.query.code[0] : route.query.code
  if (!queryCode) return
  code.value = queryCode.trim().toUpperCase()
  await router.replace({ path: '/redeem' })
  await verify()
})
</script>

<template>
  <main
    class="grid min-h-screen place-items-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 p-6 dark:from-slate-900 dark:via-slate-950 dark:to-slate-900"
  >
    <form class="card w-full max-w-md" @submit.prevent="verify">
      <p class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400">PrizePass</p>
      <h1 class="mt-2 text-3xl font-bold">兑换你的奖品</h1>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">请输入邮件中收到的 12 位兑换码。</p>
      <label class="mt-6 block text-sm font-medium" for="code">兑换码</label>
      <input
        id="code"
        v-model="code"
        class="field mt-2 text-center font-mono text-xl uppercase tracking-[0.2em]"
        maxlength="12"
        minlength="12"
        autocomplete="off"
        required
      />
      <p v-if="error" class="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">
        {{ error }}
      </p>
      <button class="btn-primary mt-4 w-full" :disabled="busy || code.trim().length !== 12">
        {{ busy ? '验证中…' : '验证兑换码' }}
      </button>
    </form>
  </main>
</template>
