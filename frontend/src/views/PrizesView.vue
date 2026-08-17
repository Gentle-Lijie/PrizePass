<script setup lang="ts">
import { push } from 'notivue'
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { api, ApiError, downloadAdmin } from '@/api/client'
import type {
  PrizeBatchDeleteResult,
  PrizeBatchStock,
  PrizeBatchTag,
  PrizeImportPreview,
  PrizeRecord,
  PrizeSummary,
  PrizeWrite,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const prizes = ref<PrizeRecord[]>([])
const summary = ref<PrizeSummary>({
  total_prizes: 0,
  backorder_units: 0,
  total_purchase_value: 0,
  claimed_purchase_value: 0,
  reimbursed_value: 0,
})
const loading = ref(true)
const busy = ref(false)

// --- Modal state ---
const showModal = ref(false)
const editingPrizeId = ref<number | null>(null)

const blankForm = (): PrizeWrite => ({
  name: '',
  image: '',
  jd_url: null,
  real_value: 0,
  purchase_value: 0,
  redeem_value: 0,
  stock: 0,
  description: null,
  tag: null,
  is_active: true,
})

const form = reactive<PrizeWrite>(blankForm())

// Value inputs in yuan (display helper)
const realValueYuan = ref('0.00')
const purchaseValueYuan = ref('0.00')

// Import state
const importFile = ref<File | null>(null)
const importPreview = ref<PrizeImportPreview | null>(null)

// --- Batch operations ---
const selectedIds = ref(new Set<number>())
const showBatchTagModal = ref(false)
const showBatchStockModal = ref(false)
const batchTagValue = ref('')
const batchStockMode = ref<'delta' | 'set'>('delta')
const batchStockValue = ref(0)

const selectedCount = computed(() => selectedIds.value.size)
const allSelected = computed(() => prizes.value.length > 0 && selectedIds.value.size === prizes.value.length)

function toggleSelect(id: number, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedIds.value = next
}

function toggleSelectAll(checked: boolean) {
  selectedIds.value = checked ? new Set(prizes.value.map((p) => p.id)) : new Set()
}

function clearSelection() {
  selectedIds.value = new Set()
}

async function batchSetTag() {
  if (selectedIds.value.size === 0) return
  busy.value = true
  try {
    const payload: PrizeBatchTag = {
      ids: [...selectedIds.value],
      tag: batchTagValue.value.trim() || null,
    }
    await api('/api/admin/prizes/batch-tag', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    push.success(`已更新 ${selectedIds.value.size} 个奖品的标签`)
    showBatchTagModal.value = false
    batchTagValue.value = ''
    clearSelection()
    await load()
  } catch (caught) {
    showErrorMsg(caught, '批量设置标签失败')
  } finally {
    busy.value = false
  }
}

async function batchAdjustStock() {
  if (selectedIds.value.size === 0) return
  busy.value = true
  try {
    const payload: PrizeBatchStock = {
      ids: [...selectedIds.value],
      mode: batchStockMode.value,
      value: batchStockValue.value,
    }
    await api('/api/admin/prizes/batch-stock', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    push.success(`已调整 ${selectedIds.value.size} 个奖品的库存`)
    showBatchStockModal.value = false
    batchStockValue.value = 0
    clearSelection()
    await load()
  } catch (caught) {
    showErrorMsg(caught, '批量调整库存失败')
  } finally {
    busy.value = false
  }
}

async function batchDelete() {
  if (selectedIds.value.size === 0) return
  if (!window.confirm(`确认删除选中的 ${selectedIds.value.size} 个奖品？`)) return
  busy.value = true
  try {
    const result = await api<PrizeBatchDeleteResult>('/api/admin/prizes/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ ids: [...selectedIds.value] }),
    })
    push.success(
      `已删除 ${result.deleted} 个奖品${result.skipped.length > 0 ? `，跳过 ${result.skipped.length} 个（已被兑换引用）` : ''}`,
    )
    clearSelection()
    await load()
  } catch (caught) {
    showErrorMsg(caught, '批量删除失败')
  } finally {
    busy.value = false
  }
}

// --- Load ---
async function load() {
  if (!auth.adminPassword) {
    await router.replace('/admin')
    return
  }
  loading.value = true
  try {
    const [prizeData, summaryData] = await Promise.all([
      api<PrizeRecord[]>('/api/admin/prizes'),
      api<PrizeSummary>('/api/admin/prizes/summary'),
    ])
    prizes.value = prizeData
    summary.value = summaryData
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      await router.replace('/admin')
      return
    }
    push.error(caught instanceof Error ? caught.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function formatMoney(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

function showErrorMsg(caught: unknown, fallback: string) {
  push.error(caught instanceof Error ? caught.message : fallback)
}

// --- Create / Edit Modal ---
function openCreateModal() {
  editingPrizeId.value = null
  Object.assign(form, blankForm())
  realValueYuan.value = '0.00'
  purchaseValueYuan.value = '0.00'
  showModal.value = true
}

function openEditModal(prize: PrizeRecord) {
  editingPrizeId.value = prize.id
  Object.assign(form, {
    name: prize.name,
    image: prize.image,
    jd_url: prize.jd_url,
    real_value: prize.real_value,
    purchase_value: prize.purchase_value,
    redeem_value: prize.redeem_value,
    stock: prize.stock,
    description: prize.description,
    tag: prize.tag,
    is_active: prize.is_active,
  })
  realValueYuan.value = (prize.real_value / 100).toFixed(2)
  purchaseValueYuan.value = (prize.purchase_value / 100).toFixed(2)
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  editingPrizeId.value = null
}

async function uploadImage(file: File) {
  const data = new FormData()
  data.append('file', file)
  const result = await api<{ image: string }>('/api/admin/uploads/prize-image', { method: 'POST', body: data })
  return result.image
}

async function handleImageUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const url = await uploadImage(file)
    form.image = url
  } catch (caught) {
    push.error(caught instanceof Error ? caught.message : '上传失败')
  }
}

function yuanToCents(yuan: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(yuan)) return null
  const n = Math.round(Number(yuan) * 100)
  return Number.isFinite(n) && n >= 0 ? n : null
}

async function savePrize() {
  const realCents = yuanToCents(realValueYuan.value)
  if (realCents === null) {
    push.error('采购价必须是合法的金额（最多两位小数）')
    return
  }
  const purchaseCents = yuanToCents(purchaseValueYuan.value)
  if (purchaseCents === null) {
    push.error('展示价必须是合法的金额（最多两位小数）')
    return
  }

  const payload: PrizeWrite = {
    name: form.name.trim(),
    image: form.image.trim(),
    jd_url: (form.jd_url ?? '').trim() || null,
    real_value: realCents,
    purchase_value: purchaseCents,
    redeem_value: Number(form.redeem_value) || 0,
    stock: Number(form.stock) || 0,
    description: (form.description ?? '').trim() || null,
    tag: (form.tag ?? '').trim() || null,
    is_active: form.is_active,
  }

  if (!payload.name) {
    push.error('奖品名称不能为空')
    return
  }
  if (!payload.image) {
    push.error('请填写奖品图片地址或上传图片')
    return
  }

  busy.value = true
  try {
    if (editingPrizeId.value !== null) {
      await api<PrizeRecord>(`/api/admin/prizes/${editingPrizeId.value}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      push.success('已更新奖品')
    } else {
      await api<PrizeRecord>('/api/admin/prizes', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      push.success('已创建奖品')
    }
    closeModal()
    await load()
  } catch (caught) {
    showErrorMsg(caught, '保存失败')
  } finally {
    busy.value = false
  }
}

// --- Toggle active ---
async function toggleActive(prize: PrizeRecord) {
  busy.value = true
  try {
    await api<PrizeRecord>(`/api/admin/prizes/${prize.id}`, {
      method: 'PUT',
      body: JSON.stringify({ ...prize, is_active: !prize.is_active }),
    })
    push.success(prize.is_active ? `已下架"${prize.name}"` : `已上架"${prize.name}"`)
    await load()
  } catch (caught) {
    showErrorMsg(caught, '操作失败')
  } finally {
    busy.value = false
  }
}

// --- Delete ---
async function deletePrize(prize: PrizeRecord) {
  if (!window.confirm(`确认删除奖品"${prize.name}"？此操作不可恢复。`)) return
  busy.value = true
  try {
    await api(`/api/admin/prizes/${prize.id}`, { method: 'DELETE' })
    push.success(`已删除"${prize.name}"`)
    await load()
  } catch (caught) {
    showErrorMsg(caught, '删除失败')
  } finally {
    busy.value = false
  }
}

// --- Import ---
async function validateImport(file: File | undefined) {
  if (!file) return
  importFile.value = file
  importPreview.value = null
  const data = new FormData()
  data.append('file', file)
  try {
    importPreview.value = await api<PrizeImportPreview>('/api/admin/prizes/import/validate', {
      method: 'POST',
      body: data,
    })
  } catch (caught) {
    showErrorMsg(caught, '校验失败')
  }
}

function cancelImport() {
  importPreview.value = null
  importFile.value = null
}

async function confirmImport() {
  if (!importFile.value || !importPreview.value?.valid) return
  const data = new FormData()
  data.append('file', importFile.value)
  busy.value = true
  try {
    const result = await api<{ imported: number }>('/api/admin/prizes/import/confirm', { method: 'POST', body: data })
    push.success(`已导入 ${result.imported} 个奖品`)
    importFile.value = null
    importPreview.value = null
    await load()
  } catch (caught) {
    showErrorMsg(caught, '导入失败')
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-7xl p-6">
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-3xl font-bold">全局奖品池</h1>
      <div class="flex flex-wrap gap-2">
        <RouterLink to="/admin/events" class="btn-secondary"> 返回比赛列表 </RouterLink>
        <button @click="load" class="btn-secondary" :disabled="loading || busy">
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- Summary Cards -->
    <div class="mb-8 grid grid-cols-1 gap-4 md:grid-cols-5">
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        <p class="text-sm text-slate-500 dark:text-slate-400">奖品总数</p>
        <p class="mt-2 text-3xl font-bold">{{ summary.total_prizes }}</p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        <p class="text-sm text-slate-500 dark:text-slate-400">待采购数量</p>
        <p
          class="mt-2 text-3xl font-bold"
          :class="summary.backorder_units > 0 ? 'text-amber-600 dark:text-amber-400' : ''"
        >
          {{ summary.backorder_units }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        <p class="text-sm text-slate-500 dark:text-slate-400">采购总额</p>
        <p class="mt-2 text-3xl font-bold">{{ formatMoney(summary.total_purchase_value) }}</p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        <p class="text-sm text-slate-500 dark:text-slate-400">已领取采购额</p>
        <p class="mt-2 text-3xl font-bold text-emerald-600 dark:text-emerald-400">
          {{ formatMoney(summary.claimed_purchase_value) }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        <p class="text-sm text-slate-500 dark:text-slate-400">已报销金额</p>
        <p class="mt-2 text-3xl font-bold text-blue-600 dark:text-blue-400">
          {{ formatMoney(summary.reimbursed_value) }}
        </p>
      </div>
    </div>

    <!-- Prize List -->
    <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
      <div class="border-b border-slate-200 p-6 dark:border-slate-700">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-xl font-semibold">奖品列表</h2>
          <div class="flex flex-wrap gap-2">
            <button
              class="btn-secondary"
              @click="downloadAdmin('/api/admin/prizes/import/template?format=csv', 'prizes-template.csv')"
            >
              CSV 模板
            </button>
            <button
              class="btn-secondary"
              @click="downloadAdmin('/api/admin/prizes/import/template?format=xlsx', 'prizes-template.xlsx')"
            >
              XLSX 模板
            </button>
            <button class="btn-secondary" @click="downloadAdmin('/api/admin/prizes/export?format=csv', 'prizes.csv')">
              导出 CSV
            </button>
            <button class="btn-secondary" @click="downloadAdmin('/api/admin/prizes/export?format=xlsx', 'prizes.xlsx')">
              导出 XLSX
            </button>
            <label class="btn-secondary cursor-pointer">
              导入奖品
              <input
                class="hidden"
                type="file"
                accept=".csv,.xlsx"
                @change="validateImport(($event.target as HTMLInputElement).files?.[0])"
              />
            </label>
            <button class="btn-primary" @click="openCreateModal">新增奖品</button>
          </div>
        </div>
      </div>

      <!-- Import Preview -->
      <div v-if="importPreview" class="border-b border-slate-200 p-6 dark:border-slate-700">
        <h3 class="font-semibold">
          导入预览
          <span v-if="importPreview.count !== undefined"> · {{ importPreview.count }} 行</span>
        </h3>
        <ul v-if="importPreview.errors.length" class="mt-3 space-y-1 text-sm text-red-700 dark:text-red-300">
          <li v-for="issue in importPreview.errors" :key="`${issue.row}-${issue.field}-${issue.message}`">
            第 {{ issue.row }} 行 · {{ issue.field }}：{{ issue.message }}
          </li>
        </ul>
        <div class="mt-4 max-h-48 overflow-auto">
          <table class="w-full text-left text-sm">
            <thead class="text-slate-600 dark:text-slate-300">
              <tr>
                <th
                  v-for="key in importPreview.rows[0] ? Object.keys(importPreview.rows[0]) : []"
                  :key="key"
                  class="p-2"
                >
                  {{ key }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in importPreview.rows.slice(0, 20)"
                :key="index"
                class="border-t border-slate-200 dark:border-slate-700"
              >
                <td
                  v-for="key in importPreview.rows[0] ? Object.keys(importPreview.rows[0]) : []"
                  :key="key"
                  class="p-2"
                >
                  {{ row[key] ?? '—' }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="importPreview.rows.length > 20" class="mt-2 text-xs text-slate-500">
            仅显示前 20 行，共 {{ importPreview.rows.length }} 行
          </p>
        </div>
        <div class="mt-4 flex gap-2">
          <button class="btn-primary" :disabled="!importPreview.valid || busy" @click="confirmImport">
            确认全部导入
          </button>
          <button class="btn-secondary" @click="cancelImport">取消</button>
        </div>
      </div>

      <div v-if="loading" class="p-12 text-center text-slate-500">加载中...</div>

      <div v-else-if="prizes.length === 0" class="p-12 text-center text-slate-500">暂无奖品</div>

      <div v-else class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-slate-50 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <tr>
              <th class="w-10 p-4">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  aria-label="全选"
                  @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
                />
              </th>
              <th class="p-4 text-left">奖品</th>
              <th class="p-4 text-left">标签</th>
              <th class="p-4 text-right">采购价</th>
              <th class="p-4 text-right">展示价</th>
              <th class="p-4 text-right">抵扣额度</th>
              <th class="p-4 text-right">库存</th>
              <th class="p-4 text-center">状态</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="prize in prizes" :key="prize.id" class="border-t border-slate-200 dark:border-slate-700">
              <td class="p-4">
                <input
                  type="checkbox"
                  :checked="selectedIds.has(prize.id)"
                  :aria-label="`选择 ${prize.name}`"
                  @change="toggleSelect(prize.id, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td class="p-4">
                <div class="flex items-center gap-3">
                  <img :src="prize.image" :alt="prize.name" class="h-12 w-12 rounded-lg object-cover" />
                  <div>
                    <p class="font-medium">{{ prize.name }}</p>
                    <p class="max-w-xs truncate text-sm text-slate-500 dark:text-slate-400">
                      {{ prize.description || '无描述' }}
                    </p>
                  </div>
                </div>
              </td>
              <td class="whitespace-nowrap p-4">
                <span
                  v-if="prize.tag"
                  class="inline-block whitespace-nowrap rounded-full bg-blue-100 px-3 py-1 text-sm text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                >
                  {{ prize.tag }}
                </span>
                <span v-else class="text-slate-400">—</span>
              </td>
              <td class="p-4 text-right font-mono">
                {{ formatMoney(prize.real_value) }}
              </td>
              <td class="p-4 text-right font-mono">
                {{ formatMoney(prize.purchase_value) }}
              </td>
              <td class="p-4 text-right font-mono">
                {{ prize.redeem_value }}
              </td>
              <td class="p-4 text-right">
                <span
                  :class="{
                    'text-amber-600 dark:text-amber-400': prize.stock < 0,
                    'text-slate-600 dark:text-slate-300': prize.stock >= 0,
                  }"
                >
                  {{ prize.stock }}
                </span>
              </td>
              <td class="p-4 text-center">
                <span
                  class="inline-block whitespace-nowrap rounded-full px-3 py-1 text-sm"
                  :class="{
                    'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300': prize.is_active,
                    'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400': !prize.is_active,
                  }"
                >
                  {{ prize.is_active ? '上架' : '下架' }}
                </span>
              </td>
              <td class="p-4 text-right">
                <div class="flex justify-end gap-3 whitespace-nowrap">
                  <button
                    class="text-blue-600 hover:text-blue-700 dark:text-blue-400 disabled:text-slate-300"
                    :disabled="busy"
                    @click="openEditModal(prize)"
                  >
                    编辑
                  </button>
                  <button
                    class="disabled:text-slate-300"
                    :class="{
                      'text-amber-600 hover:text-amber-700': prize.is_active,
                      'text-emerald-600 hover:text-emerald-700': !prize.is_active,
                    }"
                    :disabled="busy"
                    @click="toggleActive(prize)"
                  >
                    {{ prize.is_active ? '下架' : '上架' }}
                  </button>
                  <button
                    class="text-red-600 hover:text-red-700 dark:text-red-400 disabled:text-slate-300"
                    :disabled="busy"
                    @click="deletePrize(prize)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Batch Operations Bar -->
      <div
        v-if="selectedCount > 0"
        class="border-t border-slate-200 bg-blue-50 p-4 dark:border-slate-700 dark:bg-blue-950/40"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium text-blue-700 dark:text-blue-300">
              已选择 {{ selectedCount }} 个奖品
            </span>
            <button class="text-xs text-slate-500 underline dark:text-slate-400" @click="clearSelection">
              取消选择
            </button>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              class="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              :disabled="busy"
              @click="showBatchTagModal = true"
            >
              批量设置标签
            </button>
            <button
              class="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              :disabled="busy"
              @click="showBatchStockModal = true"
            >
              批量调整库存
            </button>
            <button
              class="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:border-red-900/60 dark:bg-slate-800 dark:text-red-300 dark:hover:bg-red-950/40"
              :disabled="busy"
              @click="batchDelete"
            >
              批量删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Batch Tag Modal -->
    <div
      v-if="showBatchTagModal"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showBatchTagModal = false"
    >
      <form class="card w-full max-w-md" @submit.prevent="batchSetTag">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">批量设置标签</h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="showBatchTagModal = false">
            关闭
          </button>
        </div>
        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium">
            标签值（留空则清除标签）
            <input v-model="batchTagValue" class="field mt-1" placeholder="如 1-数码、2-生活" maxlength="100" />
          </label>
          <p class="text-sm text-slate-500 dark:text-slate-400">将为 {{ selectedCount }} 个选中的奖品设置标签。</p>
        </div>
        <div class="mt-6 flex justify-end gap-2">
          <button type="button" class="btn-secondary" @click="showBatchTagModal = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="busy">
            {{ busy ? '处理中...' : '确认设置' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Batch Stock Modal -->
    <div
      v-if="showBatchStockModal"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showBatchStockModal = false"
    >
      <form class="card w-full max-w-md" @submit.prevent="batchAdjustStock">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">批量调整库存</h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="showBatchStockModal = false">
            关闭
          </button>
        </div>
        <div class="mt-5 grid gap-4">
          <div class="grid grid-cols-2 gap-2">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="batchStockMode" type="radio" value="delta" />
              增减（相对值）
            </label>
            <label class="flex items-center gap-2 text-sm">
              <input v-model="batchStockMode" type="radio" value="set" />
              设为（绝对值）
            </label>
          </div>
          <label class="text-sm font-medium">
            库存数量
            <input v-model.number="batchStockValue" class="field mt-1" type="number" step="1" />
          </label>
          <p class="text-sm text-slate-500 dark:text-slate-400">
            将对 {{ selectedCount }} 个选中的奖品{{ batchStockMode === 'delta' ? '增减' : '设为' }}库存。
          </p>
        </div>
        <div class="mt-6 flex justify-end gap-2">
          <button type="button" class="btn-secondary" @click="showBatchStockModal = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="busy">
            {{ busy ? '处理中...' : '确认调整' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Create / Edit Modal -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="closeModal"
    >
      <form class="card max-h-[90vh] w-full max-w-xl overflow-auto" @submit.prevent="savePrize">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">
            {{ editingPrizeId !== null ? '编辑奖品' : '新增奖品' }}
          </h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="closeModal">关闭</button>
        </div>

        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium">
            奖品名称
            <input v-model="form.name" class="field mt-1" maxlength="200" required placeholder="如：京东 E 卡 100 元" />
          </label>

          <div>
            <label class="text-sm font-medium">
              图片地址
              <input v-model="form.image" class="field mt-1" type="url" placeholder="https://..." />
            </label>
            <div class="mt-2 flex items-center gap-3">
              <label class="btn-secondary cursor-pointer text-xs">
                或上传图片
                <input class="hidden" type="file" accept="image/*" @change="handleImageUpload" />
              </label>
              <img v-if="form.image" :src="form.image" alt="预览" class="h-10 w-10 rounded object-cover" />
            </div>
          </div>

          <label class="text-sm font-medium">
            京东链接（选填）
            <input v-model="form.jd_url" class="field mt-1" type="url" placeholder="https://item.jd.com/..." />
          </label>

          <div class="grid grid-cols-2 gap-4">
            <label class="text-sm font-medium">
              采购价（元）
              <input v-model="realValueYuan" class="field mt-1" inputmode="decimal" required placeholder="0.00" />
            </label>
            <label class="text-sm font-medium">
              展示价（元）
              <input v-model="purchaseValueYuan" class="field mt-1" inputmode="decimal" required placeholder="0.00" />
            </label>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <label class="text-sm font-medium">
              抵扣额度
              <input v-model.number="form.redeem_value" class="field mt-1" type="number" min="0" step="1" required />
            </label>
            <label class="text-sm font-medium">
              库存
              <input v-model.number="form.stock" class="field mt-1" type="number" step="1" required />
              <span class="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400"> 负数表示待采购 </span>
            </label>
          </div>

          <label class="text-sm font-medium">
            标签（选填）
            <input v-model="form.tag" class="field mt-1" maxlength="50" placeholder="如：数码、生活、食品" />
          </label>

          <label class="text-sm font-medium">
            描述（选填）
            <textarea v-model="form.description" class="field mt-1" rows="3" placeholder="奖品的简要说明" />
          </label>

          <label class="flex items-center gap-2 text-sm font-medium">
            <input v-model="form.is_active" type="checkbox" />
            上架（对获奖人可见）
          </label>
        </div>

        <button class="btn-primary mt-6 w-full" :disabled="busy">
          {{ busy ? '保存中…' : editingPrizeId !== null ? '保存修改' : '创建奖品' }}
        </button>
      </form>
    </div>
  </div>
</template>
