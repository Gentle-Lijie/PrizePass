import type { EventStatus } from '@/api/types'

export function statusLabel(status: EventStatus) {
  return { draft: '草稿', active: '进行中', closed: '已关闭' }[status]
}
