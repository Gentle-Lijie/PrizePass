import { defineStore } from 'pinia'
import { ref } from 'vue'

import type {
  PublicPrize,
  RedemptionContext,
  RedemptionSuccess,
} from '@/api/types'

export const useRedemptionStore = defineStore('redemption', () => {
  const context = ref<RedemptionContext | null>(null)
  const prizes = ref<PublicPrize[]>([])
  const quantities = ref<Record<number, number>>({})
  const success = ref<RedemptionSuccess | null>(null)

  function resetSelection() {
    context.value = null
    prizes.value = []
    quantities.value = {}
    success.value = null
  }

  return { context, prizes, quantities, success, resetSelection }
})
