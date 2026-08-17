<script setup lang="ts">
import { push } from 'notivue'
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { api, downloadAdmin } from '@/api/client'
import type {
  PrizeRecord,
  PurchaseAttachmentKind,
  PurchaseOrderRecord,
  PurchaseOrderStatus,
  PurchaseOrderWrite,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const purchases = ref<PurchaseOrderRecord[]>([])
const loading = ref(true)
const busy = ref(false)
const statusFilter = ref<PurchaseOrderStatus | ''>('')

// Modals
const showFormModal = ref(false)
const showDetailModal = ref(false)
const showAttachmentModal = ref(false)
const editingId = ref<number | null>(null) // null = create mode
const detailOrder = ref<PurchaseOrderRecord | null>(null)
const attachmentOrder = ref<PurchaseOrderRecord | null>(null)

// Confirmations
const confirmAction = ref<null | {
  kind: 'cancel' | 'delete' | 'reimburse'
  order: PurchaseOrderRecord
}>(null)

// Form state
const form = reactive<{ title: string; note: string }>({
  title: '',
  note: '',
})
const prizeSearch = ref('')
const selectedPrizes = ref<Map<number, number>>(new Map()) // prize_id -> quantity
const allPrizes = ref<PrizeRecord[]>([])
const prizesLoading = ref(false)

// Attachment upload state
const uploadingKind = ref<PurchaseAttachmentKind | null>(null)

async function load() {
  loading.value = true
  try {
    let url = '/api/admin/purchases'
    if (statusFilter.value) {
      url += `?status=${statusFilter.value}`
    }
    purchases.value = await api<PurchaseOrderRecord[]>(url)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function formatMoney(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}

function statusLabel(status: PurchaseOrderStatus): string {
  return {
    draft: '草稿',
    reimbursed: '已报销',
    cancelled: '已取消',
  }[status]
}

function statusClass(status: PurchaseOrderStatus): string {
  return {
    draft: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
    reimbursed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300',
    cancelled: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  }[status]
}

function kindLabel(kind: PurchaseAttachmentKind): string {
  return kind === 'transaction_screenshot' ? '交易截图' : '发票 PDF'
}

// --- Form Modal ---

async function openCreateModal() {
  editingId.value = null
  form.title = ''
  form.note = ''
  selectedPrizes.value = new Map()
  prizeSearch.value = ''
  showFormModal.value = true
  await loadPrizes()
}

async function openEditModal(order: PurchaseOrderRecord) {
  editingId.value = order.id
  form.title = order.title
  form.note = order.note || ''
  selectedPrizes.value = new Map()
  prizeSearch.value = ''
  showFormModal.value = true
  try {
    const detail = await api<PurchaseOrderRecord>(`/api/admin/purchases/${order.id}`)
    if (detail.items) {
      for (const item of detail.items) {
        selectedPrizes.value.set(item.prize_id, item.quantity)
      }
    }
  } catch (e) {
    push.error(e instanceof Error ? e.message : '加载详情失败')
    return
  }
  await loadPrizes()
}

async function loadPrizes() {
  prizesLoading.value = true
  try {
    allPrizes.value = await api<PrizeRecord[]>('/api/admin/prizes')
  } catch (e) {
    push.error(e instanceof Error ? e.message : '加载奖品列表失败')
  } finally {
    prizesLoading.value = false
  }
}

const filteredPrizes = computed(() => {
  const q = prizeSearch.value.trim().toLowerCase()
  if (!q) return allPrizes.value
  return allPrizes.value.filter((p) => p.name.toLowerCase().includes(q) || (p.tag && p.tag.toLowerCase().includes(q)))
})

const runningTotal = computed(() => {
  let total = 0
  for (const prize of allPrizes.value) {
    const qty = selectedPrizes.value.get(prize.id)
    if (qty && qty > 0) {
      total += prize.real_value * qty
    }
  }
  return total
})

const selectedItemCount = computed(() => {
  let count = 0
  for (const qty of selectedPrizes.value.values()) {
    if (qty > 0) count++
  }
  return count
})

function setPrizeQuantity(prizeId: number, qty: number) {
  const safeQty = Math.max(0, Math.floor(qty))
  if (safeQty === 0) {
    selectedPrizes.value.delete(prizeId)
  } else {
    selectedPrizes.value.set(prizeId, safeQty)
  }
  // trigger reactivity
  selectedPrizes.value = new Map(selectedPrizes.value)
}

function getPrizeQuantity(prizeId: number): number {
  return selectedPrizes.value.get(prizeId) || 0
}

async function submitForm() {
  if (!form.title.trim()) {
    push.error('标题不能为空')
    return
  }
  const items: Array<{ prize_id: number; quantity: number }> = []
  for (const [prize_id, quantity] of selectedPrizes.value.entries()) {
    if (quantity > 0) items.push({ prize_id, quantity })
  }
  if (items.length === 0) {
    push.error('请至少选择一个奖品')
    return
  }
  busy.value = true
  try {
    const payload: PurchaseOrderWrite = {
      title: form.title.trim(),
      note: form.note.trim() || null,
      items,
    }
    if (editingId.value) {
      await api<PurchaseOrderRecord>(`/api/admin/purchases/${editingId.value}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      push.success('采购单已更新')
    } else {
      await api<PurchaseOrderRecord>('/api/admin/purchases', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      push.success('采购单已创建')
    }
    showFormModal.value = false
    await load()
  } catch (e) {
    push.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    busy.value = false
  }
}

// --- Detail Modal ---

async function openDetail(order: PurchaseOrderRecord) {
  try {
    detailOrder.value = await api<PurchaseOrderRecord>(`/api/admin/purchases/${order.id}`)
    showDetailModal.value = true
  } catch (e) {
    push.error(e instanceof Error ? e.message : '加载详情失败')
  }
}

// --- Attachment Modal ---

async function openAttachments(order: PurchaseOrderRecord) {
  attachmentOrder.value = order
  showAttachmentModal.value = true
  await refreshAttachmentOrder(order.id)
}

async function refreshAttachmentOrder(id: number) {
  try {
    attachmentOrder.value = await api<PurchaseOrderRecord>(`/api/admin/purchases/${id}`)
  } catch (e) {
    push.error(e instanceof Error ? e.message : '刷新附件失败')
  }
}

async function uploadAttachment(kind: PurchaseAttachmentKind, file: File) {
  if (!attachmentOrder.value) return
  uploadingKind.value = kind
  try {
    const formData = new FormData()
    formData.append('kind', kind)
    formData.append('file', file)
    const response = await fetch(`/api/admin/purchases/${attachmentOrder.value.id}/attachments`, {
      method: 'POST',
      headers: { 'X-Admin-Password': auth.adminPassword },
      body: formData,
    })
    if (!response.ok) {
      const body = await response.json()
      throw new Error(body?.error?.message || `上传失败 (${response.status})`)
    }
    push.success(`${kindLabel(kind)} 已上传`)
    await refreshAttachmentOrder(attachmentOrder.value.id)
    await load()
  } catch (e) {
    push.error(e instanceof Error ? e.message : '上传失败')
  } finally {
    uploadingKind.value = null
  }
}

function triggerUpload(kind: PurchaseAttachmentKind) {
  const input = document.createElement('input')
  input.type = 'file'
  if (kind === 'transaction_screenshot') {
    input.accept = 'image/jpeg,image/png,image/webp'
  } else {
    input.accept = 'application/pdf,.pdf'
  }
  input.onchange = () => {
    const file = input.files?.[0]
    if (file) uploadAttachment(kind, file)
  }
  input.click()
}

async function deleteAttachment(attachmentId: number, kind: PurchaseAttachmentKind) {
  if (!attachmentOrder.value) return
  if (!confirm(`确定删除此${kindLabel(kind)}吗？`)) return
  try {
    await api<void>(`/api/admin/purchases/${attachmentOrder.value.id}/attachments/${attachmentId}`, {
      method: 'DELETE',
    })
    push.success('附件已删除')
    await refreshAttachmentOrder(attachmentOrder.value.id)
    await load()
  } catch (e) {
    push.error(e instanceof Error ? e.message : '删除失败')
  }
}

// --- Actions ---

function requestConfirm(kind: 'cancel' | 'delete' | 'reimburse', order: PurchaseOrderRecord) {
  confirmAction.value = { kind, order }
}

async function executeConfirm() {
  if (!confirmAction.value) return
  const { kind, order } = confirmAction.value
  busy.value = true
  try {
    if (kind === 'cancel') {
      await api<PurchaseOrderRecord>(`/api/admin/purchases/${order.id}/cancel`, { method: 'POST' })
      push.success('采购单已取消')
    } else if (kind === 'delete') {
      await api<void>(`/api/admin/purchases/${order.id}`, {
        method: 'DELETE',
      })
      push.success('采购单已删除')
    } else if (kind === 'reimburse') {
      await api<PurchaseOrderRecord>(`/api/admin/purchases/${order.id}/reimburse`, { method: 'POST' })
      push.success('已标记为报销')
    }
    confirmAction.value = null
    await load()
  } catch (e) {
    push.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    busy.value = false
  }
}

async function downloadPackage(orderId: number, orderNo: string) {
  try {
    await downloadAdmin(`/api/admin/purchases/${orderId}/package`, `${orderNo}.zip`)
    push.success('打包下载已开始')
  } catch (e) {
    push.error(e instanceof Error ? e.message : '下载失败')
  }
}

async function exportPurchases(format: 'csv' | 'xlsx') {
  try {
    await downloadAdmin(`/api/admin/purchases/export?format=${format}`, `purchases.${format}`)
    push.success('导出成功')
  } catch (e) {
    push.error(e instanceof Error ? e.message : '导出失败')
  }
}

// Check if order has both attachment types
function hasBothAttachmentTypes(order: PurchaseOrderRecord): boolean {
  if (!order.attachments) return order.attachment_count >= 2
  const kinds = new Set(order.attachments.map((a) => a.kind))
  return kinds.has('transaction_screenshot') && kinds.has('invoice_pdf')
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-7xl p-6">
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-3xl font-bold">采购报销</h1>
      <div class="flex gap-2">
        <RouterLink to="/admin/prizes" class="btn-secondary"> 全局奖品池 </RouterLink>
        <button @click="load" class="btn-secondary" :disabled="loading">
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- Filters and Actions -->
    <div class="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center gap-2">
        <label class="text-sm font-medium text-slate-600 dark:text-slate-300"> 状态筛选： </label>
        <select
          v-model="statusFilter"
          @change="load"
          class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800"
        >
          <option value="">全部</option>
          <option value="draft">草稿</option>
          <option value="reimbursed">已报销</option>
          <option value="cancelled">已取消</option>
        </select>
      </div>
      <div class="flex gap-2">
        <button @click="exportPurchases('csv')" class="btn-secondary">导出 CSV</button>
        <button @click="exportPurchases('xlsx')" class="btn-secondary">导出 Excel</button>
        <button class="btn-primary" @click="openCreateModal">创建采购单</button>
      </div>
    </div>

    <!-- Purchase List -->
    <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
      <div v-if="loading" class="p-12 text-center text-slate-500">加载中...</div>

      <div v-else-if="purchases.length === 0" class="p-12 text-center text-slate-500">暂无采购单</div>

      <div v-else class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-slate-50 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <tr>
              <th class="p-4 text-left">采购单号</th>
              <th class="p-4 text-left">标题</th>
              <th class="p-4 text-left">状态</th>
              <th class="p-4 text-right">总金额</th>
              <th class="p-4 text-center">奖品数</th>
              <th class="p-4 text-center">附件数</th>
              <th class="p-4 text-left">创建时间</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="purchase in purchases"
              :key="purchase.id"
              class="border-t border-slate-200 dark:border-slate-700"
            >
              <td class="p-4 font-mono text-sm">
                {{ purchase.order_no }}
              </td>
              <td class="p-4">
                <p class="font-medium">{{ purchase.title }}</p>
                <p class="text-sm text-slate-500 dark:text-slate-400">
                  {{ purchase.items_summary }}
                </p>
              </td>
              <td class="whitespace-nowrap p-4">
                <span
                  :class="[
                    'inline-block whitespace-nowrap rounded-full px-3 py-1 text-sm',
                    statusClass(purchase.status),
                  ]"
                >
                  {{ statusLabel(purchase.status) }}
                </span>
              </td>
              <td class="p-4 text-right font-mono">
                {{ formatMoney(purchase.total_value) }}
              </td>
              <td class="p-4 text-center">
                {{ purchase.item_count }}
              </td>
              <td class="p-4 text-center">
                {{ purchase.attachment_count }}
              </td>
              <td class="p-4 text-sm text-slate-600 dark:text-slate-300">
                {{ formatDateTime(purchase.created_at) }}
              </td>
              <td class="p-4 text-right">
                <div class="flex justify-end gap-3 whitespace-nowrap text-sm">
                  <button
                    @click="openDetail(purchase)"
                    class="text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                  >
                    详情
                  </button>
                  <button
                    v-if="purchase.status === 'draft'"
                    @click="openEditModal(purchase)"
                    class="text-blue-600 hover:text-blue-700 dark:text-blue-400"
                  >
                    编辑
                  </button>
                  <button
                    v-if="purchase.status === 'draft'"
                    @click="openAttachments(purchase)"
                    class="text-violet-600 hover:text-violet-700 dark:text-violet-400"
                  >
                    附件
                  </button>
                  <button
                    v-if="purchase.attachment_count > 0"
                    @click="downloadPackage(purchase.id, purchase.order_no)"
                    class="text-emerald-600 hover:text-emerald-700 dark:text-emerald-400"
                  >
                    下载
                  </button>
                  <button
                    v-if="purchase.status === 'draft'"
                    @click="requestConfirm('reimburse', purchase)"
                    class="text-amber-600 hover:text-amber-700 dark:text-amber-400"
                    :disabled="!hasBothAttachmentTypes(purchase)"
                    :title="hasBothAttachmentTypes(purchase) ? '' : '需要先上传交易截图和发票 PDF'"
                  >
                    标记报销
                  </button>
                  <button
                    v-if="purchase.status === 'draft'"
                    @click="requestConfirm('cancel', purchase)"
                    class="text-orange-600 hover:text-orange-700 dark:text-orange-400"
                  >
                    取消
                  </button>
                  <button
                    v-if="purchase.status === 'draft' || purchase.status === 'cancelled'"
                    @click="requestConfirm('delete', purchase)"
                    class="text-red-600 hover:text-red-700 dark:text-red-400"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Create / Edit Modal -->
    <div
      v-if="showFormModal"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showFormModal = false"
    >
      <div class="card max-h-[90vh] w-full max-w-3xl overflow-auto">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">
            {{ editingId ? '编辑采购单' : '创建采购单' }}
          </h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="showFormModal = false">关闭</button>
        </div>

        <div class="mt-5 grid gap-4">
          <label class="text-sm font-medium">
            标题
            <input v-model="form.title" class="field mt-1" maxlength="200" placeholder="例如：618 奖品采购" required />
          </label>
          <label class="text-sm font-medium">
            备注
            <textarea v-model="form.note" class="field mt-1" rows="2" maxlength="2000" placeholder="可选备注信息" />
          </label>

          <!-- Prize Selection -->
          <div>
            <div class="flex items-center justify-between">
              <p class="text-sm font-medium">选择奖品</p>
              <p class="text-sm text-slate-500 dark:text-slate-400">
                已选 {{ selectedItemCount }} 项，合计：
                <span class="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                  {{ formatMoney(runningTotal) }}
                </span>
              </p>
            </div>
            <input v-model="prizeSearch" class="field mt-2" placeholder="搜索奖品名称或标签..." />

            <div
              v-if="prizesLoading"
              class="mt-3 rounded-lg border border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-slate-700"
            >
              加载奖品列表...
            </div>

            <div
              v-else-if="filteredPrizes.length === 0"
              class="mt-3 rounded-lg border border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-slate-700"
            >
              {{ prizeSearch ? '没有匹配的奖品' : '暂无可用奖品，请先在全局奖品池中添加' }}
            </div>

            <div v-else class="mt-3 max-h-80 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700">
              <table class="w-full text-sm">
                <thead class="sticky top-0 bg-slate-50 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <tr>
                    <th class="p-3 text-left">奖品</th>
                    <th class="p-3 text-right">单价</th>
                    <th class="p-3 text-center" style="width: 120px">数量</th>
                    <th class="p-3 text-right">小计</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="prize in filteredPrizes"
                    :key="prize.id"
                    class="border-t border-slate-200 dark:border-slate-700"
                    :class="{
                      'bg-blue-50 dark:bg-blue-950/30': getPrizeQuantity(prize.id) > 0,
                    }"
                  >
                    <td class="p-3">
                      <div class="flex items-center gap-2">
                        <img
                          v-if="prize.image"
                          :src="prize.image"
                          :alt="prize.name"
                          class="h-8 w-8 rounded object-cover"
                        />
                        <div>
                          <p class="font-medium">{{ prize.name }}</p>
                          <p v-if="prize.tag" class="text-xs text-slate-500 dark:text-slate-400">
                            {{ prize.tag }}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td class="p-3 text-right font-mono">
                      {{ formatMoney(prize.real_value) }}
                    </td>
                    <td class="p-3">
                      <input
                        type="number"
                        min="0"
                        max="9999"
                        :value="getPrizeQuantity(prize.id)"
                        @input="setPrizeQuantity(prize.id, Number(($event.target as HTMLInputElement).value))"
                        class="field w-full px-2 py-1 text-center"
                      />
                    </td>
                    <td class="p-3 text-right font-mono">
                      {{ formatMoney(prize.real_value * getPrizeQuantity(prize.id)) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="mt-6 flex justify-end gap-3">
          <button class="btn-secondary" type="button" @click="showFormModal = false">取消</button>
          <button class="btn-primary" :disabled="busy || selectedItemCount === 0" @click="submitForm">
            {{ busy ? '提交中...' : editingId ? '保存修改' : '创建采购单' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Detail Modal -->
    <div
      v-if="showDetailModal && detailOrder"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showDetailModal = false"
    >
      <div class="card max-h-[90vh] w-full max-w-3xl overflow-auto">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">采购单详情</h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="showDetailModal = false">
            关闭
          </button>
        </div>

        <div class="mt-5 grid gap-4">
          <div class="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p class="text-slate-500 dark:text-slate-400">采购单号</p>
              <p class="font-mono font-medium">{{ detailOrder.order_no }}</p>
            </div>
            <div>
              <p class="text-slate-500 dark:text-slate-400">状态</p>
              <span
                :class="[
                  'mt-1 inline-block whitespace-nowrap rounded-full px-3 py-1 text-sm',
                  statusClass(detailOrder.status),
                ]"
              >
                {{ statusLabel(detailOrder.status) }}
              </span>
            </div>
            <div>
              <p class="text-slate-500 dark:text-slate-400">标题</p>
              <p class="font-medium">{{ detailOrder.title }}</p>
            </div>
            <div>
              <p class="text-slate-500 dark:text-slate-400">总金额</p>
              <p class="font-mono font-semibold">
                {{ formatMoney(detailOrder.total_value) }}
              </p>
            </div>
            <div>
              <p class="text-slate-500 dark:text-slate-400">创建时间</p>
              <p>{{ formatDateTime(detailOrder.created_at) }}</p>
            </div>
            <div v-if="detailOrder.reimbursed_at">
              <p class="text-slate-500 dark:text-slate-400">报销时间</p>
              <p>{{ formatDateTime(detailOrder.reimbursed_at) }}</p>
            </div>
            <div v-if="detailOrder.cancelled_at">
              <p class="text-slate-500 dark:text-slate-400">取消时间</p>
              <p>{{ formatDateTime(detailOrder.cancelled_at) }}</p>
            </div>
          </div>

          <div v-if="detailOrder.note">
            <p class="text-sm text-slate-500 dark:text-slate-400">备注</p>
            <p class="mt-1 whitespace-pre-wrap text-sm">
              {{ detailOrder.note }}
            </p>
          </div>

          <!-- Items -->
          <div>
            <p class="text-sm font-medium">采购项 ({{ detailOrder.item_count }})</p>
            <div
              v-if="detailOrder.items && detailOrder.items.length > 0"
              class="mt-2 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700"
            >
              <table class="w-full text-sm">
                <thead class="bg-slate-50 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <tr>
                    <th class="p-3 text-left">奖品</th>
                    <th class="p-3 text-right">单价</th>
                    <th class="p-3 text-center">数量</th>
                    <th class="p-3 text-right">小计</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in detailOrder.items"
                    :key="item.id"
                    class="border-t border-slate-200 dark:border-slate-700"
                  >
                    <td class="p-3 font-medium">{{ item.prize_name }}</td>
                    <td class="p-3 text-right font-mono">
                      {{ formatMoney(item.unit_value) }}
                    </td>
                    <td class="p-3 text-center">{{ item.quantity }}</td>
                    <td class="p-3 text-right font-mono">
                      {{ formatMoney(item.line_value) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Attachments -->
          <div>
            <p class="text-sm font-medium">附件 ({{ detailOrder.attachment_count }})</p>
            <div
              v-if="detailOrder.attachments && detailOrder.attachments.length > 0"
              class="mt-2 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700"
            >
              <table class="w-full text-sm">
                <thead class="bg-slate-50 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <tr>
                    <th class="p-3 text-left">类型</th>
                    <th class="p-3 text-left">文件名</th>
                    <th class="p-3 text-right">大小</th>
                    <th class="p-3 text-left">上传时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="att in detailOrder.attachments"
                    :key="att.id"
                    class="border-t border-slate-200 dark:border-slate-700"
                  >
                    <td class="p-3">
                      <span
                        class="rounded-full bg-violet-100 px-2 py-0.5 text-xs text-violet-700 dark:bg-violet-900 dark:text-violet-300"
                      >
                        {{ kindLabel(att.kind) }}
                      </span>
                    </td>
                    <td class="p-3">{{ att.filename }}</td>
                    <td class="p-3 text-right text-slate-500 dark:text-slate-400">
                      {{ formatBytes(att.byte_size) }}
                    </td>
                    <td class="p-3 text-slate-500 dark:text-slate-400">
                      {{ formatDateTime(att.created_at) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="mt-2 text-sm text-slate-500 dark:text-slate-400">暂无附件</p>
          </div>
        </div>

        <div class="mt-6 flex justify-end gap-3">
          <button
            v-if="detailOrder.status === 'draft' && detailOrder.attachment_count > 0"
            class="btn-secondary"
            @click="downloadPackage(detailOrder!.id, detailOrder!.order_no)"
          >
            下载压缩包
          </button>
          <button class="btn-primary" @click="showDetailModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Attachment Modal -->
    <div
      v-if="showAttachmentModal && attachmentOrder"
      class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
      @click.self="showAttachmentModal = false"
    >
      <div class="card max-h-[90vh] w-full max-w-2xl overflow-auto">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold">管理附件</h2>
          <button type="button" class="text-slate-500 dark:text-slate-400" @click="showAttachmentModal = false">
            关闭
          </button>
        </div>

        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
          {{ attachmentOrder.order_no }} — {{ attachmentOrder.title }}
        </p>

        <!-- Upload buttons -->
        <div class="mt-5 grid gap-4 sm:grid-cols-2">
          <div class="rounded-lg border border-dashed border-slate-300 p-4 dark:border-slate-600">
            <p class="text-sm font-medium">交易截图</p>
            <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">JPEG / PNG / WebP，最大 5 MB</p>
            <button
              class="btn-secondary mt-3 w-full"
              :disabled="uploadingKind !== null || attachmentOrder.status !== 'draft'"
              @click="triggerUpload('transaction_screenshot')"
            >
              {{ uploadingKind === 'transaction_screenshot' ? '上传中...' : '上传截图' }}
            </button>
          </div>
          <div class="rounded-lg border border-dashed border-slate-300 p-4 dark:border-slate-600">
            <p class="text-sm font-medium">发票 PDF</p>
            <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">PDF 格式，最大 10 MB</p>
            <button
              class="btn-secondary mt-3 w-full"
              :disabled="uploadingKind !== null || attachmentOrder.status !== 'draft'"
              @click="triggerUpload('invoice_pdf')"
            >
              {{ uploadingKind === 'invoice_pdf' ? '上传中...' : '上传发票' }}
            </button>
          </div>
        </div>

        <!-- Current attachments -->
        <div class="mt-6">
          <p class="text-sm font-medium">当前附件 ({{ attachmentOrder.attachment_count }})</p>

          <div
            v-if="attachmentOrder.attachments && attachmentOrder.attachments.length > 0"
            class="mt-2 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700"
          >
            <table class="w-full min-w-[520px] text-sm">
              <thead class="bg-slate-50 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                <tr>
                  <th class="whitespace-nowrap p-3 text-left">类型</th>
                  <th class="p-3 text-left">文件名</th>
                  <th class="whitespace-nowrap p-3 text-right">大小</th>
                  <th class="whitespace-nowrap p-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="att in attachmentOrder.attachments"
                  :key="att.id"
                  class="border-t border-slate-200 dark:border-slate-700"
                >
                  <td class="whitespace-nowrap p-3">
                    <span
                      class="whitespace-nowrap rounded-full px-2 py-0.5 text-xs"
                      :class="
                        att.kind === 'transaction_screenshot'
                          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                      "
                    >
                      {{ kindLabel(att.kind) }}
                    </span>
                  </td>
                  <td class="max-w-[220px] break-all p-3">{{ att.filename }}</td>
                  <td class="whitespace-nowrap p-3 text-right text-slate-500 dark:text-slate-400">
                    {{ formatBytes(att.byte_size) }}
                  </td>
                  <td class="whitespace-nowrap p-3 text-right">
                    <button
                      v-if="attachmentOrder.status === 'draft'"
                      @click="deleteAttachment(att.id, att.kind)"
                      class="text-red-600 hover:text-red-700 dark:text-red-400"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="mt-2 text-sm text-slate-500 dark:text-slate-400">暂无附件</p>
        </div>

        <div class="mt-6 flex justify-end">
          <button class="btn-primary" @click="showAttachmentModal = false">完成</button>
        </div>
      </div>
    </div>

    <!-- Confirmation Dialog -->
    <div
      v-if="confirmAction"
      class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4"
      @click.self="confirmAction = null"
    >
      <div class="card w-full max-w-md">
        <h2 class="text-lg font-bold">
          {{
            confirmAction.kind === 'cancel' ? '确认取消' : confirmAction.kind === 'delete' ? '确认删除' : '确认标记报销'
          }}
        </h2>
        <p class="mt-3 text-sm text-slate-600 dark:text-slate-300">
          <template v-if="confirmAction.kind === 'cancel'">
            确定要取消采购单
            <strong>{{ confirmAction.order.order_no }}</strong>
            吗？取消后无法恢复。
          </template>
          <template v-else-if="confirmAction.kind === 'delete'">
            确定要删除采购单
            <strong>{{ confirmAction.order.order_no }}</strong>
            及其所有附件吗？此操作不可撤销。
          </template>
          <template v-else>
            确定将采购单
            <strong>{{ confirmAction.order.order_no }}</strong>
            标记为已报销吗？
          </template>
        </p>
        <div class="mt-6 flex justify-end gap-3">
          <button class="btn-secondary" @click="confirmAction = null" :disabled="busy">返回</button>
          <button
            class="btn-primary"
            :class="{
              'bg-red-600 hover:bg-red-700': confirmAction.kind === 'delete',
              'bg-orange-600 hover:bg-orange-700': confirmAction.kind === 'cancel',
              'bg-amber-600 hover:bg-amber-700': confirmAction.kind === 'reimburse',
            }"
            :disabled="busy"
            @click="executeConfirm"
          >
            {{ busy ? '处理中...' : '确认' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
