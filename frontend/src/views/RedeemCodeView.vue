<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useRedemptionStore } from '@/stores/redemption'

const code = ref('')
const error = ref('')
const busy = ref(false)
const auth = useAuthStore()
const redemption = useRedemptionStore()
const router = useRouter()

async function verify() {
  busy.value = true
  error.value = ''
  auth.redemptionCode = code.value.trim().toUpperCase()
  redemption.resetSelection()
  try {
    await api('/api/public/code/verify', { method: 'POST' })
    await router.push('/redeem/prizes')
  } catch {
    auth.clearRedemptionCode()
    error.value = '兑换码无效或当前不可使用'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="grid min-h-screen place-items-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 p-6">
    <form class="card w-full max-w-md" @submit.prevent="verify">
      <p class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600">PrizePass</p>
      <h1 class="mt-2 text-3xl font-bold">兑换你的奖品</h1>
      <p class="mt-2 text-sm text-slate-500">请输入邮件中收到的 12 位兑换码。</p>
      <label class="mt-6 block text-sm font-medium" for="code">兑换码</label>
      <input id="code" v-model="code" class="field mt-2 text-center font-mono text-xl uppercase tracking-[0.2em]" maxlength="12" minlength="12" autocomplete="off" required />
      <p v-if="error" class="mt-3 text-sm text-red-600" role="alert">{{ error }}</p>
      <button class="btn-primary mt-4 w-full" :disabled="busy || code.trim().length !== 12">{{ busy ? '验证中…' : '验证兑换码' }}</button>
    </form>
  </main>
</template>
