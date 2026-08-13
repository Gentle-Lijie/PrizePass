<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import type { EventRecord, EventWrite } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const events = ref<EventRecord[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const showCreate = ref(false)
const form = reactive<EventWrite>({
  name: '',
  description: null,
  status: 'draft',
  redemption_deadline: '',
  pickup_location: '',
  pickup_instructions: '',
  budget: 0,
})
const budgetYuan = ref('0.00')

function statusLabel(status: EventRecord['status']) {
  return { draft: '草稿', active: '进行中', closed: '已关闭' }[status]
}

function localTime(value: string) {
  return new Date(value).toLocaleString()
}

async function load() {
  if (!auth.adminPassword) {
    await router.replace('/admin')
    return
  }
  loading.value = true
  try {
    events.value = await api<EventRecord[]>('/api/admin/events')
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401)
      await router.replace('/admin')
    else error.value = caught instanceof Error ? caught.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshList() {
  error.value = ''
  await load()
}

async function createEvent() {
  const budget = Math.round(Number(budgetYuan.value) * 100)
  if (
    !Number.isFinite(budget) ||
    budget < 0 ||
    !/^\d+(\.\d{1,2})?$/.test(budgetYuan.value)
  ) {
    error.value = '比赛总预算必须是最多两位小数的非负金额'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const payload = {
      ...form,
      budget,
      redemption_deadline: new Date(form.redemption_deadline).toISOString(),
    }
    const created = await api<EventRecord>('/api/admin/events', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    showCreate.value = false
    await router.push(`/admin/events/${created.id}`)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '创建失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto max-w-6xl p-6 md:p-10">
    <header class="mb-8 flex flex-wrap items-center justify-between gap-4">
      <div>
        <p class="text-sm font-semibold text-blue-600 dark:text-blue-400">
          PrizePass 后台
        </p>
        <h1 class="mt-1 text-3xl font-bold">比赛</h1>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="btn-secondary"
          type="button"
          :disabled="loading"
          @click="refreshList"
        >
          刷新状态</button
        ><RouterLink class="btn-secondary" to="/admin/settings/notifications"
          >通知设置</RouterLink
        ><button class="btn-primary" @click="showCreate = true">
          新建比赛
        </button>
      </div>
    </header>

    <p
      v-if="error"
      class="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
    >
      {{ error }}
    </p>
    <section v-if="loading" class="card text-slate-500 dark:text-slate-400">
      正在加载比赛…
    </section>
    <section v-else-if="events.length === 0" class="card text-center">
      <h2 class="text-lg font-semibold">还没有比赛</h2>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
        创建第一场比赛并配置自提信息与奖品。
      </p>
    </section>
    <section v-else class="grid gap-4">
      <RouterLink
        v-for="event in events"
        :key="event.id"
        :to="`/admin/events/${event.id}`"
        class="card flex flex-wrap items-center justify-between gap-4 transition hover:border-blue-300 hover:shadow-md"
      >
        <div>
          <div class="flex items-center gap-3">
            <h2 class="text-lg font-semibold">{{ event.name }}</h2>
            <span
              class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium dark:bg-slate-800 dark:text-slate-300"
              >{{ statusLabel(event.status) }}</span
            >
          </div>
          <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
            截止 {{ localTime(event.redemption_deadline) }}
          </p>
        </div>
        <div class="flex gap-6 text-center text-sm sm:gap-8">
          <div>
            <strong class="block text-xl">{{ event.winner_count }}</strong
            ><span class="text-slate-500 dark:text-slate-400">获奖人</span>
          </div>
          <div>
            <strong class="block text-xl">{{ event.redemption_count }}</strong
            ><span class="text-slate-500 dark:text-slate-400">兑换</span>
          </div>
        </div>
      </RouterLink>
    </section>

    <div
      v-if="showCreate"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showCreate = false"
    >
      <form
        class="card max-h-[90vh] w-full max-w-xl overflow-auto"
        @submit.prevent="createEvent"
      >
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">新建比赛</h2>
          <button
            type="button"
            class="text-slate-500 dark:text-slate-400"
            @click="showCreate = false"
          >
            关闭
          </button>
        </div>
        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium"
            >名称<input
              v-model="form.name"
              class="field mt-1"
              maxlength="200"
              required
          /></label>
          <label class="text-sm font-medium"
            >说明<textarea
              v-model="form.description"
              class="field mt-1"
              rows="3"
            />
          </label>
          <label class="text-sm font-medium"
            >兑换截止时间<input
              v-model="form.redemption_deadline"
              class="field mt-1"
              type="datetime-local"
              required
          /></label>
          <label class="text-sm font-medium"
            >自提地点<textarea
              v-model="form.pickup_location"
              class="field mt-1"
              rows="2"
              required
            />
          </label>
          <label class="text-sm font-medium"
            >自提说明<textarea
              v-model="form.pickup_instructions"
              class="field mt-1"
              rows="3"
              required
            />
          </label>
          <label class="text-sm font-medium"
            >比赛总预算（元）<input
              v-model="budgetYuan"
              class="field mt-1"
              inputmode="decimal"
              required
          /></label>
        </div>
        <button class="btn-primary mt-6 w-full" :disabled="busy">
          {{ busy ? '创建中…' : '创建草稿' }}
        </button>
      </form>
    </div>
  </main>
</template>
