<script setup lang="ts">
import { onMounted, provide, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import type {
  AdminRedemption,
  EventRecord,
  PrizeRecord,
  PrizeSummary,
  WinnerRecord,
} from '@/api/types'
import PrizesTab from '@/components/event/PrizesTab.vue'
import RedemptionsTab from '@/components/event/RedemptionsTab.vue'
import SettingsTab from '@/components/event/SettingsTab.vue'
import WinnersTab from '@/components/event/WinnersTab.vue'
import {
  eventTabContextKey,
  type EventTabContext,
} from '@/components/event/eventContext'
import { useAuthStore } from '@/stores/auth'
import { statusLabel } from '@/utils/labels'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const eventId = Number(route.params.id)
const event = ref<EventRecord | null>(null)
const prizes = ref<PrizeRecord[]>([])
const winners = ref<WinnerRecord[]>([])
const redemptions = ref<AdminRedemption[]>([])
const prizeSummary = ref<PrizeSummary>({
  total_purchase_value: 0,
  claimed_purchase_value: 0,
  budget: 0,
})
const tab = ref<'prizes' | 'winners' | 'redemptions' | 'settings'>('prizes')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const refreshHooks = new Set<() => void>()

function showError(caught: unknown, fallback: string) {
  error.value = caught instanceof Error ? caught.message : fallback
}

async function load() {
  if (!auth.adminPassword) {
    await router.replace('/admin')
    return
  }
  try {
    const [eventData, prizeData, summaryData, winnerData, redemptionData] =
      await Promise.all([
        api<EventRecord>(`/api/admin/events/${eventId}`),
        api<PrizeRecord[]>(`/api/admin/events/${eventId}/prizes`),
        api<PrizeSummary>(`/api/admin/events/${eventId}/prizes/summary`),
        api<WinnerRecord[]>(`/api/admin/events/${eventId}/winners`),
        api<AdminRedemption[]>(`/api/admin/events/${eventId}/redemptions`),
      ])
    event.value = eventData
    prizes.value = prizeData
    prizeSummary.value = summaryData
    winners.value = winnerData
    redemptions.value = redemptionData
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401)
      await router.replace('/admin')
    else showError(caught, '加载失败')
  }
}

async function refresh() {
  await load()
  for (const hook of refreshHooks) hook()
}

provide(eventTabContextKey, {
  eventId,
  event,
  prizes,
  prizeSummary,
  winners,
  redemptions,
  error,
  notice,
  busy,
  load,
  refresh,
  refreshHooks,
} satisfies EventTabContext)

async function refreshForm() {
  busy.value = true
  error.value = ''
  try {
    await refresh()
    notice.value = '表单数据已刷新'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto max-w-7xl p-6 md:p-10">
    <div class="flex flex-wrap justify-between gap-3">
      <RouterLink
        to="/admin/events"
        class="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >← 返回比赛列表</RouterLink
      ><RouterLink
        to="/admin/settings/notifications"
        class="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >通知设置</RouterLink
      >
    </div>
    <header
      v-if="event"
      class="mt-4 flex flex-wrap items-end justify-between gap-4"
    >
      <div>
        <div class="flex items-center gap-3">
          <h1 class="text-3xl font-bold">{{ event.name }}</h1>
          <span
            class="rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800 dark:text-slate-300"
            >{{ statusLabel(event.status) }}</span
          >
        </div>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
          兑换截止 {{ new Date(event.redemption_deadline).toLocaleString() }}
        </p>
      </div>
      <button
        class="btn-secondary"
        type="button"
        :disabled="busy"
        @click="refreshForm"
      >
        {{ busy ? '刷新中…' : '刷新表单' }}
      </button>
    </header>
    <p
      v-if="error"
      class="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
    >
      {{ notice }}
    </p>

    <nav
      class="mt-8 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700"
    >
      <button
        v-for="item in [
          { key: 'prizes', label: '奖品' },
          { key: 'winners', label: '获奖人' },
          { key: 'redemptions', label: '兑换记录' },
          { key: 'settings', label: '比赛设置' },
        ]"
        :key="item.key"
        class="shrink-0 border-b-2 px-3 py-3 text-sm font-medium sm:px-4"
        :class="
          tab === item.key
            ? 'border-blue-600 text-blue-600 dark:text-blue-400'
            : 'border-transparent text-slate-500 dark:text-slate-400'
        "
        @click="tab = item.key as typeof tab"
      >
        {{ item.label }}
      </button>
    </nav>

    <PrizesTab v-if="tab === 'prizes'" />
    <WinnersTab v-else-if="tab === 'winners'" />
    <RedemptionsTab v-else-if="tab === 'redemptions'" />
    <SettingsTab v-else />
  </main>
</template>
