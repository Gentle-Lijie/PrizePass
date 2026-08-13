<script setup lang="ts">
    import { onBeforeUnmount, onMounted, reactive, ref } from 'vue';
    import { RouterLink, useRouter } from 'vue-router';

    import { api, ApiError } from '@/api/client';
    import type { NotificationJobRecord, NotificationRoutingRecord, NotificationTemplateRecord } from '@/api/types';
    import { useAuthStore } from '@/stores/auth';

    interface SettingsResponse {
        templates: NotificationTemplateRecord[];
        routing: NotificationRoutingRecord[];
        configuration: { smtp: boolean; notification_email: boolean; webhook: boolean; email_poster: boolean };
    }

    const auth = useAuthStore();
    const router = useRouter();
    const templates = ref<NotificationTemplateRecord[]>([]);
    const routing = ref<NotificationRoutingRecord[]>([]);
    const jobs = ref<NotificationJobRecord[]>([]);
    const configuration = reactive({ smtp: false, notification_email: false, webhook: false, email_poster: false });
    const email = ref('');
    const error = ref('');
    const notice = ref('');
    const busy = ref(false);
    const preview = ref<{ title: string; html: string } | null>(null);
    const eventLabels: Record<string, string> = {
        code_issued: '兑换码发放',
        redemption_submitted: '兑换已提交',
        redemption_ready: '奖品待领取',
        redemption_picked_up: '兑换已领取',
        redemption_cancelled: '兑换已取消',
    };

    function variableLabel(variable: string) {
        return `{{${variable}}}`;
    }

    const previewVariables: Record<string, string> = {
        winner_name: '张三',
        winner_email: 'winner@example.com',
        event_name: 'PrizePass 示例比赛',
        code: 'PP-2026-DEMO',
        quota: '500',
        redemption_url: 'https://example.com/redeem',
        deadline: '2026-08-31 18:00:00',
        order_no: 'PP202608130001',
        items_summary: '机械键盘 × 1、保温杯 × 1',
        total_redeem_value: '450',
        unused_quota: '50',
        status: '待领取',
        pickup_location: '园区一层服务台',
        pickup_instructions: '工作日 10:00–17:00，出示兑换单号领取。',
    };

    function escapeHtml(value: string) {
        const entities: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };
        return value.replace(/[&<>"']/g, (character) => entities[character] ?? character);
    }

    function openHtmlPreview(template: NotificationTemplateRecord) {
        if (!template.html_template?.trim()) return;
        const html = template.html_template.replace(/{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}/g, (placeholder, variable: string) => {
            const value = previewVariables[variable];
            return value === undefined ? placeholder : escapeHtml(value);
        });
        preview.value = { title: eventLabels[template.event_type] ?? template.event_type, html };
    }

    function closePreview() {
        preview.value = null;
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Escape') closePreview();
    }

    async function load() {
        if (!auth.adminPassword) {
            await router.replace('/admin');
            return;
        }
        try {
            const [settings, recentJobs] = await Promise.all([api<SettingsResponse>('/api/admin/notification-templates'), api<NotificationJobRecord[]>('/api/admin/notification-jobs')]);
            templates.value = settings.templates;
            routing.value = settings.routing;
            Object.assign(configuration, settings.configuration);
            jobs.value = recentJobs;
        } catch (caught) {
            if (caught instanceof ApiError && caught.status === 401) await router.replace('/admin');
            else error.value = caught instanceof Error ? caught.message : '加载失败';
        }
    }

    async function refreshForm() {
        busy.value = true;
        error.value = '';
        try {
            await load();
            notice.value = '表单数据已刷新';
        } finally {
            busy.value = false;
        }
    }

    async function saveTemplate(template: NotificationTemplateRecord) {
        busy.value = true;
        error.value = '';
        try {
            await api(`/api/admin/notification-templates/${template.event_type}`, {
                method: 'PUT',
                body: JSON.stringify({ text_template: template.text_template, html_template: template.html_template }),
            });
            notice.value = '模板已保存';
            await load();
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '保存失败';
        } finally {
            busy.value = false;
        }
    }

    async function saveRouting() {
        busy.value = true;
        error.value = '';
        try {
            const response = await api<{ routing: NotificationRoutingRecord[] }>('/api/admin/notification-routing', {
                method: 'PUT',
                body: JSON.stringify({ routes: routing.value }),
            });
            routing.value = response.routing;
            notice.value = '通知路由已保存，仅影响之后创建的通知任务';
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '保存失败';
        } finally {
            busy.value = false;
        }
    }

    async function testEmail() {
        busy.value = true;
        error.value = '';
        try {
            await api('/api/admin/notifications/test-email', { method: 'POST', body: JSON.stringify({ email: email.value }) });
            notice.value = 'Email 测试任务已创建';
            await load();
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '创建失败';
        } finally {
            busy.value = false;
        }
    }

    async function testWebhook() {
        busy.value = true;
        error.value = '';
        try {
            await api('/api/admin/notifications/test-webhook', { method: 'POST' });
            notice.value = 'Webhook 测试任务已创建';
            await load();
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '创建失败';
        } finally {
            busy.value = false;
        }
    }

    async function testEmailPoster() {
        busy.value = true;
        error.value = '';
        try {
            await api('/api/admin/notifications/test-email-poster', { method: 'POST', body: JSON.stringify({ email: email.value }) });
            notice.value = 'email-poster 测试任务已创建';
            await load();
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '创建失败';
        } finally {
            busy.value = false;
        }
    }

    async function retry(job: NotificationJobRecord) {
        busy.value = true;
        try {
            await api(`/api/admin/notification-jobs/${job.id}/retry`, { method: 'POST' });
            notice.value = '失败任务已重新排队';
            await load();
        } catch (caught) {
            error.value = caught instanceof Error ? caught.message : '重试失败';
        } finally {
            busy.value = false;
        }
    }

    onMounted(() => {
        void load();
        window.addEventListener('keydown', handleKeydown);
    });
    onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown));
</script>

<template>
  <main class="mx-auto max-w-6xl p-6 md:p-10">
    <RouterLink to="/admin/events" class="text-sm text-blue-600 hover:underline">← 返回比赛列表</RouterLink>
    <h1 class="mt-4 text-3xl font-bold">通知设置</h1>
    <p class="mt-2 text-sm text-slate-500">SMTP、email-poster 与 Webhook 共用任务状态和重试逻辑；邮件同时保留纯文本与 HTML 正文。</p>
    <p v-if="error" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
    <p v-if="notice" class="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{{ notice }}</p>

    <section class="card mt-6">
      <h2 class="font-semibold">环境配置状态</h2>
      <div class="mt-4 flex flex-wrap gap-3">
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.smtp ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">SMTP {{ configuration.smtp ? '已配置' : '未配置' }}</span>
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.notification_email ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">运营邮箱 {{ configuration.notification_email ? '已配置' : '未配置' }}</span>
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.webhook ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">Webhook {{ configuration.webhook ? '已配置' : '未配置' }}</span>
        <span class="rounded-full px-3 py-1 text-sm" :class="configuration.email_poster ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">email-poster {{ configuration.email_poster ? '已配置' : '未配置' }}</span>
      </div>
      <div class="mt-5 flex flex-wrap items-end gap-3">
        <!-- <label class="text-sm font-medium">测试收件地址</label> -->
        <input v-model="email" class="field mt-1 w-full sm:w-72" type="email" placeholder="name@example.com" /><button class="btn-secondary w-full sm:w-auto" :disabled="busy || !email" @click="testEmail">创建 SMTP 测试任务</button><button class="btn-secondary w-full sm:w-auto" :disabled="busy || !email || !configuration.email_poster" @click="testEmailPoster">创建 email-poster 测试任务</button><button class="btn-secondary w-full sm:w-auto" :disabled="busy || !configuration.webhook" @click="testWebhook">创建 Webhook 测试任务</button>
      </div>
    </section>

    <section class="mt-8">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-xl font-bold">场景通知路由</h2>
          <p class="mt-2 text-sm text-slate-500">可为同一场景选择多个渠道和收件对象；设置仅影响之后创建的任务。</p>
        </div>
        <div class="flex gap-2"><button class="btn-secondary" type="button" :disabled="busy" @click="refreshForm">刷新表单</button><button class="btn-primary" :disabled="busy" @click="saveRouting">保存通知路由</button></div>
      </div>
      <div class="mt-4 overflow-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full min-w-[920px] text-left text-sm">
          <thead class="bg-slate-50 text-slate-600">
            <tr>
              <th class="p-4">通知场景</th>
              <th class="p-4 text-center">SMTP → 获奖人</th>
              <th class="p-4 text-center">SMTP → 运营邮箱</th>
              <th class="p-4 text-center">email-poster → 获奖人</th>
              <th class="p-4 text-center">email-poster → 运营邮箱</th>
              <th class="p-4 text-center">Webhook</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="route in routing" :key="route.event_type" class="border-t border-slate-200">
              <th class="p-4 font-medium">{{ eventLabels[route.event_type] }}</th>
              <td class="p-4 text-center"><input v-model="route.smtp_winner" class="h-4 w-4 accent-blue-600" type="checkbox" :aria-label="`${eventLabels[route.event_type]} SMTP 发给获奖人`" /></td>
              <td class="p-4 text-center"><input v-model="route.smtp_operations" class="h-4 w-4 accent-blue-600" type="checkbox" :aria-label="`${eventLabels[route.event_type]} SMTP 发给运营邮箱`" /></td>
              <td class="p-4 text-center"><input v-model="route.email_poster_winner" class="h-4 w-4 accent-blue-600" type="checkbox" :aria-label="`${eventLabels[route.event_type]} email-poster 发给获奖人`" /></td>
              <td class="p-4 text-center"><input v-model="route.email_poster_operations" class="h-4 w-4 accent-blue-600" type="checkbox" :aria-label="`${eventLabels[route.event_type]} email-poster 发给运营邮箱`" /></td>
              <td class="p-4 text-center"><input v-model="route.webhook" class="h-4 w-4 accent-blue-600" type="checkbox" :aria-label="`${eventLabels[route.event_type]} 发送 Webhook`" /></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="mt-3 text-xs leading-5 text-slate-500">“运营邮箱”来自 <code>NOTIFICATION_EMAIL</code>；Webhook 发送到 <code>WEBHOOK_URL</code>。未配置的环境目标会导致对应任务发送失败。</p>
    </section>

    <section class="mt-8">
      <div class="flex items-center justify-between gap-3"><h2 class="text-xl font-bold">通知模板</h2><button class="btn-secondary" type="button" :disabled="busy" @click="refreshForm">刷新表单</button></div>
      <p class="mt-2 text-sm text-slate-500">纯文本正文始终保留；HTML 留空时邮件自动退回纯文本。</p>
      <div class="mt-4 grid gap-4">
        <article v-for="template in templates" :key="template.event_type" class="card">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="font-semibold">{{ eventLabels[template.event_type] }}</h3>
            <button class="btn-primary" :disabled="busy" @click="saveTemplate(template)">保存模板</button>
          </div>
          <label class="mt-4 block text-sm font-medium text-slate-700">纯文本正文</label>
          <textarea v-model="template.text_template" class="field mt-2 min-h-28 font-mono text-sm" maxlength="20000" />
          <div class="mt-4 flex items-center justify-between gap-3">
            <label class="block text-sm font-medium text-slate-700">HTML 正文（可选）</label>
            <button class="btn-secondary px-3 py-1.5 text-sm" type="button" :disabled="!template.html_template?.trim()" @click="openHtmlPreview(template)">预览 HTML</button>
          </div>
          <textarea v-model="template.html_template" class="field mt-2 min-h-52 font-mono text-sm" maxlength="50000" placeholder="留空则仅发送纯文本正文" />
          <p class="mt-3 text-xs leading-6 text-slate-500">
            可用变量：<code v-for="variable in template.allowed_variables" :key="variable" class="mr-2 rounded bg-slate-100 px-1.5 py-1">{{ variableLabel(variable) }}</code>
          </p>
        </article>
      </div>
    </section>

    <section class="mt-8">
      <div class="flex items-center justify-between gap-3"><h2 class="text-xl font-bold">最近通知任务</h2><button class="btn-secondary" type="button" :disabled="busy" @click="refreshForm">刷新状态</button></div>
      <div class="mt-4 overflow-auto rounded-xl border border-slate-200 bg-white">
        <table class="w-full min-w-[900px] text-left text-sm">
          <thead class="bg-slate-50">
            <tr>
              <th class="p-4">事件</th>
              <th class="p-4">渠道</th>
              <th class="p-4">目标</th>
              <th class="p-4">状态</th>
              <th class="p-4">尝试</th>
              <th class="p-4">失败原因</th>
              <th class="p-4">创建时间</th>
              <th class="p-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id" class="border-t">
              <td class="p-4">{{ eventLabels[job.event_type] }}</td>
              <td class="p-4">{{ job.channel }}</td>
              <td class="p-4">{{ job.destination }}</td>
              <td class="p-4">{{ job.status }}</td>
              <td class="p-4">{{ job.attempt_count }}</td>
              <td class="max-w-xs truncate p-4 text-red-600" :title="job.last_error ?? ''">{{ job.last_error || '—' }}</td>
              <td class="p-4">{{ new Date(job.created_at).toLocaleString() }}</td>
              <td class="p-4"><button v-if="job.status === 'failed'" class="text-blue-600" :disabled="busy" @click="retry(job)">重试</button></td>
            </tr>
            <tr v-if="jobs.length === 0">
              <td colspan="8" class="p-10 text-center text-slate-500">暂无通知任务</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="preview" class="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4" role="presentation" @click.self="closePreview">
        <section class="flex h-[min(90vh,900px)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" role="dialog" aria-modal="true" :aria-label="`${preview.title} HTML 预览`">
          <header class="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <h2 class="font-semibold">{{ preview.title }} · HTML 预览</h2>
              <p class="mt-1 text-xs text-slate-500">当前未保存内容，模板变量已替换为示例数据。</p>
            </div>
            <button class="btn-secondary px-3 py-1.5 text-sm" type="button" :autofocus="true" @click="closePreview">关闭</button>
          </header>
          <iframe class="min-h-0 flex-1 bg-white" :srcdoc="preview.html" :sandbox="''" title="HTML 邮件模板预览"></iframe>
        </section>
      </div>
    </Teleport>
  </main>
</template>
