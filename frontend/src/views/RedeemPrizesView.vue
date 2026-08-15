<script setup lang="ts">
    import { computed, onMounted, reactive, ref, watch } from 'vue'
    import { useRouter } from 'vue-router'
    import {
        CollapsibleContent,
        CollapsibleRoot,
        CollapsibleTrigger,
    } from 'reka-ui'

    import { api } from '@/api/client'
    import type { PublicPrize, RedemptionContext } from '@/api/types'
    import { useAuthStore } from '@/stores/auth'
    import { useRedemptionStore } from '@/stores/redemption'

    const auth = useAuthStore()
    const redemption = useRedemptionStore()
    const router = useRouter()
    const loading = ref(true)
    const error = ref('')
    const used = computed(() =>
        redemption.prizes.reduce(
            (sum, prize) =>
                sum + prize.redeem_value * (redemption.quantities[prize.id] ?? 0),
            0,
        ),
    )
    const remaining = computed(() => (redemption.context?.quota ?? 0) - used.value)
    const itemCount = computed(() =>
        Object.values(redemption.quantities).reduce(
            (sum, quantity) => sum + quantity,
            0,
        ),
    )
    // Prizes arrive sorted by tag (untagged last); group consecutive prizes so each
    // tag becomes one collapsible section and untagged prizes form the plain tail.
    const groups = computed(() => {
        const result: Array<{ tag: string | null; prizes: PublicPrize[] }> = []
        for (const prize of redemption.prizes) {
            const last = result[result.length - 1]
            if (last && last.tag === prize.tag) last.prizes.push(prize)
            else result.push({ tag: prize.tag, prizes: [prize] })
        }
        return result
    })
    // Collapse state keyed by tag; sections start expanded.
    const openGroups = reactive<Record<string, boolean>>({})
    function groupKey(tag: string | null) {
        return tag ?? ''
    }
    watch(groups, (next) => {
        for (const group of next)
            if (!(groupKey(group.tag) in openGroups))
                openGroups[groupKey(group.tag)] = true
    })
    const allCollapsed = computed(
        () =>
            groups.value.length > 0 &&
            groups.value.every((group) => !openGroups[groupKey(group.tag)]),
    )
    function toggleAllGroups() {
        // When everything is collapsed, expand all; otherwise collapse all.
        const next = allCollapsed.value
        for (const group of groups.value)
            openGroups[groupKey(group.tag)] = next
    }

    function money(cents: number) {
        return `¥${(cents / 100).toFixed(2)}`
    }
    function quantity(prize: PublicPrize) {
        return redemption.quantities[prize.id] ?? 0
    }
    function change(prize: PublicPrize, delta: number) {
        const next = quantity(prize) + delta
        if (next < 0) return
        if (next === 0) delete redemption.quantities[prize.id]
        else {
            // Picking a catalog prize replaces a custom wish; they are mutually exclusive.
            redemption.customPrize = null
            redemption.quantities[prize.id] = next
        }
    }

    // Custom prize wish: replaces the whole basket when applied.
    const showCustomForm = ref(false)
    const customForm = reactive({ name: '', url: '', note: '', priceYuan: '' })
    function openCustomForm() {
        customForm.name = redemption.customPrize?.name ?? ''
        customForm.url = redemption.customPrize?.url ?? ''
        customForm.note = redemption.customPrize?.note ?? ''
        customForm.priceYuan = redemption.customPrize?.priceYuan ?? ''
        showCustomForm.value = true
    }
    function applyCustomPrize() {
        if (!customForm.name.trim()) return
        if (customForm.priceYuan.trim() && !/^\d+(\.\d{1,2})?$/.test(customForm.priceYuan.trim())) {
            error.value = '期望价格必须是最多两位小数的非负金额'
            return
        }
        error.value = ''
        redemption.customPrize = {
            name: customForm.name.trim(),
            url: customForm.url.trim(),
            note: customForm.note.trim(),
            priceYuan: customForm.priceYuan.trim(),
        }
        redemption.quantities = {}
        showCustomForm.value = false
    }
    function removeCustomPrize() {
        redemption.customPrize = null
    }

    async function load() {
        loading.value = true
        error.value = ''
        if (!auth.redemptionCode) {
            await router.replace('/redeem')
            return
        }
        try {
            const [context, prizes] = await Promise.all([
                api<RedemptionContext>('/api/public/redemption/context'),
                api<PublicPrize[]>('/api/public/redemption/prizes'),
            ])
            redemption.context = context
            redemption.prizes = prizes
        } catch {
            auth.clearRedemptionCode()
            redemption.resetSelection()
            await router.replace('/redeem')
        } finally {
            loading.value = false
        }
    }

    async function continueToConfirm() {
        if (redemption.customPrize || (itemCount.value > 0 && remaining.value >= 0))
            await router.push('/redeem/confirm')
    }

    onMounted(load)
</script>

<template>
    <main class="mx-auto min-h-screen max-w-6xl p-4 pb-36 sm:p-6 sm:pb-28 md:p-10 md:pb-32">
        <section v-if="loading" class="card">正在加载奖品…</section>
        <template v-else-if="redemption.context">
            <header class="flex flex-wrap items-end justify-between gap-4">
                <div>
                    <p class="text-sm font-semibold text-blue-600 dark:text-blue-400">
                        {{ redemption.context.event.name }}
                    </p>
                    <h1 class="mt-1 text-2xl font-bold sm:text-3xl">
                        {{ redemption.context.winner.name }}，请选择奖品
                    </h1>
                    <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
                        可以选择多个奖品及数量，一次提交后兑换码将失效。
                    </p>
                </div>
                <div class="card flex w-full justify-around py-4 text-center">
                    <div>
                        <strong class="block text-xl">{{ redemption.context.quota }}</strong><span
                            class="text-xs text-slate-500 dark:text-slate-400">总 quota</span>
                    </div>
                    <div>
                        <strong class="block text-xl text-blue-600 dark:text-blue-400">{{
                            used
}}</strong><span class="text-xs text-slate-500 dark:text-slate-400">已使用</span>
                    </div>
                    <div>
                        <strong class="block text-xl text-emerald-600 dark:text-emerald-400">{{ remaining
                        }}</strong><span class="text-xs text-slate-500 dark:text-slate-400">剩余</span>
                    </div>
                </div>
            </header>
            <p v-if="error" class="mt-4 text-sm text-red-600 dark:text-red-400">
                {{ error }}
            </p>
            <div v-if="redemption.prizes.length === 0"
                class="card mt-6 text-center text-slate-500 sm:mt-8 dark:text-slate-400">
                当前没有可兑换的奖品
            </div>
            <div v-else class="mt-6 space-y-4 sm:mt-8 sm:space-y-5">
                <div class="flex justify-end">
                    <button type="button"
                        class="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                        @click="toggleAllGroups">
                        {{ allCollapsed ? '全部展开' : '全部折叠' }}
                    </button>
                </div>
                <CollapsibleRoot v-for="group in groups" :key="group.tag ?? '__untagged__'"
                    v-model:open="openGroups[groupKey(group.tag)]">
                    <CollapsibleTrigger class="card flex w-full items-center justify-between gap-3 p-4 text-left">
                        <span class="flex items-baseline gap-2">
                            <strong class="text-lg">{{ group.tag ?? '其他' }}</strong>
                            <span class="text-xs text-slate-500 dark:text-slate-400">{{ group.prizes.length }}
                                件奖品</span>
                        </span>
                        <svg class="h-5 w-5 shrink-0 text-slate-400 transition-transform"
                            :class="openGroups[groupKey(group.tag)] ? 'rotate-180' : ''" viewBox="0 0 20 20"
                            fill="currentColor" aria-hidden="true">
                            <path fill-rule="evenodd"
                                d="M5.22 7.22a.75.75 0 0 1 1.06 0L10 10.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 8.28a.75.75 0 0 1 0-1.06Z"
                                clip-rule="evenodd" />
                        </svg>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <section class="mt-3 grid gap-3 sm:mt-4 sm:gap-5 sm:grid-cols-2 lg:grid-cols-3">
                            <article v-for="prize in group.prizes" :key="prize.id" class="card overflow-hidden p-0">
                                <img :src="prize.image" :alt="prize.name"
                                    class="aspect-[4/3] w-full bg-slate-100 object-cover dark:bg-slate-800"
                                    loading="lazy" />
                                <div class="p-4 sm:p-5">
                                    <div
                                        class="flex flex-wrap items-start justify-between gap-2 sm:flex-nowrap sm:gap-3">
                                        <h2 class="min-w-0 text-lg font-bold">{{ prize.name }}</h2>
                                        <a v-if="prize.jd_url" :href="prize.jd_url" target="_blank"
                                            rel="noopener noreferrer"
                                            class="shrink-0 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-100 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-900/50 sm:px-3 sm:py-1.5">查看京东商品
                                            ↗</a>
                                    </div>
                                    <p class="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                                        {{ prize.description }}
                                    </p>
                                    <div class="mt-4 flex flex-wrap items-end justify-between gap-3">
                                        <div>
                                            <p class="text-xs text-slate-500 dark:text-slate-400">
                                                展示价格 {{ money(prize.purchase_value) }}
                                            </p>
                                            <p class="mt-1 font-semibold text-blue-600 dark:text-blue-400">
                                                {{ prize.redeem_value }} 额度 / 件
                                            </p>
                                        </div>
                                        <div class="flex items-center gap-3">
                                            <button
                                                class="grid h-9 w-9 place-items-center rounded-full border transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800"
                                                :disabled="quantity(prize) === 0" @click="change(prize, -1)">
                                                −</button><strong class="w-5 text-center">{{ quantity(prize)
                                                }}</strong><button
                                                class="grid h-9 w-9 place-items-center rounded-full border transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800"
                                                :disabled="remaining < prize.redeem_value || redemption.customPrize !== null"
                                                @click="change(prize, 1)">
                                                +
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </article>
                        </section>
                    </CollapsibleContent>
                </CollapsibleRoot>
            </div>

            <section class="card mt-4 sm:mt-6">
                <template v-if="redemption.customPrize">
                    <div class="flex flex-wrap items-center justify-between gap-3">
                        <div class="min-w-0">
                            <p class="text-xs font-semibold text-blue-600 dark:text-blue-400">
                                已选择自定义奖品（不能再选择列表中的奖品）
                            </p>
                            <strong class="mt-1 block break-words text-lg">{{
                                redemption.customPrize.name
                            }}</strong>
                            <p v-if="redemption.customPrize.priceYuan"
                                class="mt-1 text-sm font-semibold text-blue-600 dark:text-blue-400">
                                期望价格 ¥{{ redemption.customPrize.priceYuan }}
                            </p>
                            <a v-if="redemption.customPrize.url" :href="redemption.customPrize.url" target="_blank"
                                rel="noopener noreferrer"
                                class="mt-1 block break-all text-sm text-blue-600 dark:text-blue-400">{{
                                    redemption.customPrize.url }} ↗</a>
                            <p v-if="redemption.customPrize.note"
                                class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                备注：{{ redemption.customPrize.note }}
                            </p>
                        </div>
                        <div class="flex shrink-0 gap-2">
                            <button
                                class="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium transition hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
                                type="button" @click="openCustomForm">
                                修改
                            </button>
                            <button
                                class="rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-950/40"
                                type="button" @click="removeCustomPrize">
                                移除
                            </button>
                        </div>
                    </div>
                </template>
                <template v-else>
                    <div class="flex flex-wrap items-center justify-between gap-3">
                        <p class="text-sm text-slate-500 dark:text-slate-400">
                            列表里没有想要的奖品？可以填写一个自定义奖品作为兑换，选择后不能再选择列表中的奖品。
                        </p>
                        <button
                            class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
                            type="button" @click="openCustomForm">
                            填写自定义奖品
                        </button>
                    </div>
                </template>
            </section>

            <div v-if="showCustomForm" class="fixed inset-0 z-30 grid place-items-center bg-slate-950/40 p-4"
                @click.self="showCustomForm = false">
                <form class="card w-full max-w-md" @submit.prevent="applyCustomPrize">
                    <div class="flex justify-between">
                        <h2 class="text-xl font-bold">填写自定义奖品</h2>
                        <button type="button" @click="showCustomForm = false">关闭</button>
                    </div>
                    <div class="mt-5 grid gap-4">
                        <label class="text-sm font-medium">奖品名称<input v-model="customForm.name" class="field mt-1"
                                maxlength="200" placeholder="如 小米手环 9" required /></label>
                        <label class="text-sm font-medium">商品链接（选填）<input v-model="customForm.url" class="field mt-1"
                                type="url" pattern="https://.*" maxlength="2000"
                                placeholder="https://item.jd.com/..." /></label>
                        <label class="text-sm font-medium">期望价格（元，选填）<input v-model="customForm.priceYuan"
                                class="field mt-1" inputmode="decimal" placeholder="如 199.00" /></label>
                        <label class="text-sm font-medium">备注（选填）<textarea v-model="customForm.note" class="field mt-1"
                                maxlength="2000" rows="3" placeholder="颜色、规格等补充说明" /></label>
                    </div>
                    <p class="mt-3 text-xs text-amber-600 dark:text-amber-400">
                        提交后由管理员确认，结果会通过邮件通知你；被拒绝时兑换码会自动恢复。
                    </p>
                    <button class="btn-primary mt-6 w-full">保存自定义奖品</button>
                </form>
            </div>

            <div class="pointer-events-none fixed inset-x-0 bottom-0 z-10 h-36 bg-gradient-to-t from-canvas via-canvas/90 to-transparent backdrop-blur-[3px] sm:hidden"
                style="
          mask-image: linear-gradient(
            to top,
            black 0%,
            black 38%,
            transparent 100%
          );
          -webkit-mask-image: linear-gradient(
            to top,
            black 0%,
            black 38%,
            transparent 100%
          );
        "></div>
            <div class="fixed bottom-4 left-4 right-4 z-20 sm:sticky sm:bottom-4 sm:left-auto sm:right-auto sm:mt-8">
                <div
                    class="flex flex-col gap-3 rounded-xl bg-slate-950 p-3 text-white shadow-xl ring-1 ring-black/5 sm:flex-row sm:items-center sm:justify-between sm:p-4">
                    <div class="flex items-center justify-between gap-3 sm:block">
                        <template v-if="redemption.customPrize">
                            <strong>自定义奖品</strong><span class="text-sm text-slate-300">{{ redemption.customPrize.name
                            }}</span>
                        </template>
                        <template v-else>
                            <strong>{{ itemCount }} 件奖品</strong><span class="text-sm"
                                :class="remaining < 0 ? 'text-red-300' : 'text-slate-300'">消耗 {{ used }}，{{
                                    remaining < 0 ? `超出 ${Math.abs(remaining)}` : `剩余 ${remaining}` }}</span>
                        </template>
                    </div>
                    <button
                        class="w-full rounded-lg bg-white px-5 py-2 font-semibold text-slate-950 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                        :disabled="!redemption.customPrize && (itemCount === 0 || remaining < 0)"
                        @click="continueToConfirm">
                        填写领取信息
                    </button>
                </div>
            </div>
        </template>
    </main>
</template>
