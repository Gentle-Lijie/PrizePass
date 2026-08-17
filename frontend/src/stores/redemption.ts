import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { PublicPrize, RedemptionContext, RedemptionSuccess } from '@/api/types'

export interface CustomPrize {
  name: string
  url: string
  note: string
  priceYuan: string
}

export const useRedemptionStore = defineStore('redemption', () => {
  const context = ref<RedemptionContext | null>(null)
  const prizes = ref<PublicPrize[]>([])
  const quantities = ref<Record<number, number>>({})
  // When set, the winner redeems one custom described prize instead of catalog items.
  const customPrize = ref<CustomPrize | null>(null)
  const success = ref<RedemptionSuccess | null>(null)

  function resetSelection() {
    context.value = null
    prizes.value = []
    quantities.value = {}
    customPrize.value = null
    success.value = null
  }

  return {
    context,
    prizes,
    quantities,
    customPrize,
    success,
    resetSelection,
  }
})
