<script setup lang="ts">
import { inject, reactive, ref } from 'vue'

import { api, downloadAdmin } from '@/api/client'
import type {
  NotificationChannel,
  WinnerCreate,
  WinnerImportPreview,
  WinnerRecord,
} from '@/api/types'
import { eventTabContextKey } from '@/components/event/eventContext'

const context = inject(eventTabContextKey)!
const { eventId, winners, error, notice, busy, load } = context

const winnerImportFile = ref<File | null>(null)
const winnerImportPreview = ref<WinnerImportPreview | null>(null)
const notifyingWinner = ref<WinnerRecord | null>(null)
const notificationChannels = ref<NotificationChannel[]>(['email'])
const showWinnerForm = ref(false)
const winnerForm = reactive<WinnerCreate>({
  external_id: '',
  name: '',
  email: '',
  quota: 1,
})

function showError(caught: unknown, fallback: string) {
  error.value = caught instanceof Error ? caught.message : fallback
}

async function validateWinnerImport(file: File | undefined) {
  if (!file) return
  winnerImportFile.value = file
  winnerImportPreview.value = null
  error.value = ''
  const data = new FormData()
  data.append('file', file)
  try {
    winnerImportPreview.value = await api<WinnerImportPreview>(
      `/api/admin/events/${eventId}/winners/import/validate`,
      { method: 'POST', body: data },
    )
  } catch (caught) {
    showError(caught, '校验失败')
  }
}

async function confirmWinnerImport() {
  if (!winnerImportFile.value || !winnerImportPreview.value?.valid) return
  const data = new FormData()
  data.append('file', winnerImportFile.value)
  busy.value = true
  try {
    const result = await api<{ imported: number }>(
      `/api/admin/events/${eventId}/winners/import/confirm`,
      { method: 'POST', body: data },
    )
    notice.value = `已导入 ${result.imported} 名获奖人并生成兑换码`
    winnerImportFile.value = null
    winnerImportPreview.value = null
    await load()
  } catch (caught) {
    showError(caught, '导入失败')
  } finally {
    busy.value = false
  }
}

function openWinnerForm() {
  Object.assign(winnerForm, { external_id: '', name: '', email: '', quota: 1 })
  showWinnerForm.value = true
}

async function saveWinner() {
  const payload: WinnerCreate = {
    external_id: (winnerForm.external_id ?? '').trim() || null,
    name: winnerForm.name.trim(),
    email: winnerForm.email.trim(),
    quota: Number(winnerForm.quota),
  }
  busy.value = true
  error.value = ''
  try {
    await api(`/api/admin/events/${eventId}/winners`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    notice.value = '已添加获奖人并生成兑换码'
    showWinnerForm.value = false
    await load()
  } catch (caught) {
    showError(caught, '添加失败')
  } finally {
    busy.value = false
  }
}

async function copyCode(code: string) {
  await navigator.clipboard.writeText(code)
  notice.value = '兑换码已复制'
}

function codeStatusLabel(status: WinnerRecord['code_status']) {
  return { issued: '可使用', redeemed: '已兑换', disabled: '已撤销' }[status]
}

function notificationStatusLabel(status: string) {
  return (
    {
      pending: '待发送',
      sending: '发送中',
      retrying: '重试中',
      sent: '已发送',
      failed: '发送失败',
    }[status] ?? status
  )
}

function openResend(winner: WinnerRecord) {
  notifyingWinner.value = winner
  notificationChannels.value = ['email']
}

async function resendNotification() {
  if (!notifyingWinner.value || notificationChannels.value.length === 0) return
  busy.value = true
  error.value = ''
  try {
    const result = await api<{ queued: number }>(
      `/api/admin/winners/${notifyingWinner.value.id}/notifications/resend`,
      {
        method: 'POST',
        body: JSON.stringify({ channels: notificationChannels.value }),
      },
    )
    notice.value = `已创建 ${result.queued} 条通知任务`
    notifyingWinner.value = null
    await load()
  } catch (caught) {
    showError(caught, '重新通知失败')
  } finally {
    busy.value = false
  }
}

async function adjustQuota(winner: WinnerRecord) {
  const value = window.prompt(
    `请输入 ${winner.name} 的新额度`,
    String(winner.quota),
  )
  if (value === null) return
  const quota = Number(value)
  if (!Number.isInteger(quota) || quota <= 0) {
    error.value = '额度必须是大于 0 的整数'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await api(`/api/admin/winners/${winner.id}/quota`, {
      method: 'PUT',
      body: JSON.stringify({ quota }),
    })
    notice.value = `已将 ${winner.name} 的额度调整为 ${quota}`
    await load()
  } catch (caught) {
    showError(caught, '调整额度失败')
  } finally {
    busy.value = false
  }
}

async function revokeCode(winner: WinnerRecord) {
  if (
    !window.confirm(
      `确认撤销 ${winner.name} 的兑换码 ${winner.code}？撤销后该码将无法兑换。`,
    )
  )
    return
  busy.value = true
  error.value = ''
  try {
    await api(`/api/admin/winners/${winner.id}/code/revoke`, { method: 'POST' })
    notice.value = `已撤销 ${winner.name} 的兑换码`
    await load()
  } catch (caught) {
    showError(caught, '撤销兑换码失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="mt-6">
    <div class="flex flex-wrap gap-2">
      <button
        class="btn-secondary"
        @click="
          downloadAdmin(
            `/api/admin/events/${eventId}/winners/import/template?format=csv`,
            'winners-template.csv',
          )
        "
      >
        CSV 模板
      </button>
      <button
        class="btn-secondary"
        @click="
          downloadAdmin(
            `/api/admin/events/${eventId}/winners/import/template?format=xlsx`,
            'winners-template.xlsx',
          )
        "
      >
        XLSX 模板
      </button>
      <button
        class="btn-secondary"
        @click="
          downloadAdmin(
            `/api/admin/events/${eventId}/winners/export?format=csv`,
            'winners.csv',
          )
        "
      >
        导出 CSV
      </button>
      <button
        class="btn-secondary"
        @click="
          downloadAdmin(
            `/api/admin/events/${eventId}/winners/export?format=xlsx`,
            'winners.xlsx',
          )
        "
      >
        导出 XLSX
      </button>
      <label class="btn-primary cursor-pointer"
        >导入获奖人<input
          class="hidden"
          type="file"
          accept=".csv,.xlsx"
          @change="
            validateWinnerImport(
              ($event.target as HTMLInputElement).files?.[0],
            )
          "
      /></label>
      <button class="btn-secondary" @click="openWinnerForm()">
        添加获奖人
      </button>
    </div>
    <div v-if="winnerImportPreview" class="card mt-4">
      <h3 class="font-semibold">
        导入预览 · {{ winnerImportPreview.count }} 人 · quota 合计
        {{ winnerImportPreview.quota_total }}
      </h3>
      <ul
        v-if="winnerImportPreview.errors.length"
        class="mt-3 space-y-1 text-sm text-red-700 dark:text-red-300"
      >
        <li
          v-for="issue in winnerImportPreview.errors"
          :key="`${issue.row}-${issue.field}-${issue.message}`"
        >
          第 {{ issue.row }} 行 · {{ issue.field }}：{{ issue.message }}
        </li>
      </ul>
      <div class="mt-4 max-h-48 overflow-auto">
        <table class="w-full text-left text-sm">
          <thead class="text-slate-600 dark:text-slate-300">
            <tr>
              <th class="p-2">external_id</th>
              <th class="p-2">姓名</th>
              <th class="p-2">邮箱</th>
              <th class="p-2">quota</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in winnerImportPreview.rows"
              :key="index"
              class="border-t border-slate-200 dark:border-slate-700"
            >
              <td class="p-2">{{ row.external_id || '—' }}</td>
              <td class="p-2">{{ row.name }}</td>
              <td class="p-2">{{ row.email }}</td>
              <td class="p-2">{{ row.quota }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <button
        class="btn-primary mt-4"
        :disabled="!winnerImportPreview.valid || busy"
        @click="confirmWinnerImport"
      >
        确认全部导入并发码
      </button>
    </div>
    <div
      class="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
    >
      <table class="w-full min-w-[1180px] text-left text-sm">
        <thead
          class="bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300"
        >
          <tr>
            <th class="p-4">姓名</th>
            <th class="p-4">邮箱</th>
            <th class="p-4">额度</th>
            <th class="p-4">兑换码</th>
            <th class="p-4">码状态</th>
            <th class="p-4">邮件</th>
            <th class="p-4">Webhook</th>
            <th class="p-4 text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="winner in winners" :key="winner.id" class="border-t">
            <td class="p-4 font-medium">{{ winner.name }}</td>
            <td class="p-4">{{ winner.email }}</td>
            <td class="p-4">{{ winner.quota }}</td>
            <td class="p-4">
              <button
                class="font-mono font-semibold text-blue-600 dark:text-blue-400"
                @click="copyCode(winner.code)"
              >
                {{ winner.code }}
              </button>
            </td>
            <td class="p-4">{{ codeStatusLabel(winner.code_status) }}</td>
            <td class="p-4">
              {{ notificationStatusLabel(winner.email_notification_status) }}
            </td>
            <td class="p-4">
              {{
                notificationStatusLabel(winner.webhook_notification_status)
              }}
            </td>
            <td class="whitespace-nowrap p-4 text-right">
              <button
                class="text-blue-600 dark:text-blue-400 disabled:text-slate-300"
                :disabled="winner.code_status !== 'issued' || busy"
                @click="openResend(winner)"
              >
                重新通知</button
              ><button
                class="ml-4 text-blue-600 dark:text-blue-400 disabled:text-slate-300"
                :disabled="winner.code_status !== 'issued' || busy"
                @click="adjustQuota(winner)"
              >
                调整额度</button
              ><button
                class="ml-4 text-red-600 dark:text-red-400 disabled:text-slate-300"
                :disabled="winner.code_status !== 'issued' || busy"
                @click="revokeCode(winner)"
              >
                撤销兑换码
              </button>
            </td>
          </tr>
          <tr v-if="winners.length === 0">
            <td
              colspan="8"
              class="p-10 text-center text-slate-500 dark:text-slate-400"
            >
              暂无获奖人，请先下载模板并导入
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="showWinnerForm"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showWinnerForm = false"
    >
      <form class="card w-full max-w-md" @submit.prevent="saveWinner">
        <div class="flex justify-between">
          <h2 class="text-xl font-bold">添加获奖人</h2>
          <button type="button" @click="showWinnerForm = false">关闭</button>
        </div>
        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium"
            >姓名<input
              v-model="winnerForm.name"
              class="field mt-1"
              maxlength="100"
              required
          /></label>
          <label class="text-sm font-medium"
            >邮箱<input
              v-model="winnerForm.email"
              class="field mt-1"
              type="email"
              maxlength="320"
              required
          /></label>
          <label class="text-sm font-medium"
            >额度<input
              v-model.number="winnerForm.quota"
              class="field mt-1"
              type="number"
              min="1"
              step="1"
              required
          /></label>
          <label class="text-sm font-medium"
            >external_id（选填）<input
              v-model="winnerForm.external_id"
              class="field mt-1"
              maxlength="200"
            /><span
              class="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400"
              >留空则以邮箱作为去重标识</span
            ></label
          >
        </div>
        <button class="btn-primary mt-6 w-full" :disabled="busy">
          添加并发码
        </button>
      </form>
    </div>
    <div
      v-if="notifyingWinner"
      class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4"
      @click.self="notifyingWinner = null"
    >
      <form class="card w-full max-w-md" @submit.prevent="resendNotification">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-xl font-bold">重新发送兑换通知</h2>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {{ notifyingWinner.name }} · {{ notifyingWinner.email }}
            </p>
          </div>
          <button type="button" @click="notifyingWinner = null">关闭</button>
        </div>
        <fieldset class="mt-5">
          <legend class="text-sm font-medium">选择通知渠道</legend>
          <div
            class="mt-3 grid gap-3 rounded-lg bg-slate-50 p-4 text-sm dark:bg-slate-800"
          >
            <label class="flex items-center gap-2"
              ><input
                v-model="notificationChannels"
                type="checkbox"
                value="email"
              />
              SMTP 邮件</label
            ><label class="flex items-center gap-2"
              ><input
                v-model="notificationChannels"
                type="checkbox"
                value="email_poster"
              />
              Email Poster</label
            ><label class="flex items-center gap-2"
              ><input
                v-model="notificationChannels"
                type="checkbox"
                value="webhook"
              />
              Webhook</label
            >
          </div>
        </fieldset>
        <button
          class="btn-primary mt-6 w-full"
          :disabled="busy || notificationChannels.length === 0"
        >
          创建通知任务
        </button>
      </form>
    </div>
  </section>
</template>
