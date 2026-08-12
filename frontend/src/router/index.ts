import { createRouter, createWebHistory } from 'vue-router'

import AdminLoginView from '@/views/AdminLoginView.vue'
import EventsView from '@/views/EventsView.vue'
import EventDetailView from '@/views/EventDetailView.vue'
import NotificationSettingsView from '@/views/NotificationSettingsView.vue'
import RedeemCodeView from '@/views/RedeemCodeView.vue'
import RedeemPrizesView from '@/views/RedeemPrizesView.vue'
import RedeemConfirmView from '@/views/RedeemConfirmView.vue'
import RedeemSuccessView from '@/views/RedeemSuccessView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/redeem' },
    { path: '/admin', component: AdminLoginView },
    { path: '/admin/events', component: EventsView },
    { path: '/admin/events/:id', component: EventDetailView },
    { path: '/admin/settings/notifications', component: NotificationSettingsView },
    { path: '/redeem', component: RedeemCodeView },
    { path: '/redeem/prizes', component: RedeemPrizesView },
    { path: '/redeem/confirm', component: RedeemConfirmView },
    { path: '/redeem/success', component: RedeemSuccessView },
  ],
})
