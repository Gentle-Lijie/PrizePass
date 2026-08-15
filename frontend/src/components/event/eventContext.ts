import type { InjectionKey, Ref } from 'vue'

import type {
  AdminRedemption,
  EventRecord,
  PrizeRecord,
  PrizeSummary,
  WinnerRecord,
} from '@/api/types'

// Shared state provided by EventDetailView to its tab components.
// Every write action in a tab still funnels through load() so all lists stay
// in sync, and error/notice/busy remain a single global set.
export interface EventTabContext {
  eventId: number
  event: Ref<EventRecord | null>
  prizes: Ref<PrizeRecord[]>
  prizeSummary: Ref<PrizeSummary>
  winners: Ref<WinnerRecord[]>
  redemptions: Ref<AdminRedemption[]>
  error: Ref<string>
  notice: Ref<string>
  busy: Ref<boolean>
  load: () => Promise<void>
  // load() plus refreshHooks (e.g. re-open an open redemption detail).
  refresh: () => Promise<void>
  // Run after refresh reloads everything.
  refreshHooks: Set<() => void>
}

export const eventTabContextKey: InjectionKey<EventTabContext> =
  Symbol('eventTabContext')
