import { createRouter, createWebHistory } from 'vue-router'

import LandingView from '@/views/LandingView.vue'
import AdminLoginView from '@/views/AdminLoginView.vue'
import EventsView from '@/views/EventsView.vue'
import EventDetailView from '@/views/EventDetailView.vue'
import PrizesView from '@/views/PrizesView.vue'
import PurchasesView from '@/views/PurchasesView.vue'
import NotificationSettingsView from '@/views/NotificationSettingsView.vue'
import RedeemCodeView from '@/views/RedeemCodeView.vue'
import RedeemPrizesView from '@/views/RedeemPrizesView.vue'
import RedeemConfirmView from '@/views/RedeemConfirmView.vue'
import RedeemSuccessView from '@/views/RedeemSuccessView.vue'

export default createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.path === '/redeem/confirm' || to.path === '/redeem/success') return { top: 0, left: 0 }
    return { top: 0, left: 0 }
  },
  routes: [
    { path: '/', component: LandingView },
    { path: '/admin', component: AdminLoginView },
    { path: '/admin/events', component: EventsView },
    { path: '/admin/events/:id', component: EventDetailView },
    { path: '/admin/prizes', component: PrizesView },
    { path: '/admin/purchases', component: PurchasesView },
    {
      path: '/admin/settings/notifications',
      component: NotificationSettingsView,
    },
    { path: '/redeem', component: RedeemCodeView },
    { path: '/redeem/prizes', component: RedeemPrizesView },
    { path: '/redeem/confirm', component: RedeemConfirmView },
    { path: '/redeem/success', component: RedeemSuccessView },
  ],
})
