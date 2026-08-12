<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { PublicPrize, RedemptionContext } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useRedemptionStore } from '@/stores/redemption'

const auth = useAuthStore()
const redemption = useRedemptionStore()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const used = computed(() => redemption.prizes.reduce((sum, prize) => sum + prize.redeem_value * (redemption.quantities[prize.id] ?? 0), 0))
const remaining = computed(() => (redemption.context?.quota ?? 0) - used.value)
const itemCount = computed(() => Object.values(redemption.quantities).reduce((sum, quantity) => sum + quantity, 0))

function money(cents: number) { return `¥${(cents / 100).toFixed(2)}` }
function quantity(prize: PublicPrize) { return redemption.quantities[prize.id] ?? 0 }
function change(prize: PublicPrize, delta: number) {
  const next = quantity(prize) + delta
  if (next < 0 || next > prize.stock) return
  if (delta > 0 && used.value + prize.redeem_value > (redemption.context?.quota ?? 0)) return
  if (next === 0) delete redemption.quantities[prize.id]
  else redemption.quantities[prize.id] = next
}

async function load() {
  if (!auth.redemptionCode) { await router.replace('/redeem'); return }
  try {
    const [context, prizes] = await Promise.all([
      api<RedemptionContext>('/api/public/redemption/context'),
      api<PublicPrize[]>('/api/public/redemption/prizes'),
    ])
    redemption.context = context
    redemption.prizes = prizes
  } catch {
    auth.clearRedemptionCode(); redemption.resetSelection(); await router.replace('/redeem')
  } finally { loading.value = false }
}

async function continueToConfirm() {
  if (itemCount.value > 0 && remaining.value >= 0) await router.push('/redeem/confirm')
}

onMounted(load)
</script>

<template>
  <main class="mx-auto min-h-screen max-w-6xl p-6 md:p-10">
    <section v-if="loading" class="card">正在加载奖品…</section>
    <template v-else-if="redemption.context">
      <header class="flex flex-wrap items-end justify-between gap-4">
        <div><p class="text-sm font-semibold text-blue-600">{{ redemption.context.event.name }}</p><h1 class="mt-1 text-3xl font-bold">选择奖品</h1><p class="mt-2 text-sm text-slate-500">可以选择多个奖品及数量，一次提交后兑换码将失效。</p></div>
        <div class="card flex gap-7 py-4 text-center"><div><strong class="block text-xl">{{ redemption.context.quota }}</strong><span class="text-xs text-slate-500">总 quota</span></div><div><strong class="block text-xl text-blue-600">{{ used }}</strong><span class="text-xs text-slate-500">已使用</span></div><div><strong class="block text-xl text-emerald-600">{{ remaining }}</strong><span class="text-xs text-slate-500">剩余</span></div></div>
      </header>
      <p v-if="error" class="mt-4 text-sm text-red-600">{{ error }}</p>
      <section class="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <article v-for="prize in redemption.prizes" :key="prize.id" class="card overflow-hidden p-0">
          <img :src="prize.image" :alt="prize.name" class="aspect-[4/3] w-full bg-slate-100 object-cover" />
          <div class="p-5"><h2 class="text-lg font-bold">{{ prize.name }}</h2><p class="mt-2 min-h-10 text-sm text-slate-500">{{ prize.description }}</p><div class="mt-4 flex items-end justify-between"><div><p class="text-xs text-slate-500">参考 {{ money(prize.real_value) }} · 库存 {{ prize.stock }}</p><p class="mt-1 font-semibold text-blue-600">{{ prize.redeem_value }} 额度 / 件</p></div><div class="flex items-center gap-3"><button class="h-9 w-9 rounded-full border" :disabled="quantity(prize) === 0" @click="change(prize, -1)">−</button><strong class="w-5 text-center">{{ quantity(prize) }}</strong><button class="h-9 w-9 rounded-full border" :disabled="quantity(prize) >= prize.stock || remaining < prize.redeem_value" @click="change(prize, 1)">+</button></div></div></div>
        </article>
        <div v-if="redemption.prizes.length === 0" class="card col-span-full text-center text-slate-500">当前没有可兑换的奖品</div>
      </section>
      <div class="sticky bottom-4 mt-8 flex items-center justify-between rounded-xl bg-slate-950 p-4 text-white shadow-xl"><div><strong>{{ itemCount }} 件奖品</strong><span class="ml-3 text-sm text-slate-300">消耗 {{ used }}，剩余 {{ remaining }}</span></div><button class="rounded-lg bg-white px-5 py-2 font-semibold text-slate-950 disabled:opacity-40" :disabled="itemCount === 0 || remaining < 0" @click="continueToConfirm">填写领取信息</button></div>
    </template>
  </main>
</template>
