<script setup lang="ts">
import { push } from 'notivue'
import { inject, onMounted, onUnmounted, ref } from 'vue'

import { api, downloadAdmin } from '@/api/client'
import type { AdminRedemption, AdminRedemptionStatus } from '@/api/types'
import { eventTabContextKey } from '@/components/event/eventContext'
import { exportFilename } from '@/utils/filename'

const context = inject(eventTabContextKey)!
const { eventId, event, redemptions, busy, load, refresh, refreshHooks } = context

const selectedRedemption = ref<AdminRedemption | null>(null)
const redemptionStatus = ref<AdminRedemptionStatus | ''>('')
const redemptionSearch = ref('')

function showError(caught: unknown, fallback: string) {
  push.error(caught instanceof Error ? caught.message : fallback)
}

function redemptionStatusLabel(status: AdminRedemptionStatus) {
  return {
    submitted: '已提交',
    ready: '待领取',
    picked_up: '已领取',
    cancelled: '已取消',
  }[status]
}

async function filterRedemptions() {
  const params = new URLSearchParams()
  if (redemptionStatus.value) params.set('status', redemptionStatus.value)
  if (redemptionSearch.value.trim()) params.set('search', redemptionSearch.value.trim())
  try {
    redemptions.value = await api<AdminRedemption[]>(`/api/admin/events/${eventId}/redemptions?${params}`)
  } catch (caught) {
    showError(caught, '加载兑换记录失败')
  }
}

async function openRedemption(id: number) {
  try {
    selectedRedemption.value = await api<AdminRedemption>(`/api/admin/redemptions/${id}`)
  } catch (caught) {
    showError(caught, '加载兑换详情失败')
  }
}

// Keep an open detail dialog in sync after a full refresh.
function reopenAfterRefresh() {
  if (selectedRedemption.value) void openRedemption(selectedRedemption.value.id)
}
onMounted(() => refreshHooks.add(reopenAfterRefresh))
onUnmounted(() => refreshHooks.delete(reopenAfterRefresh))

async function redemptionAction(redemption: AdminRedemption, action: 'ready' | 'pickup' | 'cancel') {
  const labels = redemption.custom_name
    ? {
        ready: '采纳该自定义奖品',
        pickup: '标记为已领取',
        cancel: '拒绝该自定义奖品并恢复兑换码',
      }
    : {
        ready: '标记为待领取',
        pickup: '标记为已领取',
        cancel: '取消兑换并恢复库存',
      }
  let reason: string | null = null
  if (action === 'cancel' && redemption.custom_name) {
    const input = window.prompt(`请输入驳回「${redemption.custom_name}」的原因（将通过邮件通知获奖人）`)
    if (input === null) return
    reason = input.trim()
    if (!reason) {
      push.error('驳回原因不能为空')
      return
    }
  } else if (!window.confirm(`确认${labels[action]}？`)) return
  busy.value = true
  try {
    await api(`/api/admin/redemptions/${redemption.id}/${action}`, {
      method: 'POST',
      ...(reason !== null ? { body: JSON.stringify({ reason }) } : {}),
    })
    push.success('兑换状态已更新')
    await load()
    await filterRedemptions()
    if (selectedRedemption.value) {
      const refreshed = redemptions.value.find((item) => item.id === redemption.id)
      selectedRedemption.value = refreshed
        ? await api<AdminRedemption>(`/api/admin/redemptions/${redemption.id}`)
        : null
    }
  } catch (caught) {
    showError(caught, '状态更新失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="mt-6">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <form class="flex flex-wrap items-end gap-2" @submit.prevent="filterRedemptions">
        <label class="text-sm"
          >状态<select v-model="redemptionStatus" class="field mt-1">
            <option value="">全部</option>
            <option value="submitted">已提交</option>
            <option value="ready">待领取</option>
            <option value="picked_up">已领取</option>
            <option value="cancelled">已取消</option>
          </select></label
        >
        <label class="text-sm"
          >兑换单号<input v-model="redemptionSearch" class="field mt-1" maxlength="24" placeholder="搜索单号"
        /></label>
        <button class="btn-secondary" type="submit">筛选</button>
      </form>
      <div class="flex gap-2">
        <button class="btn-secondary" type="button" :disabled="busy" @click="refresh">刷新状态</button
        ><button
          class="btn-secondary"
          @click="
            downloadAdmin(
              `/api/admin/events/${eventId}/redemptions/export?format=csv`,
              exportFilename('兑换记录', 'csv', event?.name),
            )
          "
        >
          导出 CSV</button
        ><button
          class="btn-secondary"
          @click="
            downloadAdmin(
              `/api/admin/events/${eventId}/redemptions/export?format=xlsx`,
              exportFilename('兑换记录', 'xlsx', event?.name),
            )
          "
        >
          导出 XLSX
        </button>
        <button
          class="btn-primary border border-transparent"
          title="导出所有已领取的兑换记录，用于采购报销"
          @click="
            downloadAdmin(
              `/api/admin/events/${eventId}/redemptions/reimbursement-export?format=xlsx`,
              exportFilename('报销', 'xlsx', event?.name),
            )
          "
        >
          导出报销 XLSX
        </button>
        <button
          class="btn-primary border border-transparent"
          title="导出所有已领取的兑换记录，用于采购报销"
          @click="
            downloadAdmin(
              `/api/admin/events/${eventId}/redemptions/reimbursement-export?format=csv`,
              exportFilename('报销', 'csv', event?.name),
            )
          "
        >
          导出报销 CSV
        </button>
      </div>
    </div>
    <div class="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
      <table class="w-full min-w-[1000px] text-left text-sm">
        <thead class="bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
          <tr>
            <th class="p-4">兑换单号</th>
            <th class="p-4">提交人</th>
            <th class="p-4">手机号</th>
            <th class="p-4">奖品</th>
            <th class="p-4">总抵扣</th>
            <th class="p-4">状态</th>
            <th class="p-4">提交时间</th>
            <th class="p-4 text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in redemptions" :key="record.id" class="border-t">
            <td class="p-4 font-mono">
              <button class="text-blue-600 dark:text-blue-400" @click="openRedemption(record.id)">
                {{ record.order_no }}
              </button>
            </td>
            <td class="p-4">{{ record.contact_name }}</td>
            <td class="p-4">{{ record.contact_phone }}</td>
            <td class="max-w-xs truncate p-4">{{ record.items_summary }}</td>
            <td class="p-4">{{ record.total_redeem_value }}</td>
            <td class="p-4">{{ redemptionStatusLabel(record.status) }}</td>

            <td class="p-4">
              {{ new Date(record.created_at).toLocaleString() }}
            </td>
            <td class="whitespace-nowrap p-4 text-right">
              <button
                v-if="record.status === 'submitted'"
                class="rounded-lg bg-blue-600 px-3 py-2 font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="busy"
                @click="redemptionAction(record, 'ready')"
              >
                {{ record.custom_name ? '采纳' : '已备货' }}</button
              ><button
                v-if="record.status === 'ready'"
                class="rounded-lg bg-emerald-600 px-3 py-2 font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="busy"
                @click="redemptionAction(record, 'pickup')"
              >
                已领取</button
              ><button
                v-if="record.status === 'submitted' || record.status === 'ready'"
                class="ml-3 text-red-600 dark:text-red-400"
                @click="redemptionAction(record, 'cancel')"
              >
                {{ record.custom_name ? '拒绝' : '取消' }}
              </button>
            </td>
          </tr>
          <tr v-if="redemptions.length === 0">
            <td colspan="8" class="p-10 text-center text-slate-500 dark:text-slate-400">暂无兑换记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="selectedRedemption"
      class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4"
      @click.self="selectedRedemption = null"
    >
      <section class="card max-h-[92vh] w-full max-w-2xl overflow-auto">
        <div class="flex items-start justify-between">
          <div>
            <p class="text-xs text-slate-500 dark:text-slate-400">兑换单号</p>
            <h2 class="font-mono text-xl font-bold">
              {{ selectedRedemption.order_no }}
            </h2>
          </div>
          <button @click="selectedRedemption = null">关闭</button>
        </div>
        <div class="mt-5 grid grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-slate-500 dark:text-slate-400">获奖人</span>
            <p>
              {{ selectedRedemption.winner_name }} ·
              {{ selectedRedemption.winner_email }}
            </p>
          </div>
          <div>
            <span class="text-slate-500 dark:text-slate-400">领取联系人</span>
            <p>
              {{ selectedRedemption.contact_name }} ·
              {{ selectedRedemption.contact_phone }}
            </p>
          </div>
          <div>
            <span class="text-slate-500 dark:text-slate-400">状态</span>
            <p>{{ redemptionStatusLabel(selectedRedemption.status) }}</p>
          </div>
          <div>
            <span class="text-slate-500 dark:text-slate-400">额度</span>
            <p>
              消耗 {{ selectedRedemption.total_redeem_value }} / {{ selectedRedemption.quota }}，未用
              {{ selectedRedemption.unused_quota }}
            </p>
          </div>
        </div>
        <p v-if="selectedRedemption.note" class="mt-4 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">
          备注：{{ selectedRedemption.note }}
        </p>
        <div v-if="selectedRedemption.custom_name" class="mt-5">
          <h3 class="font-semibold">自定义奖品</h3>
          <div class="mt-3 border-t pt-3 text-sm">
            <p>
              <strong>{{ selectedRedemption.custom_name }}</strong>
              <strong v-if="selectedRedemption.custom_price !== null" class="ml-2 text-blue-600 dark:text-blue-400"
                >¥{{ (selectedRedemption.custom_price / 100).toFixed(2) }}</strong
              >
              <a
                v-if="selectedRedemption.custom_url"
                :href="selectedRedemption.custom_url"
                target="_blank"
                rel="noopener noreferrer"
                class="ml-2 break-all text-blue-600 dark:text-blue-400"
                >打开链接 ↗</a
              >
            </p>
            <p v-if="selectedRedemption.custom_note" class="mt-2 text-slate-500 dark:text-slate-400">
              备注：{{ selectedRedemption.custom_note }}
            </p>
          </div>
        </div>
        <div v-if="selectedRedemption.items?.length" class="mt-5">
          <h3 class="font-semibold">奖品快照</h3>
          <div
            v-for="item in selectedRedemption.items"
            :key="item.id"
            class="mt-3 flex items-center gap-3 border-t pt-3"
          >
            <img :src="item.prize_image" :alt="item.prize_name" class="h-12 w-12 rounded object-cover" />
            <div class="flex-1">
              <strong>{{ item.prize_name }}</strong>
              <p class="text-xs text-slate-500 dark:text-slate-400">
                抵扣 {{ item.redeem_value }} × {{ item.quantity }}
              </p>
            </div>
            <strong>{{ item.line_redeem_value }}</strong>
          </div>
        </div>
        <div class="mt-5 rounded-lg bg-blue-50 p-4 text-sm dark:bg-blue-950/40">
          <strong>自提信息</strong>
          <p class="mt-1">{{ selectedRedemption.pickup_location }}</p>
          <p class="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-300">
            {{ selectedRedemption.pickup_instructions }}
          </p>
        </div>
        <div class="mt-5 flex flex-col justify-end gap-2 sm:flex-row">
          <button class="btn-secondary" type="button" :disabled="busy" @click="openRedemption(selectedRedemption.id)">
            刷新状态</button
          ><button
            v-if="selectedRedemption.status === 'submitted'"
            class="btn-primary"
            @click="redemptionAction(selectedRedemption, 'ready')"
          >
            {{ selectedRedemption.custom_name ? '采纳' : '标记待领取' }}</button
          ><button
            v-if="selectedRedemption.status === 'ready'"
            class="btn-primary"
            @click="redemptionAction(selectedRedemption, 'pickup')"
          >
            标记已领取</button
          ><button
            v-if="selectedRedemption.status === 'submitted' || selectedRedemption.status === 'ready'"
            class="btn-secondary text-red-600 dark:text-red-400"
            @click="redemptionAction(selectedRedemption, 'cancel')"
          >
            {{ selectedRedemption.custom_name ? '拒绝（恢复兑换码）' : '取消兑换' }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
