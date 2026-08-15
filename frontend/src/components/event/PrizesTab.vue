<script setup lang="ts">
    import { computed, inject, reactive, ref, watch } from 'vue'

    import { api, downloadAdmin } from '@/api/client'
    import type {
        PrizeBatchDeleteResult,
        PrizeBatchStock,
        PrizeBatchTag,
        PrizeImportPreview,
        PrizeRecord,
        PrizeWrite,
    } from '@/api/types'
    import { eventTabContextKey } from '@/components/event/eventContext'

    const context = inject(eventTabContextKey)!
    const { eventId, prizes, prizeSummary, error, notice, busy, load } = context

    const editingPrize = ref<PrizeRecord | null>(null)
    const showPrizeForm = ref(false)
    const imageMode = ref<'url' | 'upload'>('url')
    const importFile = ref<File | null>(null)
    const importPreview = ref<PrizeImportPreview | null>(null)
    const prizeForm = reactive({
        name: '',
        image: '',
        jd_url: '',
        realValueYuan: '0.00',
        purchaseValueYuan: '0.00',
        redeem_value: 1,
        stock: 0,
        description: '',
        tag: '',
        is_active: true,
    })

    function money(cents: number) {
        return `¥${(cents / 100).toFixed(2)}`
    }
    function showError(caught: unknown, fallback: string) {
        error.value = caught instanceof Error ? caught.message : fallback
    }

    function openPrize(prize?: PrizeRecord) {
        editingPrize.value = prize ?? null
        Object.assign(
            prizeForm,
            prize
                ? {
                    name: prize.name,
                    image: prize.image,
                    jd_url: prize.jd_url ?? '',
                    realValueYuan: (prize.real_value / 100).toFixed(2),
                    purchaseValueYuan: (prize.purchase_value / 100).toFixed(2),
                    redeem_value: prize.redeem_value,
                    stock: prize.stock,
                    description: prize.description ?? '',
                    tag: prize.tag ?? '',
                    is_active: prize.is_active,
                }
                : {
                    name: '',
                    image: '',
                    jd_url: '',
                    realValueYuan: '0.00',
                    purchaseValueYuan: '0.00',
                    redeem_value: 1,
                    stock: 0,
                    description: '',
                    tag: '',
                    is_active: true,
                },
        )
        imageMode.value = prize?.image.startsWith('/uploads/') ? 'upload' : 'url'
        showPrizeForm.value = true
    }

    async function savePrize() {
        const cents = Math.round(Number(prizeForm.realValueYuan) * 100)
        const purchaseCents = Math.round(Number(prizeForm.purchaseValueYuan) * 100)
        if (
            !Number.isFinite(cents) ||
            cents < 0 ||
            !/^\d+(\.\d{1,2})?$/.test(prizeForm.realValueYuan)
        ) {
            error.value = '真实采购单价必须是最多两位小数的非负金额'
            return
        }
        if (
            !Number.isFinite(purchaseCents) ||
            purchaseCents < 0 ||
            !/^\d+(\.\d{1,2})?$/.test(prizeForm.purchaseValueYuan)
        ) {
            error.value = '用户展示价格必须是最多两位小数的非负金额'
            return
        }
        const payload: PrizeWrite = {
            name: prizeForm.name,
            image: prizeForm.image,
            jd_url: prizeForm.jd_url || null,
            real_value: cents,
            purchase_value: purchaseCents,
            redeem_value: Number(prizeForm.redeem_value),
            stock: Number(prizeForm.stock),
            description: prizeForm.description || null,
            tag: prizeForm.tag.trim() || null,
            is_active: prizeForm.is_active,
        }
        busy.value = true
        error.value = ''
        try {
            if (editingPrize.value)
                await api(`/api/admin/prizes/${editingPrize.value.id}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload),
                })
            else
                await api(`/api/admin/events/${eventId}/prizes`, {
                    method: 'POST',
                    body: JSON.stringify(payload),
                })
            showPrizeForm.value = false
            notice.value = '奖品已保存'
            await load()
        } catch (caught) {
            showError(caught, '保存失败')
        } finally {
            busy.value = false
        }
    }

    async function uploadImage(file: File | undefined) {
        if (!file) return
        const data = new FormData()
        data.append('file', file)
        try {
            const result = await api<{ image: string }>(
                '/api/admin/uploads/prize-image',
                {
                    method: 'POST',
                    body: data,
                },
            )
            prizeForm.image = result.image
        } catch (caught) {
            showError(caught, '上传失败')
        }
    }

    async function removePrize(prize: PrizeRecord) {
        if (!window.confirm(`确认删除奖品“${prize.name}”？`)) return
        try {
            await api<void>(`/api/admin/prizes/${prize.id}`, { method: 'DELETE' })
            notice.value = '奖品已删除'
            await load()
        } catch (caught) {
            showError(caught, '删除失败')
        }
    }

    async function togglePrizeActive(prize: PrizeRecord) {
        const payload: PrizeWrite = {
            name: prize.name,
            image: prize.image,
            jd_url: prize.jd_url,
            real_value: prize.real_value,
            purchase_value: prize.purchase_value,
            redeem_value: prize.redeem_value,
            stock: prize.stock,
            description: prize.description,
            tag: prize.tag,
            is_active: !prize.is_active,
        }
        try {
            await api(`/api/admin/prizes/${prize.id}`, {
                method: 'PUT',
                body: JSON.stringify(payload),
            })
            notice.value = prize.is_active
                ? `已下架“${prize.name}”`
                : `已上架“${prize.name}”`
            await load()
        } catch (caught) {
            showError(caught, '操作失败')
        }
    }

    // Batch selection for the prize table.
    const selectedPrizeIds = ref(new Set<number>())
    const selectedCount = computed(() => selectedPrizeIds.value.size)
    const allPrizesSelected = computed(
        () =>
            prizes.value.length > 0 && selectedCount.value === prizes.value.length,
    )
    function clearSelection() {
        selectedPrizeIds.value = new Set<number>()
    }
    function togglePrizeSelected(id: number, checked: boolean) {
        const next = new Set(selectedPrizeIds.value)
        if (checked) next.add(id)
        else next.delete(id)
        selectedPrizeIds.value = next
    }
    function toggleAllPrizesSelected(checked: boolean) {
        selectedPrizeIds.value = checked
            ? new Set(prizes.value.map((prize) => prize.id))
            : new Set<number>()
    }
    // A reload replaces the prize list, so drop any stale selection.
    watch(prizes, clearSelection)

    const showBatchTagForm = ref(false)
    const batchTagValue = ref('')
    const showBatchStockForm = ref(false)
    const batchStockMode = ref<'delta' | 'set'>('delta')
    const batchStockValue = ref('0')

    function selectedIds() {
        return [...selectedPrizeIds.value]
    }

    async function submitBatchTag() {
        busy.value = true
        error.value = ''
        try {
            const body: PrizeBatchTag = {
                ids: selectedIds(),
                tag: batchTagValue.value.trim() || null,
            }
            const result = await api<{ updated: number }>(
                `/api/admin/events/${eventId}/prizes/batch-tag`,
                { method: 'POST', body: JSON.stringify(body) },
            )
            showBatchTagForm.value = false
            notice.value = `已更新 ${result.updated} 个奖品的标签`
            await load()
        } catch (caught) {
            showError(caught, '批量设置标签失败')
        } finally {
            busy.value = false
        }
    }

    async function submitBatchStock() {
        const value = Number(batchStockValue.value)
        if (!Number.isInteger(value)) {
            error.value = '库存必须是整数'
            return
        }
        busy.value = true
        error.value = ''
        try {
            const body: PrizeBatchStock = {
                ids: selectedIds(),
                mode: batchStockMode.value,
                value,
            }
            const result = await api<{ updated: number }>(
                `/api/admin/events/${eventId}/prizes/batch-stock`,
                { method: 'POST', body: JSON.stringify(body) },
            )
            showBatchStockForm.value = false
            notice.value = `已调整 ${result.updated} 个奖品的库存`
            await load()
        } catch (caught) {
            showError(caught, '批量调整库存失败')
        } finally {
            busy.value = false
        }
    }

    async function batchDeletePrizes() {
        const count = selectedCount.value
        if (!window.confirm(`确认删除选中的 ${count} 个奖品？被兑换记录引用的奖品将自动跳过。`))
            return
        busy.value = true
        error.value = ''
        try {
            const result = await api<PrizeBatchDeleteResult>(
                `/api/admin/events/${eventId}/prizes/batch-delete`,
                { method: 'POST', body: JSON.stringify({ ids: selectedIds() }) },
            )
            notice.value =
                `已删除 ${result.deleted} 个奖品` +
                (result.skipped.length
                    ? `，跳过：${result.skipped.map((item) => `“${item.name}”`).join('、')}`
                    : '')
            await load()
        } catch (caught) {
            showError(caught, '批量删除失败')
        } finally {
            busy.value = false
        }
    }

    async function validateImport(file: File | undefined) {
        if (!file) return
        importFile.value = file
        importPreview.value = null
        error.value = ''
        const data = new FormData()
        data.append('file', file)
        try {
            importPreview.value = await api<PrizeImportPreview>(
                `/api/admin/events/${eventId}/prizes/import/validate`,
                { method: 'POST', body: data },
            )
        } catch (caught) {
            showError(caught, '校验失败')
        }
    }

    async function confirmImport() {
        if (!importFile.value || !importPreview.value?.valid) return
        const data = new FormData()
        data.append('file', importFile.value)
        busy.value = true
        try {
            const result = await api<{ imported: number }>(
                `/api/admin/events/${eventId}/prizes/import/confirm`,
                { method: 'POST', body: data },
            )
            notice.value = `已导入 ${result.imported} 个奖品`
            importFile.value = null
            importPreview.value = null
            await load()
        } catch (caught) {
            showError(caught, '导入失败')
        } finally {
            busy.value = false
        }
    }
</script>

<template>
    <section class="mt-6">
        <div class="mb-5 grid gap-4 md:grid-cols-3">
            <article class="card">
                <p class="text-sm text-slate-500 dark:text-slate-400">奖品采购总额</p>
                <strong class="mt-2 block text-2xl">{{
                    money(prizeSummary.total_purchase_value)
                    }}</strong>
                <p class="mt-1 text-xs text-slate-400">含现有库存及已兑换奖品</p>
            </article>
            <article class="card">
                <p class="text-sm text-slate-500 dark:text-slate-400">已领取采购额</p>
                <strong class="mt-2 block text-2xl text-emerald-600 dark:text-emerald-400">{{
                    money(prizeSummary.claimed_purchase_value) }}</strong>
                <p class="mt-1 text-xs text-slate-400">仅统计已确认领取的奖品</p>
            </article>
            <article class="card">
                <p class="text-sm text-slate-500 dark:text-slate-400">比赛总预算</p>
                <strong class="mt-2 block text-2xl" :class="prizeSummary.total_purchase_value > prizeSummary.budget
                    ? 'text-red-600 dark:text-red-400'
                    : ''
                    ">{{ money(prizeSummary.budget) }}</strong>
                <p class="mt-1 text-xs" :class="prizeSummary.total_purchase_value > prizeSummary.budget
                    ? 'text-red-500 dark:text-red-400'
                    : 'text-slate-400 dark:text-slate-500'
                    ">
                    {{
                        prizeSummary.total_purchase_value > prizeSummary.budget
                            ? `采购总额已超预算 ${money(prizeSummary.total_purchase_value - prizeSummary.budget)}`
                            : `预算余量 ${money(prizeSummary.budget - prizeSummary.total_purchase_value)}`
                    }}
                </p>
            </article>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex flex-wrap items-center gap-2">
                <button class="btn-secondary" @click="
                    downloadAdmin(
                        `/api/admin/events/${eventId}/prizes/import/template?format=csv`,
                        'prizes-template.csv',
                    )
                    ">
                    CSV 模板
                </button>
                <button class="btn-secondary" @click="
                    downloadAdmin(
                        `/api/admin/events/${eventId}/prizes/import/template?format=xlsx`,
                        'prizes-template.xlsx',
                    )
                    ">
                    XLSX 模板
                </button>
                <button class="btn-secondary" @click="
                    downloadAdmin(
                        `/api/admin/events/${eventId}/prizes/export?format=csv`,
                        'prizes.csv',
                    )
                    ">
                    导出 CSV
                </button>
                <button class="btn-secondary" @click="
                    downloadAdmin(
                        `/api/admin/events/${eventId}/prizes/export?format=xlsx`,
                        'prizes.xlsx',
                    )
                    ">
                    导出 XLSX
                </button>
                <label class="btn-secondary cursor-pointer">导入表格<input class="hidden" type="file" accept=".csv,.xlsx"
                        @change="
                            validateImport(($event.target as HTMLInputElement).files?.[0])
                            " /></label>
            </div>
            <div v-if="selectedCount > 0"
                class="flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 p-[5px] dark:border-blue-900/60 dark:bg-blue-950/40">
                <strong class="text-sm text-blue-700 dark:text-blue-300">已选 {{ selectedCount }} 项</strong>
                <button
                    class="rounded-lg border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                    @click="showBatchTagForm = true">
                    添加标签
                </button>
                <button
                    class="rounded-lg border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                    @click="showBatchStockForm = true">
                    调整库存
                </button>
                <button
                    class="rounded-lg border border-red-300 bg-white px-3 py-1 text-sm font-medium text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/60 dark:bg-slate-900 dark:text-red-300 dark:hover:bg-red-950/40"
                    @click="batchDeletePrizes">
                    删除
                </button>
                <button class="text-sm text-slate-500 underline-offset-2 hover:underline dark:text-slate-400"
                    @click="clearSelection">
                    清除选择
                </button>
                <!-- </div> -->
            </div>
            <!-- Transparent border keeps this borderless primary button the same height as the bordered ones. -->
            <button class="btn-primary border border-transparent" @click="openPrize()">新增奖品</button>
        </div>

        <div v-if="importPreview" class="card mt-4">
            <h3 class="font-semibold">
                导入预览 · {{ importPreview.rows.length }} 行
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
                            <th class="p-2">名称</th>
                            <th class="p-2">京东链接</th>
                            <th class="p-2">真实采购价</th>
                            <th class="p-2">展示价格</th>
                            <th class="p-2">抵扣</th>
                            <th class="p-2">库存</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="(row, index) in importPreview.rows" :key="index"
                            class="border-t border-slate-200 dark:border-slate-700">
                            <td class="p-2">{{ row.name }}</td>
                            <td class="max-w-40 truncate p-2">{{ row.jd_url || '—' }}</td>
                            <td class="p-2">{{ row.real_value }}</td>
                            <td class="p-2">{{ row.purchase_value }}</td>
                            <td class="p-2">{{ row.redeem_value }}</td>
                            <td class="p-2">{{ row.stock }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <button class="btn-primary mt-4" :disabled="!importPreview.valid || busy" @click="confirmImport">
                确认全部导入
            </button>
        </div>



        <div
            class="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <table class="w-full min-w-[900px] text-left text-sm">
                <thead class="bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
                    <tr>
                        <th class="w-10 p-4">
                            <input type="checkbox" :checked="allPrizesSelected" aria-label="全选奖品" @change="
                                toggleAllPrizesSelected(
                                    ($event.target as HTMLInputElement).checked,
                                )
                                " />
                        </th>
                        <th class="p-4">奖品</th>
                        <th class="p-4">真实采购单价</th>
                        <th class="p-4">用户展示价格</th>
                        <th class="p-4">抵扣额度</th>
                        <th class="p-4">库存 / 待采购</th>
                        <th class="p-4">京东链接</th>
                        <th class="p-4 text-right">操作</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="prize in prizes" :key="prize.id" class="border-t border-slate-100 dark:border-slate-800">
                        <td class="p-4">
                            <input type="checkbox" :checked="selectedPrizeIds.has(prize.id)"
                                :aria-label="`选择 ${prize.name}`" @change="
                                    togglePrizeSelected(
                                        prize.id,
                                        ($event.target as HTMLInputElement).checked,
                                    )
                                    " />
                        </td>
                        <td class="p-4">
                            <div class="flex items-center gap-3">
                                <img :src="prize.image" :alt="prize.name" class="h-12 w-12 rounded-lg object-cover" />
                                <div>
                                    <strong>{{ prize.name }}</strong>
                                    <span v-if="prize.tag"
                                        class="ml-2 rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-950/40 dark:text-blue-300">{{
                                            prize.tag }}</span>
                                    <span v-if="!prize.is_active"
                                        class="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">已下架</span>
                                    <p class="max-w-xs truncate text-xs text-slate-500 dark:text-slate-400">
                                        {{ prize.description }}
                                    </p>
                                </div>
                            </div>
                        </td>
                        <td class="p-4">{{ money(prize.real_value) }}</td>
                        <td class="p-4 font-medium">{{ money(prize.purchase_value) }}</td>
                        <td class="p-4">{{ prize.redeem_value }}</td>
                        <td class="p-4" :class="prize.stock < 0
                            ? 'font-medium text-amber-600 dark:text-amber-400'
                            : ''
                            ">
                            {{
                                prize.stock < 0 ? `待采购 ${Math.abs(prize.stock)}` : prize.stock }} </td>
                        <td class="p-4">
                            <a v-if="prize.jd_url" :href="prize.jd_url" target="_blank" rel="noopener noreferrer"
                                class="text-blue-600 dark:text-blue-400 hover:underline">打开链接 ↗</a><span v-else
                                class="text-slate-400">—</span>
                        </td>
                        <td class="p-4 text-right">
                            <button class="text-blue-600 dark:text-blue-400" @click="openPrize(prize)">
                                编辑</button><button class="ml-4 text-amber-600 dark:text-amber-400"
                                @click="togglePrizeActive(prize)">
                                {{ prize.is_active ? '下架' : '上架' }}</button><button
                                class="ml-4 text-red-600 dark:text-red-400" @click="removePrize(prize)">
                                删除
                            </button>
                        </td>
                    </tr>
                    <tr v-if="prizes.length === 0">
                        <td colspan="8" class="p-10 text-center text-slate-500 dark:text-slate-400">
                            暂无奖品
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div v-if="showPrizeForm" class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
            @click.self="showPrizeForm = false">
            <form class="card max-h-[92vh] w-full max-w-xl overflow-auto" @submit.prevent="savePrize">
                <div class="flex justify-between">
                    <h2 class="text-xl font-bold">
                        {{ editingPrize ? '编辑奖品' : '新增奖品' }}
                    </h2>
                    <button type="button" @click="showPrizeForm = false">关闭</button>
                </div>
                <div class="mt-5 grid gap-4">
                    <label class="text-sm font-medium">名字<input v-model="prizeForm.name" class="field mt-1"
                            maxlength="200" required /></label>
                    <fieldset>
                        <legend class="text-sm font-medium">图片</legend>
                        <div class="mt-2 flex gap-4 text-sm">
                            <label><input v-model="imageMode" type="radio" value="url" /> HTTPS
                                外链</label><label><input v-model="imageMode" type="radio" value="upload" />
                                本地上传</label>
                        </div>
                        <input v-if="imageMode === 'url'" v-model="prizeForm.image" class="field mt-2" type="url"
                            pattern="https://.*" required />
                        <div v-else class="mt-2">
                            <input type="file" accept="image/jpeg,image/png,image/webp" @change="
                                uploadImage(($event.target as HTMLInputElement).files?.[0])
                                " />
                            <p v-if="prizeForm.image" class="mt-2 break-all text-xs text-slate-500 dark:text-slate-400">
                                {{ prizeForm.image }}
                            </p>
                        </div>
                    </fieldset>
                    <label class="text-sm font-medium">京东商品链接（选填）<input v-model="prizeForm.jd_url" class="field mt-1"
                            type="url" pattern="https://.*" maxlength="2000"
                            placeholder="https://item.jd.com/..." /><span
                            class="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400">填写后，用户选择奖品时可跳转查看商品详情</span></label>
                    <label class="text-sm font-medium">标签（选填）<input v-model="prizeForm.tag" class="field mt-1"
                            maxlength="100" placeholder="如 1-数码、2-生活" /><span
                            class="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400">用于兑换页按标签折叠分组展示，标签按文字排序（可用数字前缀控制顺序），留空归入默认组</span></label>
                    <fieldset>
                        <legend class="text-sm font-medium">上架状态</legend>
                        <div class="mt-2 flex gap-4 text-sm">
                            <label><input v-model="prizeForm.is_active" type="radio" :value="true" />
                                上架（用户端可见）</label><label><input v-model="prizeForm.is_active" type="radio"
                                    :value="false" />
                                下架（仅管理端可见）</label>
                        </div>
                    </fieldset>
                    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
                        <label class="text-sm font-medium">真实采购单价（元）<input v-model="prizeForm.realValueYuan"
                                class="field mt-1" inputmode="decimal" required /></label><label
                            class="text-sm font-medium">用户展示价格（元）<input v-model="prizeForm.purchaseValueYuan"
                                class="field mt-1" inputmode="decimal" required /></label><label
                            class="text-sm font-medium">抵扣额度<input v-model.number="prizeForm.redeem_value"
                                class="field mt-1" type="number" min="1" step="1" required /></label><label
                            class="text-sm font-medium">库存<input v-model.number="prizeForm.stock" class="field mt-1"
                                type="number" step="1" required /></label>
                    </div>
                    <label class="text-sm font-medium">描述<textarea v-model="prizeForm.description" class="field mt-1"
                            maxlength="5000" rows="4" />
                    </label>
                </div>
                <button class="btn-primary mt-6 w-full" :disabled="busy || !prizeForm.image">
                    保存奖品
                </button>
            </form>
        </div>

        <div v-if="showBatchTagForm" class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
            @click.self="showBatchTagForm = false">
            <form class="card w-full max-w-md" @submit.prevent="submitBatchTag">
                <div class="flex justify-between">
                    <h2 class="text-xl font-bold">批量设置标签</h2>
                    <button type="button" @click="showBatchTagForm = false">关闭</button>
                </div>
                <p class="mt-3 text-sm text-slate-500 dark:text-slate-400">
                    将覆盖 {{ selectedCount }} 个选中奖品的标签。
                </p>
                <label class="mt-4 block text-sm font-medium">标签<input v-model="batchTagValue" class="field mt-1"
                        maxlength="100" placeholder="如 1-数码、2-生活" /></label>
                <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    留空则清除选中奖品的标签。
                </p>
                <button class="btn-primary mt-6 w-full" :disabled="busy">
                    应用标签
                </button>
            </form>
        </div>

        <div v-if="showBatchStockForm" class="fixed inset-0 z-20 grid place-items-center bg-slate-950/40 p-4"
            @click.self="showBatchStockForm = false">
            <form class="card w-full max-w-md" @submit.prevent="submitBatchStock">
                <div class="flex justify-between">
                    <h2 class="text-xl font-bold">批量调整库存</h2>
                    <button type="button" @click="showBatchStockForm = false">关闭</button>
                </div>
                <p class="mt-3 text-sm text-slate-500 dark:text-slate-400">
                    将应用于 {{ selectedCount }} 个选中奖品。
                </p>
                <fieldset class="mt-4">
                    <legend class="text-sm font-medium">方式</legend>
                    <div class="mt-2 flex gap-4 text-sm">
                        <label><input v-model="batchStockMode" type="radio" value="delta" />
                            增减（如 +5、-3）</label><label><input v-model="batchStockMode" type="radio" value="set" />
                            设为指定值</label>
                    </div>
                </fieldset>
                <label class="mt-4 block text-sm font-medium">{{ batchStockMode === 'delta' ? '增减量' : '库存值'
                    }}<input v-model="batchStockValue" class="field mt-1" type="number" step="1" required /></label>
                <button class="btn-primary mt-6 w-full" :disabled="busy">
                    应用调整
                </button>
            </form>
        </div>
    </section>
</template>
