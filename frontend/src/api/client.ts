import { useAuthStore } from '@/stores/auth'

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore()
  const headers = new Headers(init.headers)
  if (path.startsWith('/api/admin/')) headers.set('X-Admin-Password', auth.adminPassword)
  if (path.startsWith('/api/public/')) headers.set('X-Redemption-Code', auth.redemptionCode)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const body = (await response.json()) as ApiErrorBody
    throw new ApiError(response.status, body.error.code, body.error.message, body.error.details)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function downloadAdmin(path: string, filename: string): Promise<void> {
  const auth = useAuthStore()
  const response = await fetch(path, { headers: { 'X-Admin-Password': auth.adminPassword } })
  if (!response.ok) {
    const body = (await response.json()) as ApiErrorBody
    throw new ApiError(response.status, body.error.code, body.error.message, body.error.details)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
