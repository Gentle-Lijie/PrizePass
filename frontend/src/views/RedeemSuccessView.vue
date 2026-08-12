<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useRedemptionStore } from '@/stores/redemption'

const redemption = useRedemptionStore()
const router = useRouter()
onMounted(async () => { if (!redemption.success) await router.replace('/redeem') })
</script>

<template>
  <main class="grid min-h-screen place-items-center bg-emerald-50 p-6">
    <section v-if="redemption.success" class="card w-full max-w-lg text-center">
      <div class="mx-auto grid h-16 w-16 place-items-center rounded-full bg-emerald-100 text-3xl text-emerald-700">✓</div>
      <h1 class="mt-5 text-3xl font-bold">兑换提交成功</h1>
      <p class="mt-2 text-sm text-slate-500">请保存兑换单号，并按下方说明前往自提。</p>
      <div class="mt-6 rounded-xl bg-slate-950 p-5 text-white"><p class="text-xs text-slate-400">兑换单号</p><strong class="mt-1 block font-mono text-xl tracking-wider">{{ redemption.success.order_no }}</strong><p class="mt-2 text-sm">状态：待备货</p></div>
      <div class="mt-5 text-left"><h2 class="font-semibold">自提地点</h2><p class="mt-2">{{ redemption.success.pickup_location }}</p><p class="mt-2 whitespace-pre-wrap text-sm text-slate-600">{{ redemption.success.pickup_instructions }}</p></div>
    </section>
  </main>
</template>
