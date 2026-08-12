<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { api, ApiError, downloadAdmin } from '@/api/client'
import type { AdminRedemption, AdminRedemptionStatus, EventRecord, EventStatus, EventWrite, PrizeImportPreview, PrizeRecord, PrizeWrite, WinnerImportPreview, WinnerRecord } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const eventId = Number(route.params.id)
const event = ref<EventRecord | null>(null)
const prizes = ref<PrizeRecord[]>([])
const winners = ref<WinnerRecord[]>([])
const redemptions = ref<AdminRedemption[]>([])
const selectedRedemption = ref<AdminRedemption | null>(null)
const redemptionStatus = ref<AdminRedemptionStatus | ''>('')
const redemptionSearch = ref('')
const tab = ref<'prizes' | 'winners' | 'redemptions' | 'settings'>('prizes')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const editingPrize = ref<PrizeRecord | null>(null)
const showPrizeForm = ref(false)
const imageMode = ref<'url' | 'upload'>('url')
const importFile = ref<File | null>(null)
const importPreview = ref<PrizeImportPreview | null>(null)
const winnerImportFile = ref<File | null>(null)
const winnerImportPreview = ref<WinnerImportPreview | null>(null)

const eventForm = reactive<EventWrite>({ name: '', description: null, status: 'draft', redemption_deadline: '', pickup_location: '', pickup_instructions: '' })
const prizeForm = reactive({ name: '', image: '', realValueYuan: '0.00', redeem_value: 1, stock: 0, description: '' })

const allowedStatuses = computed<EventStatus[]>(() => {
  if (!event.value) return ['draft']
  return { draft: ['draft', 'active'], active: ['active', 'closed'], closed: ['closed', 'active'] }[event.value.status] as EventStatus[]
})

function statusLabel(status: EventStatus) { return { draft: '草稿', active: '进行中', closed: '已关闭' }[status] }
function money(cents: number) { return `¥${(cents / 100).toFixed(2)}` }
function toLocalInput(value: string) {
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}
function showError(caught: unknown, fallback: string) {
  error.value = caught instanceof Error ? caught.message : fallback
}

async function load() {
  if (!auth.adminPassword) { await router.replace('/admin'); return }
  try {
    const [eventData, prizeData, winnerData, redemptionData] = await Promise.all([
      api<EventRecord>(`/api/admin/events/${eventId}`),
      api<PrizeRecord[]>(`/api/admin/events/${eventId}/prizes`),
      api<WinnerRecord[]>(`/api/admin/events/${eventId}/winners`),
      api<AdminRedemption[]>(`/api/admin/events/${eventId}/redemptions`),
    ])
    event.value = eventData
    prizes.value = prizeData
    winners.value = winnerData
    redemptions.value = redemptionData
    Object.assign(eventForm, eventData, { redemption_deadline: toLocalInput(eventData.redemption_deadline) })
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) await router.replace('/admin')
    else showError(caught, '加载失败')
  }
}

function openPrize(prize?: PrizeRecord) {
  editingPrize.value = prize ?? null
  Object.assign(prizeForm, prize ? {
    name: prize.name, image: prize.image, realValueYuan: (prize.real_value / 100).toFixed(2), redeem_value: prize.redeem_value, stock: prize.stock, description: prize.description ?? '',
  } : { name: '', image: '', realValueYuan: '0.00', redeem_value: 1, stock: 0, description: '' })
  imageMode.value = prize?.image.startsWith('/uploads/') ? 'upload' : 'url'
  showPrizeForm.value = true
}

async function savePrize() {
  const cents = Math.round(Number(prizeForm.realValueYuan) * 100)
  if (!Number.isFinite(cents) || cents < 0 || !/^\d+(\.\d{1,2})?$/.test(prizeForm.realValueYuan)) {
    error.value = '真实价值必须是最多两位小数的非负金额'; return
  }
  const payload: PrizeWrite = { name: prizeForm.name, image: prizeForm.image, real_value: cents, redeem_value: Number(prizeForm.redeem_value), stock: Number(prizeForm.stock), description: prizeForm.description || null }
  busy.value = true; error.value = ''
  try {
    if (editingPrize.value) await api(`/api/admin/prizes/${editingPrize.value.id}`, { method: 'PUT', body: JSON.stringify(payload) })
    else await api(`/api/admin/events/${eventId}/prizes`, { method: 'POST', body: JSON.stringify(payload) })
    showPrizeForm.value = false; notice.value = '奖品已保存'; await load()
  } catch (caught) { showError(caught, '保存失败') } finally { busy.value = false }
}

async function uploadImage(file: File | undefined) {
  if (!file) return
  const data = new FormData(); data.append('file', file)
  try {
    const result = await api<{ image: string }>('/api/admin/uploads/prize-image', { method: 'POST', body: data })
    prizeForm.image = result.image
  } catch (caught) { showError(caught, '上传失败') }
}

async function removePrize(prize: PrizeRecord) {
  if (!window.confirm(`确认删除奖品“${prize.name}”？`)) return
  try { await api<void>(`/api/admin/prizes/${prize.id}`, { method: 'DELETE' }); notice.value = '奖品已删除'; await load() }
  catch (caught) { showError(caught, '删除失败') }
}

async function saveEvent() {
  busy.value = true; error.value = ''
  try {
    await api(`/api/admin/events/${eventId}`, { method: 'PUT', body: JSON.stringify({ ...eventForm, redemption_deadline: new Date(eventForm.redemption_deadline).toISOString() }) })
    notice.value = '比赛设置已保存'; await load()
  } catch (caught) { showError(caught, '保存失败') } finally { busy.value = false }
}

async function validateImport(file: File | undefined) {
  if (!file) return
  importFile.value = file; importPreview.value = null; error.value = ''
  const data = new FormData(); data.append('file', file)
  try { importPreview.value = await api<PrizeImportPreview>(`/api/admin/events/${eventId}/prizes/import/validate`, { method: 'POST', body: data }) }
  catch (caught) { showError(caught, '校验失败') }
}

async function confirmImport() {
  if (!importFile.value || !importPreview.value?.valid) return
  const data = new FormData(); data.append('file', importFile.value)
  busy.value = true
  try {
    const result = await api<{ imported: number }>(`/api/admin/events/${eventId}/prizes/import/confirm`, { method: 'POST', body: data })
    notice.value = `已导入 ${result.imported} 个奖品`; importFile.value = null; importPreview.value = null; await load()
  } catch (caught) { showError(caught, '导入失败') } finally { busy.value = false }
}

async function validateWinnerImport(file: File | undefined) {
  if (!file) return
  winnerImportFile.value = file; winnerImportPreview.value = null; error.value = ''
  const data = new FormData(); data.append('file', file)
  try { winnerImportPreview.value = await api<WinnerImportPreview>(`/api/admin/events/${eventId}/winners/import/validate`, { method: 'POST', body: data }) }
  catch (caught) { showError(caught, '校验失败') }
}

async function confirmWinnerImport() {
  if (!winnerImportFile.value || !winnerImportPreview.value?.valid) return
  const data = new FormData(); data.append('file', winnerImportFile.value)
  busy.value = true
  try {
    const result = await api<{ imported: number }>(`/api/admin/events/${eventId}/winners/import/confirm`, { method: 'POST', body: data })
    notice.value = `已导入 ${result.imported} 名获奖人并生成兑换码`; winnerImportFile.value = null; winnerImportPreview.value = null; await load()
  } catch (caught) { showError(caught, '导入失败') } finally { busy.value = false }
}

async function copyCode(code: string) {
  await navigator.clipboard.writeText(code)
  notice.value = '兑换码已复制'
}

function redemptionStatusLabel(status: AdminRedemptionStatus) {
  return { submitted: '已提交', ready: '待领取', picked_up: '已领取', cancelled: '已取消' }[status]
}

async function filterRedemptions() {
  const params = new URLSearchParams()
  if (redemptionStatus.value) params.set('status', redemptionStatus.value)
  if (redemptionSearch.value.trim()) params.set('search', redemptionSearch.value.trim())
  try { redemptions.value = await api<AdminRedemption[]>(`/api/admin/events/${eventId}/redemptions?${params}`) }
  catch (caught) { showError(caught, '加载兑换记录失败') }
}

async function openRedemption(id: number) {
  try { selectedRedemption.value = await api<AdminRedemption>(`/api/admin/redemptions/${id}`) }
  catch (caught) { showError(caught, '加载兑换详情失败') }
}

async function redemptionAction(redemption: AdminRedemption, action: 'ready' | 'pickup' | 'cancel') {
  const labels = { ready: '标记为待领取', pickup: '标记为已领取', cancel: '取消兑换并恢复库存' }
  if (!window.confirm(`确认${labels[action]}？`)) return
  busy.value = true
  try {
    await api(`/api/admin/redemptions/${redemption.id}/${action}`, { method: 'POST' })
    notice.value = '兑换状态已更新'; selectedRedemption.value = null; await load(); await filterRedemptions()
  } catch (caught) { showError(caught, '状态更新失败') } finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto max-w-7xl p-6 md:p-10">
    <div class="flex justify-between"><RouterLink to="/admin/events" class="text-sm text-blue-600 hover:underline">← 返回比赛列表</RouterLink><RouterLink to="/admin/settings/notifications" class="text-sm text-blue-600 hover:underline">通知设置</RouterLink></div>
    <header v-if="event" class="mt-4 flex flex-wrap items-end justify-between gap-4">
      <div><div class="flex items-center gap-3"><h1 class="text-3xl font-bold">{{ event.name }}</h1><span class="rounded-full bg-slate-100 px-3 py-1 text-xs">{{ statusLabel(event.status) }}</span></div><p class="mt-2 text-sm text-slate-500">兑换截止 {{ new Date(event.redemption_deadline).toLocaleString() }}</p></div>
    </header>
    <p v-if="error" class="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
    <p v-if="notice" class="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{{ notice }}</p>

    <nav class="mt-8 flex gap-2 border-b border-slate-200">
      <button v-for="item in [{ key: 'prizes', label: '奖品' }, { key: 'winners', label: '获奖人' }, { key: 'redemptions', label: '兑换记录' }, { key: 'settings', label: '比赛设置' }]" :key="item.key" class="border-b-2 px-4 py-3 text-sm font-medium" :class="tab === item.key ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'" @click="tab = item.key as typeof tab">{{ item.label }}</button>
    </nav>

    <section v-if="tab === 'prizes'" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex flex-wrap gap-2">
          <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/prizes/import/template?format=csv`, 'prizes-template.csv')">CSV 模板</button>
          <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/prizes/import/template?format=xlsx`, 'prizes-template.xlsx')">XLSX 模板</button>
          <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/prizes/export?format=csv`, 'prizes.csv')">导出 CSV</button>
          <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/prizes/export?format=xlsx`, 'prizes.xlsx')">导出 XLSX</button>
          <label class="btn-secondary cursor-pointer">导入表格<input class="hidden" type="file" accept=".csv,.xlsx" @change="validateImport(($event.target as HTMLInputElement).files?.[0])" /></label>
        </div>
        <button class="btn-primary" @click="openPrize()">新增奖品</button>
      </div>

      <div v-if="importPreview" class="card mt-4">
        <h3 class="font-semibold">导入预览 · {{ importPreview.rows.length }} 行</h3>
        <ul v-if="importPreview.errors.length" class="mt-3 space-y-1 text-sm text-red-700"><li v-for="issue in importPreview.errors" :key="`${issue.row}-${issue.field}-${issue.message}`">第 {{ issue.row }} 行 · {{ issue.field }}：{{ issue.message }}</li></ul>
        <div class="mt-4 max-h-48 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th class="p-2">名称</th><th class="p-2">真实价值</th><th class="p-2">抵扣</th><th class="p-2">库存</th></tr></thead><tbody><tr v-for="(row, index) in importPreview.rows" :key="index" class="border-t"><td class="p-2">{{ row.name }}</td><td class="p-2">{{ row.real_value }}</td><td class="p-2">{{ row.redeem_value }}</td><td class="p-2">{{ row.stock }}</td></tr></tbody></table></div>
        <button class="btn-primary mt-4" :disabled="!importPreview.valid || busy" @click="confirmImport">确认全部导入</button>
      </div>

      <div class="mt-5 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 text-slate-600"><tr><th class="p-4">奖品</th><th class="p-4">真实价值</th><th class="p-4">抵扣价值</th><th class="p-4">库存</th><th class="p-4 text-right">操作</th></tr></thead>
          <tbody><tr v-for="prize in prizes" :key="prize.id" class="border-t border-slate-100"><td class="p-4"><div class="flex items-center gap-3"><img :src="prize.image" :alt="prize.name" class="h-12 w-12 rounded-lg object-cover" /><div><strong>{{ prize.name }}</strong><p class="max-w-xs truncate text-xs text-slate-500">{{ prize.description }}</p></div></div></td><td class="p-4">{{ money(prize.real_value) }}</td><td class="p-4">{{ prize.redeem_value }}</td><td class="p-4">{{ prize.stock }}</td><td class="p-4 text-right"><button class="text-blue-600" @click="openPrize(prize)">编辑</button><button class="ml-4 text-red-600" @click="removePrize(prize)">删除</button></td></tr><tr v-if="prizes.length === 0"><td colspan="5" class="p-10 text-center text-slate-500">暂无奖品</td></tr></tbody>
        </table>
      </div>
    </section>

    <section v-else-if="tab === 'winners'" class="mt-6">
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/winners/import/template?format=csv`, 'winners-template.csv')">CSV 模板</button>
        <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/winners/import/template?format=xlsx`, 'winners-template.xlsx')">XLSX 模板</button>
        <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/winners/export?format=csv`, 'winners.csv')">导出 CSV</button>
        <button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/winners/export?format=xlsx`, 'winners.xlsx')">导出 XLSX</button>
        <label class="btn-primary cursor-pointer">导入获奖人<input class="hidden" type="file" accept=".csv,.xlsx" @change="validateWinnerImport(($event.target as HTMLInputElement).files?.[0])" /></label>
      </div>
      <div v-if="winnerImportPreview" class="card mt-4">
        <h3 class="font-semibold">导入预览 · {{ winnerImportPreview.count }} 人 · quota 合计 {{ winnerImportPreview.quota_total }}</h3>
        <ul v-if="winnerImportPreview.errors.length" class="mt-3 space-y-1 text-sm text-red-700"><li v-for="issue in winnerImportPreview.errors" :key="`${issue.row}-${issue.field}-${issue.message}`">第 {{ issue.row }} 行 · {{ issue.field }}：{{ issue.message }}</li></ul>
        <div class="mt-4 max-h-48 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th class="p-2">external_id</th><th class="p-2">姓名</th><th class="p-2">邮箱</th><th class="p-2">quota</th></tr></thead><tbody><tr v-for="(row, index) in winnerImportPreview.rows" :key="index" class="border-t"><td class="p-2">{{ row.external_id || '—' }}</td><td class="p-2">{{ row.name }}</td><td class="p-2">{{ row.email }}</td><td class="p-2">{{ row.quota }}</td></tr></tbody></table></div>
        <button class="btn-primary mt-4" :disabled="!winnerImportPreview.valid || busy" @click="confirmWinnerImport">确认全部导入并发码</button>
      </div>
      <div class="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full min-w-[900px] text-left text-sm"><thead class="bg-slate-50 text-slate-600"><tr><th class="p-4">姓名</th><th class="p-4">邮箱</th><th class="p-4">quota</th><th class="p-4">兑换码</th><th class="p-4">码状态</th><th class="p-4">Email</th><th class="p-4">Webhook</th></tr></thead><tbody><tr v-for="winner in winners" :key="winner.id" class="border-t"><td class="p-4 font-medium">{{ winner.name }}</td><td class="p-4">{{ winner.email }}</td><td class="p-4">{{ winner.quota }}</td><td class="p-4"><button class="font-mono font-semibold text-blue-600" @click="copyCode(winner.code)">{{ winner.code }}</button></td><td class="p-4">{{ winner.code_status }}</td><td class="p-4">{{ winner.email_notification_status }}</td><td class="p-4">{{ winner.webhook_notification_status }}</td></tr><tr v-if="winners.length === 0"><td colspan="7" class="p-10 text-center text-slate-500">暂无获奖人，请先下载模板并导入</td></tr></tbody></table>
      </div>
    </section>

    <section v-else-if="tab === 'redemptions'" class="mt-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <form class="flex flex-wrap items-end gap-2" @submit.prevent="filterRedemptions">
          <label class="text-sm">状态<select v-model="redemptionStatus" class="field mt-1"><option value="">全部</option><option value="submitted">已提交</option><option value="ready">待领取</option><option value="picked_up">已领取</option><option value="cancelled">已取消</option></select></label>
          <label class="text-sm">兑换单号<input v-model="redemptionSearch" class="field mt-1" maxlength="24" placeholder="搜索单号" /></label>
          <button class="btn-secondary" type="submit">筛选</button>
        </form>
        <div class="flex gap-2"><button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/redemptions/export?format=csv`, 'redemptions.csv')">导出 CSV</button><button class="btn-secondary" @click="downloadAdmin(`/api/admin/events/${eventId}/redemptions/export?format=xlsx`, 'redemptions.xlsx')">导出 XLSX</button></div>
      </div>
      <div class="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full min-w-[1000px] text-left text-sm"><thead class="bg-slate-50 text-slate-600"><tr><th class="p-4">兑换单号</th><th class="p-4">提交人</th><th class="p-4">手机号</th><th class="p-4">奖品</th><th class="p-4">总抵扣</th><th class="p-4">状态</th><th class="p-4">提交时间</th><th class="p-4 text-right">操作</th></tr></thead><tbody><tr v-for="record in redemptions" :key="record.id" class="border-t"><td class="p-4 font-mono"><button class="text-blue-600" @click="openRedemption(record.id)">{{ record.order_no }}</button></td><td class="p-4">{{ record.contact_name }}</td><td class="p-4">{{ record.contact_phone }}</td><td class="max-w-xs truncate p-4">{{ record.items_summary }}</td><td class="p-4">{{ record.total_redeem_value }}</td><td class="p-4">{{ redemptionStatusLabel(record.status) }}</td><td class="p-4">{{ new Date(record.created_at).toLocaleString() }}</td><td class="whitespace-nowrap p-4 text-right"><button v-if="record.status === 'submitted'" class="rounded-lg bg-blue-600 px-3 py-2 font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50" :disabled="busy" @click="redemptionAction(record, 'ready')">已备货</button><button v-if="record.status === 'ready'" class="rounded-lg bg-emerald-600 px-3 py-2 font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" :disabled="busy" @click="redemptionAction(record, 'pickup')">已领取</button><button v-if="record.status === 'submitted' || record.status === 'ready'" class="ml-3 text-red-600" @click="redemptionAction(record, 'cancel')">取消</button></td></tr><tr v-if="redemptions.length === 0"><td colspan="8" class="p-10 text-center text-slate-500">暂无兑换记录</td></tr></tbody></table>
      </div>
    </section>

    <form v-else class="card mt-6 max-w-2xl" @submit.prevent="saveEvent">
      <div class="grid gap-4">
        <label class="text-sm font-medium">名称<input v-model="eventForm.name" class="field mt-1" maxlength="200" required /></label>
        <label class="text-sm font-medium">说明<textarea v-model="eventForm.description" class="field mt-1" rows="3" /></label>
        <label class="text-sm font-medium">兑换截止时间<input v-model="eventForm.redemption_deadline" class="field mt-1" type="datetime-local" required /></label>
        <label class="text-sm font-medium">固定自提地点<textarea v-model="eventForm.pickup_location" class="field mt-1" rows="2" required /></label>
        <label class="text-sm font-medium">自提说明<textarea v-model="eventForm.pickup_instructions" class="field mt-1" rows="3" required /></label>
        <label class="text-sm font-medium">状态<select v-model="eventForm.status" class="field mt-1"><option v-for="status in allowedStatuses" :key="status" :value="status">{{ statusLabel(status) }}</option></select></label>
      </div>
      <button class="btn-primary mt-6" :disabled="busy">保存比赛设置</button>
    </form>

    <div v-if="showPrizeForm" class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4" @click.self="showPrizeForm = false">
      <form class="card max-h-[92vh] w-full max-w-xl overflow-auto" @submit.prevent="savePrize">
        <div class="flex justify-between"><h2 class="text-xl font-bold">{{ editingPrize ? '编辑奖品' : '新增奖品' }}</h2><button type="button" @click="showPrizeForm = false">关闭</button></div>
        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium">名字<input v-model="prizeForm.name" class="field mt-1" maxlength="200" required /></label>
          <fieldset><legend class="text-sm font-medium">图片</legend><div class="mt-2 flex gap-4 text-sm"><label><input v-model="imageMode" type="radio" value="url" /> HTTPS 外链</label><label><input v-model="imageMode" type="radio" value="upload" /> 本地上传</label></div><input v-if="imageMode === 'url'" v-model="prizeForm.image" class="field mt-2" type="url" pattern="https://.*" required /><div v-else class="mt-2"><input type="file" accept="image/jpeg,image/png,image/webp" @change="uploadImage(($event.target as HTMLInputElement).files?.[0])" /><p v-if="prizeForm.image" class="mt-2 break-all text-xs text-slate-500">{{ prizeForm.image }}</p></div></fieldset>
          <div class="grid grid-cols-3 gap-3"><label class="text-sm font-medium">真实价值（元）<input v-model="prizeForm.realValueYuan" class="field mt-1" inputmode="decimal" required /></label><label class="text-sm font-medium">抵扣价值<input v-model.number="prizeForm.redeem_value" class="field mt-1" type="number" min="1" step="1" required /></label><label class="text-sm font-medium">库存<input v-model.number="prizeForm.stock" class="field mt-1" type="number" min="0" step="1" required /></label></div>
          <label class="text-sm font-medium">描述<textarea v-model="prizeForm.description" class="field mt-1" maxlength="5000" rows="4" /></label>
        </div>
        <button class="btn-primary mt-6 w-full" :disabled="busy || !prizeForm.image">保存奖品</button>
      </form>
    </div>

    <div v-if="selectedRedemption" class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4" @click.self="selectedRedemption = null">
      <section class="card max-h-[92vh] w-full max-w-2xl overflow-auto">
        <div class="flex items-start justify-between"><div><p class="text-xs text-slate-500">兑换单号</p><h2 class="font-mono text-xl font-bold">{{ selectedRedemption.order_no }}</h2></div><button @click="selectedRedemption = null">关闭</button></div>
        <div class="mt-5 grid grid-cols-2 gap-4 text-sm"><div><span class="text-slate-500">获奖人</span><p>{{ selectedRedemption.winner_name }} · {{ selectedRedemption.winner_email }}</p></div><div><span class="text-slate-500">领取联系人</span><p>{{ selectedRedemption.contact_name }} · {{ selectedRedemption.contact_phone }}</p></div><div><span class="text-slate-500">状态</span><p>{{ redemptionStatusLabel(selectedRedemption.status) }}</p></div><div><span class="text-slate-500">额度</span><p>消耗 {{ selectedRedemption.total_redeem_value }} / {{ selectedRedemption.quota }}，未用 {{ selectedRedemption.unused_quota }}</p></div></div>
        <p v-if="selectedRedemption.note" class="mt-4 rounded-lg bg-slate-50 p-3 text-sm">备注：{{ selectedRedemption.note }}</p>
        <div class="mt-5"><h3 class="font-semibold">奖品快照</h3><div v-for="item in selectedRedemption.items" :key="item.id" class="mt-3 flex items-center gap-3 border-t pt-3"><img :src="item.prize_image" :alt="item.prize_name" class="h-12 w-12 rounded object-cover" /><div class="flex-1"><strong>{{ item.prize_name }}</strong><p class="text-xs text-slate-500">抵扣 {{ item.redeem_value }} × {{ item.quantity }}</p></div><strong>{{ item.line_redeem_value }}</strong></div></div>
        <div class="mt-5 rounded-lg bg-blue-50 p-4 text-sm"><strong>自提信息</strong><p class="mt-1">{{ selectedRedemption.pickup_location }}</p><p class="mt-1 whitespace-pre-wrap text-slate-600">{{ selectedRedemption.pickup_instructions }}</p></div>
        <div class="mt-5 flex justify-end gap-2"><button v-if="selectedRedemption.status === 'submitted'" class="btn-primary" @click="redemptionAction(selectedRedemption, 'ready')">标记待领取</button><button v-if="selectedRedemption.status === 'ready'" class="btn-primary" @click="redemptionAction(selectedRedemption, 'pickup')">标记已领取</button><button v-if="selectedRedemption.status === 'submitted' || selectedRedemption.status === 'ready'" class="btn-secondary text-red-600" @click="redemptionAction(selectedRedemption, 'cancel')">取消兑换</button></div>
      </section>
    </div>
  </main>
</template>
