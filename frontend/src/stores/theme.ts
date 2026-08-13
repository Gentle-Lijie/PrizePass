import { defineStore } from 'pinia'
import { ref } from 'vue'

type Theme = 'light' | 'dark'
type ThemePreference = Theme | 'system'

const STORAGE_KEY = 'prizepass-theme'

function readThemePreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system'

  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

function readSystemTheme(): Theme {
  return typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

function resolveTheme(preference: ThemePreference): Theme {
  return preference === 'system' ? readSystemTheme() : preference
}

export function readInitialTheme(): Theme {
  return resolveTheme(readThemePreference())
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export const useThemeStore = defineStore('theme', () => {
  const preference = ref<ThemePreference>(readThemePreference())
  const theme = ref<Theme>(resolveTheme(preference.value))
  applyTheme(theme.value)

  const systemThemeMedia =
    typeof window === 'undefined'
      ? null
      : window.matchMedia('(prefers-color-scheme: dark)')

  function handleSystemThemeChange() {
    if (preference.value !== 'system') return

    theme.value = resolveTheme('system')
    applyTheme(theme.value)
  }

  systemThemeMedia?.addEventListener('change', handleSystemThemeChange)

  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    preference.value = theme.value
    localStorage.setItem(STORAGE_KEY, preference.value)
    applyTheme(theme.value)
  }

  function useSystemTheme() {
    preference.value = 'system'
    localStorage.removeItem(STORAGE_KEY)
    theme.value = resolveTheme('system')
    applyTheme(theme.value)
  }

  return { theme, preference, toggle, useSystemTheme }
})
