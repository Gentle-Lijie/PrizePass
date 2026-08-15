<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { RedemptionSuccess } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useRedemptionStore } from '@/stores/redemption'

const auth = useAuthStore()
const redemption = useRedemptionStore()
const router = useRouter()
const busy = ref(false)
const error = ref('')
const form = reactive({ contact_name: '', contact_phone: '', note: '' })
const selected = computed(() =>
  redemption.prizes.filter(
    (prize) => (redemption.quantities[prize.id] ?? 0) > 0,
  ),
)
const isCustom = computed(() => redemption.customPrize !== null)
const used = computed(() =>
  selected.value.reduce(
    (sum, prize) => sum + prize.redeem_value * redemption.quantities[prize.id]!,
    0,
  ),
)
const remaining = computed(() => (redemption.context?.quota ?? 0) - used.value)

// Custom-prize submissions must first pass a one-off invoice confirmation.
// Confirmation is intentionally not persisted anywhere.
const showInvoiceConfirm = ref(false)

async function requestSubmit() {
  if (isCustom.value) {
    showInvoiceConfirm.value = true
    return
  }
  await submit()
}

async function submit() {
  showInvoiceConfirm.value = false
  busy.value = true
  error.value = ''
  try {
    const custom = redemption.customPrize
    redemption.success = await api<RedemptionSuccess>(
      '/api/public/redemptions',
      {
        method: 'POST',
        body: JSON.stringify({
          contact_name: form.contact_name,
          contact_phone: form.contact_phone,
          note: form.note || null,
          ...(custom
            ? {
                items: [],
                custom_name: custom.name,
                custom_url: custom.url || null,
                custom_note: custom.note || null,
                custom_price: custom.priceYuan
                  ? Math.round(Number(custom.priceYuan) * 100)
                  : null,
              }
            : {
                items: selected.value.map((prize) => ({
                  prize_id: prize.id,
                  quantity: redemption.quantities[prize.id],
                })),
              }),
        }),
      },
    )
    auth.clearRedemptionCode()
    await router.replace('/redeem/success')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '提交失败，请重试'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  if (
    !auth.redemptionCode ||
    !redemption.context ||
    (selected.value.length === 0 && !redemption.customPrize)
  )
    await router.replace('/redeem')
})
</script>

<template>
  <main class="mx-auto min-h-screen max-w-3xl p-6 pb-18 md:p-10 md:pb-32">
    <button
      class="text-sm text-blue-600 dark:text-blue-400"
      @click="router.back()"
    >
      ← 返回选择奖品
    </button>
    <h1 class="mt-4 text-3xl font-bold">确认兑换</h1>
    <form
      v-if="redemption.context"
      class="mt-6 grid gap-6"
      @submit.prevent="requestSubmit"
    >
      <section class="card">
        <h2 class="font-semibold">奖品明细</h2>
        <template v-if="isCustom && redemption.customPrize">
          <div class="mt-4 border-t border-slate-200 pt-4 text-sm dark:border-slate-700">
            <p>
              自定义奖品：<strong>{{ redemption.customPrize.name }}</strong>
              <strong
                v-if="redemption.customPrize.priceYuan"
                class="ml-2 text-blue-600 dark:text-blue-400"
                >¥{{ redemption.customPrize.priceYuan }}</strong
              >
            </p>
            <a
              v-if="redemption.customPrize.url"
              :href="redemption.customPrize.url"
              target="_blank"
              rel="noopener noreferrer"
              class="mt-1 block break-all text-blue-600 dark:text-blue-400"
              >{{ redemption.customPrize.url }} ↗</a
            >
            <p
              v-if="redemption.customPrize.note"
              class="mt-2 text-slate-500 dark:text-slate-400"
            >
              备注：{{ redemption.customPrize.note }}
            </p>
            <p class="mt-3 text-xs text-amber-600 dark:text-amber-400">
              提交后管理员将确认是否采纳，结果会通过邮件通知你；被拒绝时兑换码会自动恢复，可重新选择奖品。
            </p>
          </div>
        </template>
        <template v-else>
          <div
            v-for="prize in selected"
            :key="prize.id"
            class="mt-4 flex flex-col gap-1 border-t border-slate-200 pt-4 text-sm dark:border-slate-700 sm:flex-row sm:items-center sm:justify-between"
          >
            <span class="break-words"
              >{{ prize.name }} × {{ redemption.quantities[prize.id] }}</span
            ><strong class="shrink-0"
              >{{
                prize.redeem_value * redemption.quantities[prize.id]!
              }}
              额度</strong
            >
          </div>
          <div
            class="mt-5 flex flex-col gap-1 border-t border-slate-200 pt-4 dark:border-slate-700 sm:flex-row sm:justify-between"
          >
            <strong>总消耗 {{ used }}</strong
            ><span class="text-emerald-600 dark:text-emerald-400"
              >剩余 {{ remaining }}</span
            >
          </div>
        </template>
      </section>
      <section class="card">
        <h2 class="font-semibold">领取人信息</h2>
        <div class="mt-4 grid gap-4">
          <label class="text-sm font-medium"
            >姓名
            <input
              v-model="form.contact_name"
              class="field mt-1"
              maxlength="100"
              required
          /></label>
          <label class="text-sm font-medium"
            >手机号
            <input
              v-model="form.contact_phone"
              class="field mt-1"
              minlength="5"
              maxlength="30"
              pattern="[0-9+() -]{5,30}"
              required
          /></label>
          <label class="text-sm font-medium"
            >备注（可选）
            <textarea
              v-model="form.note"
              class="field mt-1"
              maxlength="500"
              rows="3"
            />
          </label>
        </div>
      </section>
      <section class="card bg-blue-50 dark:bg-blue-950/40">
        <h2 class="font-semibold">自提信息</h2>
        <p class="mt-2">{{ redemption.context.event.pickup_location }}</p>
        <p
          class="mt-1 whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300"
        >
          {{ redemption.context.event.pickup_instructions }}
        </p>
      </section>
      <p
        v-if="error"
        class="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
      >
        {{ error }}
      </p>
      <div class="relative sticky bottom-4 z-10 sm:static">
        <div
          class="pointer-events-none absolute inset-x-0 -top-12 h-16 bg-gradient-to-t from-canvas via-canvas/90 to-transparent backdrop-blur-[3px] sm:hidden"
          style="
            mask-image: linear-gradient(
              to top,
              black 0%,
              black 38%,
              transparent 100%
            );
            -webkit-mask-image: linear-gradient(
              to top,
              black 0%,
              black 38%,
              transparent 100%
            );
          "
        ></div>
        <button
          class="btn-primary relative w-full py-3 shadow-lg sm:static sm:shadow-none"
          :disabled="busy || (!isCustom && remaining < 0)"
          @click="requestSubmit"
        >
          {{ busy ? '提交中…' : '确认并提交兑换' }}
        </button>
      </div>
    </form>

    <div
      v-if="showInvoiceConfirm"
      class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showInvoiceConfirm = false"
    >
      <div class="card w-full max-w-md">
        <h2 class="text-xl font-bold">请确认是否可以开票</h2>
        <p class="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
          提交自定义奖品前，请确认该商品
          <strong>可以开具发票</strong>（报销/报账需要发票凭证）。确认后才会提交兑换申请。
        </p>
        <div class="mt-6 flex flex-col gap-2 sm:flex-row">
          <button
            class="btn-primary flex-1"
            :disabled="busy"
            @click="submit"
          >
            {{ busy ? '提交中…' : '确认可以开票，提交' }}
          </button>
          <button
            class="btn-secondary flex-1"
            type="button"
            @click="showInvoiceConfirm = false"
          >
            返回检查
          </button>
        </div>
      </div>
    </div>
  </main>
</template>
