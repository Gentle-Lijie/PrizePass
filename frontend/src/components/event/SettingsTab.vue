<script setup lang="ts">
import { computed, inject, reactive, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { EventStatus, EventWrite } from '@/api/types'
import { eventTabContextKey } from '@/components/event/eventContext'
import { statusLabel } from '@/utils/labels'

const context = inject(eventTabContextKey)!
const { eventId, event, error, notice, busy, load, refresh } = context

const eventForm = reactive<EventWrite>({
  name: '',
  description: null,
  status: 'draft',
  redemption_deadline: '',
  pickup_location: '',
  pickup_instructions: '',
  budget: 0,
})
const eventBudgetYuan = ref('0.00')

const allowedStatuses = computed<EventStatus[]>(() => {
  if (!event.value) return ['draft']
  return {
    draft: ['draft', 'active'],
    active: ['active', 'closed'],
    closed: ['closed', 'active'],
  }[event.value.status] as EventStatus[]
})

function toLocalInput(value: string) {
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

// Keep the form in sync whenever a reload replaces the event record.
watch(
  event,
  (data) => {
    if (!data) return
    Object.assign(eventForm, {
      name: data.name,
      description: data.description,
      status: data.status,
      redemption_deadline: toLocalInput(data.redemption_deadline),
      pickup_location: data.pickup_location,
      pickup_instructions: data.pickup_instructions,
      budget: data.budget,
    })
    eventBudgetYuan.value = (data.budget / 100).toFixed(2)
  },
  { immediate: true },
)

function showError(caught: unknown, fallback: string) {
  error.value = caught instanceof Error ? caught.message : fallback
}

async function saveEvent() {
  const budget = Math.round(Number(eventBudgetYuan.value) * 100)
  if (!Number.isFinite(budget) || budget < 0 || !/^\d+(\.\d{1,2})?$/.test(eventBudgetYuan.value)) {
    error.value = '比赛总预算必须是最多两位小数的非负金额'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await api(`/api/admin/events/${eventId}`, {
      method: 'PUT',
      body: JSON.stringify({
        ...eventForm,
        budget,
        redemption_deadline: new Date(eventForm.redemption_deadline).toISOString(),
      }),
    })
    notice.value = '比赛设置已保存'
    await load()
  } catch (caught) {
    showError(caught, '保存失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="card mt-6 w-full max-w-2xl" @submit.prevent="saveEvent">
    <div class="grid gap-4">
      <label class="text-sm font-medium"
        >名称<input v-model="eventForm.name" class="field mt-1" maxlength="200" required
      /></label>
      <label class="text-sm font-medium"
        >说明<textarea v-model="eventForm.description" class="field mt-1" rows="3" />
      </label>
      <label class="text-sm font-medium"
        >兑换截止时间<input v-model="eventForm.redemption_deadline" class="field mt-1" type="datetime-local" required
      /></label>
      <label class="text-sm font-medium"
        >固定自提地点<textarea v-model="eventForm.pickup_location" class="field mt-1" rows="2" required />
      </label>
      <label class="text-sm font-medium"
        >自提说明<textarea v-model="eventForm.pickup_instructions" class="field mt-1" rows="3" required />
      </label>
      <label class="text-sm font-medium"
        >比赛总预算（元）<input v-model="eventBudgetYuan" class="field mt-1" inputmode="decimal" required /><span
          class="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400"
          >用于对比奖品采购总额并提示预算余量</span
        ></label
      >
      <label class="text-sm font-medium"
        >状态<select v-model="eventForm.status" class="field mt-1">
          <option v-for="status in allowedStatuses" :key="status" :value="status">
            {{ statusLabel(status) }}
          </option>
        </select></label
      >
    </div>
    <div class="mt-6 flex flex-col gap-2 sm:flex-row">
      <button class="btn-primary" :disabled="busy">保存比赛设置</button
      ><button class="btn-secondary" type="button" :disabled="busy" @click="refresh">刷新表单</button>
    </div>
  </form>
</template>
