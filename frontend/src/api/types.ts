export type EventStatus = 'draft' | 'active' | 'closed'

export interface EventRecord {
  id: number
  name: string
  description: string | null
  status: EventStatus
  redemption_deadline: string
  pickup_location: string
  pickup_instructions: string
  budget: number
  winner_count: number
  redemption_count: number
  created_at: string
  updated_at: string
}

export interface EventWrite {
  name: string
  description: string | null
  status: EventStatus
  redemption_deadline: string
  pickup_location: string
  pickup_instructions: string
  budget: number
}

export interface PrizeRecord {
  id: number
  event_id: number
  name: string
  image: string
  jd_url: string | null
  real_value: number
  purchase_value: number
  redeem_value: number
  stock: number
  description: string | null
  tag: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PrizeWrite {
  name: string
  image: string
  jd_url: string | null
  real_value: number
  purchase_value: number
  redeem_value: number
  stock: number
  description: string | null
  tag: string | null
  is_active: boolean
}

export interface PrizeBatchIds {
  ids: number[]
}

export interface PrizeBatchTag extends PrizeBatchIds {
  tag: string | null
}

export interface PrizeBatchStock extends PrizeBatchIds {
  mode: 'delta' | 'set'
  value: number
}

export interface PrizeBatchDeleteResult {
  deleted: number
  skipped: Array<{ id: number; name: string }>
}

export interface ImportError {
  row: number
  field: string
  message: string
}

export interface PrizeImportPreview {
  valid: boolean
  rows: Array<Record<string, string | number>>
  errors: ImportError[]
  count?: number
}

export interface WinnerRecord {
  id: number
  external_id: string | null
  name: string
  email: string
  quota: number
  code: string
  code_status: 'issued' | 'redeemed' | 'disabled'
  email_notification_status: string
  webhook_notification_status: string
  created_at: string
}

export interface WinnerCreate {
  external_id: string | null
  name: string
  email: string
  quota: number
}

export type NotificationChannel = 'email' | 'webhook' | 'email_poster'

export interface PrizeSummary {
  total_purchase_value: number
  claimed_purchase_value: number
  budget: number
}

export interface WinnerImportPreview {
  valid: boolean
  rows: Array<Record<string, string | number | null>>
  errors: ImportError[]
  count: number
  quota_total: number
}

export interface RedemptionContext {
  event: {
    id: number
    name: string
    description: string | null
    redemption_deadline: string
    pickup_location: string
    pickup_instructions: string
  }
  winner: { name: string; email: string }
  quota: number
}

export interface PublicPrize {
  id: number
  name: string
  image: string
  jd_url: string | null
  purchase_value: number
  redeem_value: number
  description: string | null
  tag: string | null
}

export interface RedemptionSuccess {
  id: number
  order_no: string
  status: 'submitted'
  total_redeem_value: number
  unused_quota: number
  pickup_location: string
  pickup_instructions: string
}

export type AdminRedemptionStatus =
  'submitted' | 'ready' | 'picked_up' | 'cancelled'

export interface AdminRedemption {
  id: number
  order_no: string
  status: AdminRedemptionStatus
  winner_name: string
  winner_email: string
  contact_name: string
  contact_phone: string
  note: string | null
  items_summary: string
  total_redeem_value: number
  quota: number
  unused_quota: number
  pickup_location: string
  pickup_instructions: string
  created_at: string
  picked_up_at: string | null
  cancelled_at: string | null
  items?: Array<{
    id: number
    prize_id: number
    prize_name: string
    prize_image: string
    real_value: number
    purchase_value: number
    redeem_value: number
    quantity: number
    line_redeem_value: number
  }>
}

export interface NotificationTemplateRecord {
  event_type: string
  text_template: string
  html_template: string | null
  allowed_variables: string[]
  updated_at: string
}

export interface NotificationRoutingRecord {
  event_type: string
  smtp_winner: boolean
  smtp_operations: boolean
  email_poster_winner: boolean
  email_poster_operations: boolean
  webhook: boolean
}

export interface NotificationJobRecord {
  id: number
  event_type: string
  channel: 'email' | 'webhook' | 'email_poster'
  destination: string
  text_rendered: string
  html_rendered: string | null
  status: 'pending' | 'sending' | 'retrying' | 'sent' | 'failed'
  attempt_count: number
  next_attempt_at: string | null
  last_error: string | null
  sent_at: string | null
  created_at: string
}
