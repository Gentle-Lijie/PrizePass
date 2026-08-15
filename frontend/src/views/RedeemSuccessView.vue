<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useRedemptionStore } from '@/stores/redemption'

const redemption = useRedemptionStore()
const router = useRouter()
onMounted(async () => {
  if (!redemption.success) await router.replace('/redeem')
})
</script>

<template>
  <main
    class="min-h-screen bg-emerald-50 px-4 py-6 dark:bg-emerald-950/20 sm:grid sm:place-items-center sm:p-6"
  >
    <section
      v-if="redemption.success"
      class="card mx-auto w-full max-w-lg p-5 text-center sm:p-6"
    >
      <div
        class="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-100 text-2xl text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300 sm:h-16 sm:w-16 sm:text-3xl"
      >
        ✓
      </div>
      <h1 class="mt-4 text-2xl font-bold sm:mt-5 sm:text-3xl">兑换提交成功</h1>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
        请保存兑换单号，并按下方说明前往自提。<template v-if="redemption.success.custom_name"
          >自定义奖品提交后需管理员确认，结果会通过邮件通知你。</template
        >
      </p>
      <div
        class="mt-5 min-w-0 rounded-xl bg-slate-950 p-4 text-white sm:mt-6 sm:p-5"
      >
        <p class="text-xs text-slate-400">兑换单号</p>
        <strong
          class="mt-2 block break-all font-mono text-base leading-7 tracking-wide sm:text-xl sm:tracking-wider"
          >{{ redemption.success.order_no }}</strong
        >
        <p class="mt-2 text-sm">状态：待备货</p>
      </div>
      <div class="mt-5 text-left">
        <h2 class="font-semibold">自提地点</h2>
        <p class="mt-2">{{ redemption.success.pickup_location }}</p>
        <p
          class="mt-2 whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300"
        >
          {{ redemption.success.pickup_instructions }}
        </p>
      </div>
      <button class="btn-secondary mt-6 w-full" @click="router.push('/')">
        返回首页
      </button>
    </section>
  </main>
</template>
