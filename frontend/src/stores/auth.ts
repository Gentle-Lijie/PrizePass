import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const adminPassword = ref('')
  const redemptionCode = ref('')

  function clearAdminPassword() {
    adminPassword.value = ''
  }

  function clearRedemptionCode() {
    redemptionCode.value = ''
  }

  return {
    adminPassword,
    redemptionCode,
    clearAdminPassword,
    clearRedemptionCode,
  }
})
