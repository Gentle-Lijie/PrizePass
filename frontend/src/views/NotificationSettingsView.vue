<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import type { NotificationJobRecord, NotificationTemplateRecord } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

interface SettingsResponse {
  templates: NotificationTemplateRecord[]
  configuration: { smtp: boolean; notification_email: boolean; webhook: boolean }
}

const auth = useAuthStore()
const router = useRouter()
const templates = ref<NotificationTemplateRecord[]>([])
const jobs = ref<NotificationJobRecord[]>([])
const configuration = reactive({ smtp: false, notification_email: false, webhook: false })
const email = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const eventLabels: Record<string, string> = {
  code_issued: '兑换码发放',
  redemption_submitted: '兑换已提交',
  redemption_ready: '奖品待领取',
  redemption_picked_up: '兑换已领取',
  redemption_cancelled: '兑换已取消',
}

function variableLabel(variable: string) { return `{{${variable}}}` }

async function load() {
  if (!auth.adminPassword) { await router.replace('/admin'); return }
  try {
    const [settings, recentJobs] = await Promise.all([
      api<SettingsResponse>('/api/admin/notification-templates'),
      api<NotificationJobRecord[]>('/api/admin/notification-jobs'),
    ])
    templates.value = settings.templates
    Object.assign(configuration, settings.configuration)
    jobs.value = recentJobs
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) await router.replace('/admin')
    else error.value = caught instanceof Error ? caught.message : '加载失败'
  }
}

async function saveTemplate(template: NotificationTemplateRecord) {
  busy.value = true; error.value = ''
  try {
    await api(`/api/admin/notification-templates/${template.event_type}`, { method: 'PUT', body: JSON.stringify({ text_template: template.text_template }) })
    notice.value = '模板已保存'
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '保存失败' }
  finally { busy.value = false }
}

async function testEmail() {
  busy.value = true; error.value = ''
  try { await api('/api/admin/notifications/test-email', { method: 'POST', body: JSON.stringify({ email: email.value }) }); notice.value = 'Email 测试任务已创建'; await load() }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '创建失败' }
  finally { busy.value = false }
}

async function testWebhook() {
  busy.value = true; error.value = ''
  try { await api('/api/admin/notifications/test-webhook', { method: 'POST' }); notice.value = 'Webhook 测试任务已创建'; await load() }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '创建失败' }
  finally { busy.value = false }
}

async function retry(job: NotificationJobRecord) {
  busy.value = true
  try { await api(`/api/admin/notification-jobs/${job.id}/retry`, { method: 'POST' }); notice.value = '失败任务已重新排队'; await load() }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '重试失败' }
  finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto max-w-6xl p-6 md:p-10">
    <RouterLink to="/admin/events" class="text-sm text-blue-600 hover:underline">← 返回比赛列表</RouterLink>
    <h1 class="mt-4 text-3xl font-bold">通知设置</h1>
    <p class="mt-2 text-sm text-slate-500">Email 与 Webhook 共用渲染文本、任务状态和重试逻辑。</p>
    <p v-if="error" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
    <p v-if="notice" class="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{{ notice }}</p>

    <section class="card mt-6">
      <h2 class="font-semibold">环境配置状态</h2>
      <div class="mt-4 flex flex-wrap gap-3">
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.smtp ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">SMTP {{ configuration.smtp ? '已配置' : '未配置' }}</span>
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.notification_email ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">运营邮箱 {{ configuration.notification_email ? '已配置' : '未配置' }}</span>
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.webhook ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">Webhook {{ configuration.webhook ? '已配置' : '未配置' }}</span>
      </div>
      <div class="mt-5 flex flex-wrap items-end gap-3"><label class="text-sm font-medium">测试收件地址<input v-model="email" class="field mt-1 w-72" type="email" placeholder="name@example.com" /></label><button class="btn-secondary" :disabled="busy || !email" @click="testEmail">创建 Email 测试任务</button><button class="btn-secondary" :disabled="busy || !configuration.webhook" @click="testWebhook">创建 Webhook 测试任务</button></div>
    </section>

    <section class="mt-8">
      <h2 class="text-xl font-bold">文本模板</h2>
      <div class="mt-4 grid gap-4">
        <article v-for="template in templates" :key="template.event_type" class="card">
          <div class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-semibold">{{ eventLabels[template.event_type] }}</h3><button class="btn-primary" :disabled="busy" @click="saveTemplate(template)">保存模板</button></div>
          <textarea v-model="template.text_template" class="field mt-4 min-h-28 font-mono text-sm" maxlength="20000" />
          <p class="mt-3 text-xs leading-6 text-slate-500">可用变量：<code v-for="variable in template.allowed_variables" :key="variable" class="mr-2 rounded bg-slate-100 px-1.5 py-1">{{ variableLabel(variable) }}</code></p>
        </article>
      </div>
    </section>

    <section class="mt-8">
      <h2 class="text-xl font-bold">最近通知任务</h2>
      <div class="mt-4 overflow-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full min-w-[900px] text-left text-sm"><thead class="bg-slate-50"><tr><th class="p-4">事件</th><th class="p-4">渠道</th><th class="p-4">目标</th><th class="p-4">状态</th><th class="p-4">尝试</th><th class="p-4">失败原因</th><th class="p-4">创建时间</th><th class="p-4"></th></tr></thead><tbody><tr v-for="job in jobs" :key="job.id" class="border-t"><td class="p-4">{{ eventLabels[job.event_type] }}</td><td class="p-4">{{ job.channel }}</td><td class="p-4">{{ job.destination }}</td><td class="p-4">{{ job.status }}</td><td class="p-4">{{ job.attempt_count }}</td><td class="max-w-xs truncate p-4 text-red-600" :title="job.last_error ?? ''">{{ job.last_error || '—' }}</td><td class="p-4">{{ new Date(job.created_at).toLocaleString() }}</td><td class="p-4"><button v-if="job.status === 'failed'" class="text-blue-600" :disabled="busy" @click="retry(job)">重试</button></td></tr><tr v-if="jobs.length === 0"><td colspan="8" class="p-10 text-center text-slate-500">暂无通知任务</td></tr></tbody></table>
      </div>
    </section>
  </main>
</template>
