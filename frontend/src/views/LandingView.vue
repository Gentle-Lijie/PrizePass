<script setup lang="ts">
    import { computed, ref } from 'vue'
    import { useRouter } from 'vue-router'
    import {
        ArrowRight,
        Bell,
        CheckCircle2,
        FileSpreadsheet,
        Gift,
        LayoutGrid,
        MapPin,
        Minus,
        PackageCheck,
        Plus,
        ShieldCheck,
        Ticket,
        Workflow,
    } from 'lucide-vue-next'

    const router = useRouter()

    /* ---------------- 角色切换 ---------------- */
    type Role = 'winner' | 'organizer'
    const role = ref<Role>('winner')

    const winnerFeatures = [
        {
            icon: Ticket,
            title: '一次性兑换码',
            desc: '每位获奖人收到独立兑换码，用一次即作废，安全不外泄。',
        },
        {
            icon: LayoutGrid,
            title: '额度内自由组合',
            desc: '在专属额度里挑喜欢的奖品、调整数量，凑满为止。',
        },
        {
            icon: PackageCheck,
            title: '实时库存',
            desc: '库存随大家的选择实时更新，选得到就能领到。',
        },
        {
            icon: MapPin,
            title: '到点自提',
            desc: '提交后凭单号到固定地点领取，地点和说明一目了然。',
        },
    ]
    const organizerFeatures = [
        {
            icon: ShieldCheck,
            title: '单密码管理',
            desc: '没有用户表和复杂权限，一个环境变量密码管全部比赛。',
        },
        {
            icon: Gift,
            title: '六字段奖品',
            desc: '名称、图片、真实价、展示价、抵扣额度、库存，逐项可控。',
        },
        {
            icon: FileSpreadsheet,
            title: '批量导入',
            desc: 'CSV / XLSX 原子导入奖品与获奖人，一行出错整批拒绝。',
        },
        {
            icon: Workflow,
            title: '状态机流转',
            desc: '提交 → 备货 → 已领取，取消即恢复库存与兑换码。',
        },
    ]

    const features = computed(() =>
        role.value === 'winner' ? winnerFeatures : organizerFeatures,
    )

    /* ---------------- 额度兑换演示 ---------------- */
    const QUOTA = 100
    const demoPrizes = [
        { id: 1, name: '机械键盘', value: 40, emoji: '⌨️' },
        { id: 2, name: '无线耳机', value: 35, emoji: '🎧' },
        { id: 3, name: '品牌帆布袋', value: 20, emoji: '👜' },
        { id: 4, name: '定制马克杯', value: 15, emoji: '☕' },
    ]
    const cart = ref<Record<number, number>>({})
    const demoSubmitted = ref(false)

    const used = computed(() =>
        demoPrizes.reduce((sum, p) => sum + p.value * (cart.value[p.id] ?? 0), 0),
    )
    const remaining = computed(() => QUOTA - used.value)
    const progress = computed(() => Math.min(100, (used.value / QUOTA) * 100))
    const pickedCount = computed(() =>
        Object.values(cart.value).reduce((s, n) => s + n, 0),
    )

    function add(p: { id: number; value: number }) {
        if (remaining.value >= p.value) cart.value[p.id] = (cart.value[p.id] ?? 0) + 1
    }
    function sub(p: { id: number }) {
        const q = cart.value[p.id] ?? 0
        if (q > 0) cart.value[p.id] = q - 1
    }

    function submitDemo() {
        if (pickedCount.value === 0) add(demoPrizes[0]!)
        demoSubmitted.value = true
    }

    function closeDemoResult() {
        demoSubmitted.value = false
    }

    const steps = [
        {
            n: '01',
            title: '创建比赛',
            desc: '设置自提地点、领取说明和兑换截止时间。',
        },
        {
            n: '02',
            title: '导入奖品与获奖人',
            desc: '批量上传，系统自动生成兑换码并排队发通知。',
        },
        {
            n: '03',
            title: '发放兑换码',
            desc: '通过邮件、email-poster 与 Webhook 多渠道送达。',
        },
        {
            n: '04',
            title: '获奖人自选提交',
            desc: '凭码在额度内挑选奖品，一次提交确认。',
        },
        {
            n: '05',
            title: '备货与领取',
            desc: '依次推进到备货、已领取，必要时取消并恢复。',
        },
    ]

    /* ---------------- 滚动渐入 ---------------- */
    const vReveal = {
        mounted(el: HTMLElement) {
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
            el.classList.add('reveal')
            const io = new IntersectionObserver(
                (entries) => {
                    entries.forEach((entry) => {
                        if (entry.isIntersecting) {
                            entry.target.classList.add('reveal-in')
                            io.unobserve(entry.target)
                        }
                    })
                },
                { threshold: 0.12 },
            )
            io.observe(el)
        },
    }

    function goRedeem() {
        router.push('/redeem')
    }
    function goAdmin() {
        router.push('/admin')
    }
</script>

<template>
    <div class="min-h-screen bg-canvas text-ink">
        <!-- 顶栏 -->
        <header
            class="sticky top-0 z-40 border-b border-slate-200/70 bg-white/80 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/80">
            <div class="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
                <a href="/" class="flex items-center gap-2.5">
                    <span class="grid h-8 w-8 place-items-center rounded-lg bg-accent font-bold text-white">P</span>
                    <span
                        class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400">PrizePass</span>
                </a>
                <nav class="flex items-center gap-2 sm:gap-3">
                    <button
                        class="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition hover:text-ink dark:text-slate-300 dark:hover:text-white sm:block"
                        @click="goAdmin">
                        管理后台
                    </button>
                    <button class="btn-primary" @click="goRedeem">兑换奖品</button>
                </nav>
            </div>
        </header>

        <!-- Hero -->
        <section
            class="bg-gradient-to-br from-blue-50 via-white to-indigo-50 dark:from-slate-900 dark:via-slate-950 dark:to-slate-900">
            <div class="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-2 lg:py-28">
                <div v-reveal>
                    <p class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400">
                        PrizePass
                    </p>
                    <h1 class="mt-3 text-5xl font-bold leading-[1.08] tracking-tight sm:text-6xl">
                        奖品，你自己挑。
                    </h1>
                    <p class="mt-5 max-w-md text-base leading-relaxed text-slate-600 dark:text-slate-300">
                        在专属额度里挑你真正想要的，调整数量、自由组合，挑满为止，到点自提。
                    </p>
                    <div class="mt-8 flex flex-wrap gap-3">
                        <button class="btn-primary inline-flex items-center gap-2" @click="goRedeem">
                            开始兑换
                            <ArrowRight class="h-4 w-4" />
                        </button>
                        <button class="btn-secondary" @click="goAdmin">进入管理后台</button>
                    </div>
                    <dl
                        class="mt-10 grid max-w-md grid-cols-3 gap-4 border-t border-slate-200 pt-6 dark:border-slate-700">
                        <div>
                            <dt class="text-2xl font-bold text-ink">6</dt>
                            <dd class="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                种通知模板
                            </dd>
                        </div>
                        <div>
                            <dt class="text-2xl font-bold text-ink">3+</dt>
                            <dd class="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                种通知渠道
                            </dd>
                        </div>
                        <div>
                            <dt class="text-2xl font-bold text-ink">0</dt>
                            <dd class="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                Cookie / Token
                            </dd>
                        </div>
                    </dl>
                </div>

                <!-- 额度兑换演示卡 -->
                <div v-reveal
                    class="flex h-[65vh] flex-col rounded-2xl bg-slate-950 p-5 text-white shadow-xl ring-1 ring-white/10 sm:p-6">
                    <div class="flex items-center justify-between">
                        <p class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-400">
                            体验兑换
                        </p>
                        <span
                            class="rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-medium text-emerald-300">实时库存</span>
                    </div>
                    <div class="mt-5 min-h-0 flex-1">
                        <div v-if="demoSubmitted" class="grid h-full place-items-center">
                            <div class="text-center">
                                <CheckCircle2 class="mx-auto h-12 w-12 text-emerald-400" />
                                <h3 class="mt-5 text-xl font-semibold text-white">
                                    已提交待备货
                                </h3>
                                <p class="mt-2 text-sm text-slate-400">请关注邮件通知</p>
                                <button type="button"
                                    class="mt-8 rounded-xl bg-white px-8 py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
                                    @click="closeDemoResult">
                                    确定
                                </button>
                            </div>
                        </div>

                        <div v-else>
                            <div class="flex items-end justify-between text-sm">
                                <span class="text-slate-400">已用额度</span>
                                <span class="font-mono"><span class="text-lg font-bold text-white">{{ used
                                        }}</span><span class="text-slate-500"> / {{ QUOTA }}</span></span>
                            </div>
                            <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
                                <div class="h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-400 transition-all duration-300"
                                    :style="{ width: `${progress}%` }" />
                            </div>
                            <p class="mt-2 text-right text-xs text-slate-500">
                                剩余 {{ remaining }}
                            </p>
                            <ul class="mt-5 space-y-2">
                                <li v-for="p in demoPrizes" :key="p.id"
                                    class="flex items-center gap-3 rounded-xl bg-slate-900 p-3">
                                    <span
                                        class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-800 text-lg">{{
                                            p.emoji }}</span>
                                    <div class="min-w-0 flex-1">
                                        <p class="truncate text-sm font-medium">{{ p.name }}</p>
                                        <p class="text-xs text-slate-500">抵扣 {{ p.value }}</p>
                                    </div>
                                    <div class="flex items-center gap-1.5">
                                        <button
                                            class="grid h-7 w-7 place-items-center rounded-md bg-slate-800 text-slate-300 transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-30"
                                            :disabled="!cart[p.id]" aria-label="减少" @click="sub(p)">
                                            <Minus class="h-3.5 w-3.5" />
                                        </button>
                                        <span class="w-5 text-center font-mono text-sm">{{
                                            cart[p.id] ?? 0
                                            }}</span>
                                        <button
                                            class="grid h-7 w-7 place-items-center rounded-md bg-blue-600 text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-30"
                                            :disabled="remaining < p.value" aria-label="增加" @click="add(p)">
                                            <Plus class="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                </li>
                            </ul>

                            <form class="mt-5" @submit.prevent="submitDemo">
                                <button type="submit"
                                    class="flex w-full items-center justify-center gap-2 rounded-xl bg-white py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-100">
                                    提交体验选择
                                    <ArrowRight class="h-4 w-4" />
                                </button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 角色切换功能 -->
        <section class="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
            <div v-reveal class="mx-auto max-w-2xl text-center">
                <h2 class="text-3xl font-bold tracking-tight sm:text-4xl">
                    为两种角色而生
                </h2>
                <p class="mt-3 text-slate-600 dark:text-slate-300">
                    无论是领奖人还是组织者，都能在两步之内开始。
                </p>
            </div>

            <div v-reveal class="mt-10 flex justify-center">
                <div
                    class="inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900">
                    <button class="rounded-lg px-5 py-2 text-sm font-medium transition" :class="role === 'winner'
                        ? 'bg-accent text-white'
                        : 'text-slate-600 hover:text-ink dark:text-slate-300 dark:hover:text-white'
                        " @click="role = 'winner'">
                        我是获奖人
                    </button>
                    <button class="rounded-lg px-5 py-2 text-sm font-medium transition" :class="role === 'organizer'
                        ? 'bg-accent text-white'
                        : 'text-slate-600 hover:text-ink dark:text-slate-300 dark:hover:text-white'
                        " @click="role = 'organizer'">
                        我是组织者
                    </button>
                </div>
            </div>

            <div class="mt-10 grid gap-5 sm:grid-cols-2">
                <div v-for="(f, i) in features" :key="f.title" v-reveal
                    class="group rounded-2xl border border-slate-200 bg-white p-6 transition hover:-translate-y-1 hover:border-blue-200 hover:shadow-md dark:border-slate-700 dark:bg-slate-900 dark:hover:border-blue-500"
                    :style="{ transitionDelay: `${i * 40}ms` }">
                    <div
                        class="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-accent transition group-hover:bg-accent group-hover:text-white dark:bg-blue-950/50">
                        <component :is="f.icon" class="h-5 w-5" />
                    </div>
                    <h3 class="mt-4 text-lg font-semibold">{{ f.title }}</h3>
                    <p class="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                        {{ f.desc }}
                    </p>
                </div>
            </div>
        </section>

        <!-- 流程时间线 -->
        <section class="border-y border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
                <div v-reveal class="max-w-2xl">
                    <h2 class="text-3xl font-bold tracking-tight sm:text-4xl">
                        从建赛到领取，一条直线
                    </h2>
                    <p class="mt-3 text-slate-600 dark:text-slate-300">
                        五步走完整个流程，每一步的状态都可追溯、可回滚。
                    </p>
                </div>
                <ol class="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-5">
                    <li v-for="s in steps" :key="s.n" v-reveal
                        class="relative rounded-2xl border border-slate-200 bg-canvas p-5 dark:border-slate-700">
                        <span class="font-mono text-sm font-bold text-blue-600 dark:text-blue-400">{{ s.n }}</span>
                        <h3 class="mt-2 font-semibold">{{ s.title }}</h3>
                        <p class="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                            {{ s.desc }}
                        </p>
                    </li>
                </ol>
            </div>
        </section>

        <!-- 通知系统 -->
        <section class="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
            <div class="grid items-center gap-10 lg:grid-cols-2">
                <div v-reveal>
                    <span
                        class="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-accent dark:bg-blue-950/50 dark:text-blue-300">
                        <Bell class="h-3.5 w-3.5" /> 多渠道通知
                    </span>
                    <h2 class="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
                        每个场景，独立路由
                    </h2>
                    <p class="mt-4 text-slate-600 dark:text-slate-300">
                        同时支持 SMTP 邮件、email-poster HTTP 转发与固定
                        Webhook。兑换码发放、待领取、已提交、已领取、取消……每个场景都能单独选择走哪些渠道，发给获奖人还是运营邮箱。
                    </p>
                    <ul class="mt-6 space-y-2.5 text-sm text-slate-700 dark:text-slate-300">
                        <li class="flex items-center gap-2">
                            <span class="text-emerald-600">✓</span> 失败按 1 分钟、5
                            分钟自动重试
                        </li>
                        <li class="flex items-center gap-2">
                            <span class="text-emerald-600">✓</span> 纯文本与 HTML 双模板
                        </li>
                        <li class="flex items-center gap-2">
                            <span class="text-emerald-600">✓</span> 通知任务监控与手工重试
                        </li>
                    </ul>
                </div>
                <div v-reveal
                    class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
                    <p class="text-xs font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">
                        场景路由示意
                    </p>
                    <div class="mt-4 space-y-3">
                        <div v-for="row in [
                            { s: '兑换码发放', c: '邮件 · Webhook' },
                            { s: '奖品待领取', c: '邮件 · Webhook' },
                            { s: '兑换已提交', c: '运营邮箱 · Webhook' },
                            { s: '兑换已领取', c: '运营邮箱 · Webhook' },
                        ]" :key="row.s" class="flex items-center justify-between rounded-xl bg-canvas px-4 py-3">
                            <span class="text-sm font-medium">{{ row.s }}</span>
                            <span class="text-xs text-slate-500 dark:text-slate-400">{{
                                row.c
                                }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 最终 CTA -->
        <section class="bg-slate-950">
            <div class="mx-auto max-w-4xl px-4 py-16 text-center sm:px-6 sm:py-24">
                <h2 v-reveal class="text-3xl font-bold tracking-tight text-white sm:text-4xl">
                    准备好开始了吗？
                </h2>
                <p v-reveal class="mx-auto mt-3 max-w-md text-slate-400">
                    获奖人凭码入场，组织者凭密码管理。刷新即清，安全轻量。
                </p>
                <div v-reveal class="mt-8 flex flex-wrap justify-center gap-3">
                    <button
                        class="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 font-medium text-slate-900 transition hover:bg-slate-100"
                        @click="goRedeem">
                        兑换奖品
                        <ArrowRight class="h-4 w-4" />
                    </button>
                    <button
                        class="rounded-lg border border-slate-700 px-5 py-2.5 font-medium text-white transition hover:bg-slate-800"
                        @click="goAdmin">
                        进入管理后台
                    </button>
                </div>
            </div>
        </section>

        <!-- 页脚 -->
        <footer class="border-t border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div
                class="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 sm:flex-row sm:px-6">
                <div class="flex items-center gap-2.5">
                    <span
                        class="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm font-bold text-white">P</span>
                    <span
                        class="text-sm font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400">PrizePass</span>
                </div>
                <p class="text-xs text-slate-500 dark:text-slate-400">
                    Made with ❤️ by
                    <a href="https://github.com/Gentle-Lijie" target="_blank" rel="noopener noreferrer"
                        class="text-blue-600 hover:underline dark:text-blue-400">GentleLijie</a>
                    · 比赛奖品兑换平台 · 轻量、安全、到点自提
                </p>
            </div>
        </footer>
    </div>
</template>

<style scoped>
    .reveal {
        opacity: 0;
        transform: translateY(16px);
        transition:
            opacity 0.6s ease,
            transform 0.6s ease;
    }

    .reveal-in {
        opacity: 1;
        transform: none;
    }
</style>
