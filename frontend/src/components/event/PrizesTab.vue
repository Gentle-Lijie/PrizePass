<script setup lang="ts">
import { push } from 'notivue'
import { computed, inject, onMounted, ref } from 'vue'

import { api } from '@/api/client'
import type { PrizeRecord } from '@/api/types'
import { eventTabContextKey } from '@/components/event/eventContext'

const context = inject(eventTabContextKey)!
const { eventId, busy } = context

interface PrizeAvailability extends PrizeRecord {
  available_for_event: boolean
}

const allPrizes = ref<PrizeAvailability[]>([])
const loading = ref(true)

const showAddModal = ref(false)
const searchQuery = ref('')
const selectedAddIds = ref(new Set<number>())
const selectedRemoveIds = ref(new Set<number>())

const availablePrizes = computed(() => allPrizes.value.filter((p) => p.available_for_event))

async function loadPrizes() {
  loading.value = true
  try {
    allPrizes.value = await api<PrizeAvailability[]>(`/api/admin/events/${eventId}/prizes/available`)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function money(cents: number) {
  return `¥${(cents / 100).toFixed(2)}`
}

async function removePrize(prize: PrizeAvailability) {
  if (!window.confirm(`确认从本比赛移除"${prize.name}"？`)) return
  busy.value = true
  try {
    await api(`/api/admin/events/${eventId}/prizes/${prize.id}`, {
      method: 'DELETE',
    })
    prize.available_for_event = false
    push.success(`已从本比赛移除"${prize.name}"`)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    busy.value = false
  }
}

async function batchRemovePrizes() {
  const ids = [...selectedRemoveIds.value]
  if (!window.confirm(`确认从本比赛移除选中的 ${ids.length} 个奖品？`)) return
  busy.value = true
  try {
    await Promise.all(ids.map((id) => api(`/api/admin/events/${eventId}/prizes/${id}`, { method: 'DELETE' })))
    allPrizes.value.forEach((p) => {
      if (ids.includes(p.id)) p.available_for_event = false
    })
    selectedRemoveIds.value = new Set()
    push.success(`已从本比赛移除 ${ids.length} 个奖品`)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '批量移除失败')
  } finally {
    busy.value = false
  }
}

function toggleRemoveSelected(id: number, checked: boolean) {
  const next = new Set(selectedRemoveIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedRemoveIds.value = next
}

function toggleAllRemoveSelected(checked: boolean) {
  selectedRemoveIds.value = checked ? new Set(availablePrizes.value.map((p) => p.id)) : new Set<number>()
}

function filteredUnavailablePrizes() {
  const q = searchQuery.value.toLowerCase().trim()
  const pool = allPrizes.value.filter((p) => !p.available_for_event)
  if (!q) return pool
  return pool.filter(
    (p) =>
      p.name.toLowerCase().includes(q) ||
      (p.tag || '').toLowerCase().includes(q) ||
      (p.description || '').toLowerCase().includes(q),
  )
}

function toggleAddSelected(id: number, checked: boolean) {
  const next = new Set(selectedAddIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedAddIds.value = next
}

function toggleAllAddSelected(checked: boolean) {
  const filtered = filteredUnavailablePrizes()
  selectedAddIds.value = checked ? new Set(filtered.map((p) => p.id)) : new Set<number>()
}

async function batchAddPrizes() {
  const ids = [...selectedAddIds.value]
  if (ids.length === 0) return
  busy.value = true
  try {
    await Promise.all(ids.map((id) => api(`/api/admin/events/${eventId}/prizes/${id}`, { method: 'POST' })))
    allPrizes.value.forEach((p) => {
      if (ids.includes(p.id)) p.available_for_event = true
    })
    selectedAddIds.value = new Set()
    showAddModal.value = false
    push.success(`已添加 ${ids.length} 个奖品到本比赛`)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '批量添加失败')
  } finally {
    busy.value = false
  }
}

async function openAddModal() {
  searchQuery.value = ''
  selectedAddIds.value = new Set()
  showAddModal.value = true
}

onMounted(loadPrizes)
</script>

<template>
  <section class="mt-6">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold">本比赛可用奖品</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          只有标记为"可用"的奖品才会出现在获奖人的兑换页面。
        </p>
      </div>
      <div class="flex gap-2">
        <button
          v-if="selectedRemoveIds.size > 0"
          class="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:border-red-900/60 dark:bg-slate-900 dark:text-red-300 dark:hover:bg-red-950/40"
          :disabled="busy"
          @click="batchRemovePrizes"
        >
          批量移除 ({{ selectedRemoveIds.size }})
        </button>
        <button class="btn-primary" :disabled="busy" @click="openAddModal">添加奖品</button>
      </div>
    </div>

    <div
      v-if="loading"
      class="rounded-lg border border-slate-200 bg-white p-12 text-center dark:border-slate-700 dark:bg-slate-800"
    >
      <p class="text-slate-500 dark:text-slate-400">加载奖品列表...</p>
    </div>

    <template v-else>
      <div
        v-if="availablePrizes.length > 0"
        class="overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
      >
        <table class="w-full min-w-[900px] text-left text-sm">
          <thead class="bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            <tr>
              <th class="w-10 p-4">
                <input
                  type="checkbox"
                  :checked="availablePrizes.length > 0 && selectedRemoveIds.size === availablePrizes.length"
                  aria-label="全选"
                  @change="toggleAllRemoveSelected(($event.target as HTMLInputElement).checked)"
                />
              </th>
              <th class="p-4">奖品</th>
              <th class="p-4">标签</th>
              <th class="p-4 text-right">采购价</th>
              <th class="p-4 text-right">抵扣</th>
              <th class="p-4 text-right">库存</th>
              <th class="p-4 text-center">状态</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="prize in availablePrizes"
              :key="prize.id"
              class="border-t border-slate-100 dark:border-slate-800"
            >
              <td class="p-4">
                <input
                  type="checkbox"
                  :checked="selectedRemoveIds.has(prize.id)"
                  :aria-label="`选择 ${prize.name}`"
                  @change="toggleRemoveSelected(prize.id, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td class="p-4">
                <div class="flex items-center gap-3">
                  <img :src="prize.image" :alt="prize.name" class="h-12 w-12 rounded-lg object-cover" />
                  <div>
                    <strong>{{ prize.name }}</strong>
                    <p class="max-w-xs truncate text-xs text-slate-500 dark:text-slate-400">
                      {{ prize.description }}
                    </p>
                  </div>
                </div>
              </td>
              <td class="p-4">
                <span
                  v-if="prize.tag"
                  class="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-950/40 dark:text-blue-300"
                >
                  {{ prize.tag }}
                </span>
                <span v-else class="text-slate-400">—</span>
              </td>
              <td class="p-4 text-right">{{ money(prize.real_value) }}</td>
              <td class="p-4 text-right">{{ prize.redeem_value }}</td>
              <td
                class="p-4 text-right"
                :class="prize.stock < 0 ? 'font-medium text-amber-600 dark:text-amber-400' : ''"
              >
                {{ prize.stock < 0 ? `待采购 ${Math.abs(prize.stock)}` : prize.stock }}
              </td>
              <td class="p-4 text-center">
                <span
                  :class="
                    prize.is_active
                      ? 'rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300'
                      : 'rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                  "
                >
                  {{ prize.is_active ? '上架' : '下架' }}
                </span>
              </td>
              <td class="p-4 text-right">
                <button class="text-red-600 dark:text-red-400" :disabled="busy" @click="removePrize(prize)">
                  移除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-else
        class="rounded-lg border border-slate-200 bg-white p-12 text-center dark:border-slate-700 dark:bg-slate-800"
      >
        <p class="text-slate-500 dark:text-slate-400">本比赛暂无可用奖品</p>
        <p class="mt-2 text-sm text-slate-400 dark:text-slate-500">点击"添加奖品"从全局奖品池中选择。</p>
      </div>
    </template>

    <!-- Add prize modal -->
    <div
      v-if="showAddModal"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showAddModal = false"
    >
      <div class="card w-full max-w-3xl max-h-[80vh] overflow-auto">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">添加奖品</h2>
          <button type="button" @click="showAddModal = false">关闭</button>
        </div>

        <div class="mt-4">
          <input v-model="searchQuery" class="field w-full" placeholder="搜索奖品名称、标签或描述..." />
        </div>

        <div class="mt-4 flex items-center gap-3">
          <span class="text-sm text-slate-500 dark:text-slate-400"> 已选 {{ selectedAddIds.size }} 项 </span>
          <button
            v-if="selectedAddIds.size > 0"
            class="rounded-lg border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            @click="selectedAddIds = new Set()"
          >
            清除选择
          </button>
        </div>

        <div
          v-if="filteredUnavailablePrizes().length === 0"
          class="mt-4 p-6 text-center text-sm text-slate-500 dark:text-slate-400"
        >
          {{ allPrizes.every((p) => p.available_for_event) ? '所有奖品已添加' : '没有匹配的奖品' }}
        </div>

        <div v-else class="mt-4 max-h-[40vh] overflow-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table class="w-full min-w-[600px] text-left text-sm">
            <thead class="bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
              <tr>
                <th class="w-10 p-3">
                  <input
                    type="checkbox"
                    :checked="
                      filteredUnavailablePrizes().length > 0 &&
                      selectedAddIds.size === filteredUnavailablePrizes().length
                    "
                    aria-label="全选"
                    @change="toggleAllAddSelected(($event.target as HTMLInputElement).checked)"
                  />
                </th>
                <th class="p-3">奖品</th>
                <th class="p-3">标签</th>
                <th class="p-3 text-right">采购价</th>
                <th class="p-3 text-right">抵扣</th>
                <th class="p-3 text-right">库存</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="prize in filteredUnavailablePrizes()"
                :key="prize.id"
                class="border-t border-slate-100 dark:border-slate-800"
              >
                <td class="p-3">
                  <input
                    type="checkbox"
                    :checked="selectedAddIds.has(prize.id)"
                    :aria-label="`选择 ${prize.name}`"
                    @change="toggleAddSelected(prize.id, ($event.target as HTMLInputElement).checked)"
                  />
                </td>
                <td class="p-3">
                  <div class="flex items-center gap-2">
                    <img :src="prize.image" :alt="prize.name" class="h-8 w-8 rounded object-cover" />
                    <div>
                      <strong>{{ prize.name }}</strong>
                      <p class="truncate text-xs text-slate-500 dark:text-slate-400">
                        {{ prize.description }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="p-3">
                  <span
                    v-if="prize.tag"
                    class="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600 dark:bg-blue-950/40 dark:text-blue-300"
                  >
                    {{ prize.tag }}
                  </span>
                  <span v-else class="text-slate-400">—</span>
                </td>
                <td class="p-3 text-right">{{ money(prize.real_value) }}</td>
                <td class="p-3 text-right">{{ prize.redeem_value }}</td>
                <td class="p-3 text-right" :class="prize.stock < 0 ? 'text-amber-600 dark:text-amber-400' : ''">
                  {{ prize.stock < 0 ? `待采购 ${Math.abs(prize.stock)}` : prize.stock }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 flex justify-end gap-2">
          <button class="btn-secondary" @click="showAddModal = false">取消</button>
          <button class="btn-primary" :disabled="busy || selectedAddIds.size === 0" @click="batchAddPrizes">
            {{ busy ? '添加中…' : `添加 ${selectedAddIds.size > 0 ? selectedAddIds.size + ' 个' : ''}奖品` }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
