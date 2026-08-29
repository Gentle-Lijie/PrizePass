<script setup lang="ts">
import type { Html5Qrcode } from 'html5-qrcode'
import { push } from 'notivue'
import SignaturePad from 'signature_pad'
import { inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api, ApiError } from '@/api/client'
import type { AdminRedemption, ClaimLookup } from '@/api/types'
import { eventTabContextKey } from '@/components/event/eventContext'

const context = inject(eventTabContextKey)!
const { refresh } = context

type Stage = 'scan' | 'info' | 'sign' | 'done'
const READER_ID = 'claim-reader'
// Signature PNGs are stored trimmed to this pixel height so each one stays a few KB.
const SIGNATURE_HEIGHT = 120

const stage = ref<Stage>('scan')
const manualCode = ref('')
const lookup = ref<ClaimLookup | null>(null)
const lookupCode = ref('')
const submitting = ref(false)
const cameraStarting = ref(false)
const cameraError = ref('')
// Enumerated cameras (label + deviceId); -1 means "not picked yet".
const cameras = ref<Array<{ id: string; label: string }>>([])
const cameraIndex = ref(-1)

let scanner: Html5Qrcode | null = null
let pad: SignaturePad | null = null

function showError(caught: unknown, fallback: string) {
  const message = caught instanceof Error ? caught.message : fallback
  push.error(message)
}

// Scanned text may be a bare code or a /redeem?code=... URL; both should work.
function extractCode(text: string): string | null {
  const trimmed = text.trim()
  try {
    const code = new URL(trimmed).searchParams.get('code')
    if (code) return code.trim().toUpperCase()
  } catch {
    // Not a URL — fall through and treat as a bare code.
  }
  return /^[A-Za-z0-9]{8,32}$/.test(trimmed) ? trimmed.toUpperCase() : null
}

async function startCamera() {
  if (scanner || cameraStarting.value) return
  cameraStarting.value = true
  cameraError.value = ''
  try {
    // zxing inside html5-qrcode is heavy; load it only when scanning starts.
    const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import('html5-qrcode')
    if (cameras.value.length === 0) {
      // getCameras() prompts for permission on some browsers; the scan start
      // below would prompt anyway, so failing here is not an error.
      try {
        cameras.value = (await Html5Qrcode.getCameras()) ?? []
      } catch {
        cameras.value = []
      }
    }
    // Prefer a rear camera by label; fall back to the first device, and to
    // facingMode when enumeration is unavailable (e.g. strict privacy modes).
    let camera: string | { facingMode: string } = { facingMode: 'environment' }
    if (cameras.value.length > 0) {
      if (cameraIndex.value < 0) {
        const rear = cameras.value.findIndex((item) => /back|rear|environment|后置|后摄/i.test(item.label))
        cameraIndex.value = rear >= 0 ? rear : 0
      }
      camera = cameras.value[cameraIndex.value]?.id ?? { facingMode: 'environment' }
    }
    const instance = new Html5Qrcode(READER_ID, {
      formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE],
      verbose: false,
    })
    await instance.start(
      camera,
      { fps: 10, qrbox: { width: 240, height: 240 } },
      async (decoded) => {
        const code = extractCode(decoded)
        if (!code) return
        await stopCamera()
        await runLookup(code)
      },
      () => {
        // Per-frame decode misses are normal; ignore.
      },
    )
    scanner = instance
  } catch (caught) {
    cameraError.value =
      '摄像头不可用（需要 HTTPS 或 localhost 授权），请使用下方手动输入兑换码。'
    if (caught instanceof Error && /permission|denied/i.test(caught.message)) {
      cameraError.value = '摄像头权限被拒绝，请在浏览器设置中允许后重试，或手动输入兑换码。'
    }
  } finally {
    cameraStarting.value = false
  }
}

async function stopCamera() {
  if (!scanner) return
  const instance = scanner
  scanner = null
  try {
    await instance.stop()
    instance.clear()
  } catch {
    // Camera already gone (tab switched / browser teardown).
  }
}

async function switchCamera() {
  if (cameras.value.length < 2 || cameraStarting.value) return
  await stopCamera()
  cameraIndex.value = (cameraIndex.value + 1) % cameras.value.length
  await startCamera()
}

function cameraLabel(index: number) {
  const label = cameras.value[index]?.label ?? ''
  return label ? `（${label.slice(0, 12)}）` : ''
}

async function runLookup(code: string) {
  try {
    lookup.value = await api<ClaimLookup>(`/api/admin/claims/lookup?code=${encodeURIComponent(code)}`)
    lookupCode.value = code.trim().toUpperCase()
    stage.value = 'info'
  } catch (caught) {
    showError(caught, '查询失败')
    if (stage.value === 'scan') await startCamera()
  }
}

async function submitManualCode() {
  const code = extractCode(manualCode.value)
  if (!code) {
    push.error('请输入有效的兑换码')
    return
  }
  await runLookup(code)
}

function backToScan() {
  stage.value = 'scan'
  lookup.value = null
  manualCode.value = ''
  void nextTick(() => startCamera())
}

async function beginSigning() {
  stage.value = 'sign'
  await nextTick()
  const canvas = document.querySelector<HTMLCanvasElement>('#claim-signature')
  if (!canvas) return
  setupCanvas(canvas)
  pad = new SignaturePad(canvas, {
    minWidth: 1,
    maxWidth: 3,
    penColor: '#172033',
    backgroundColor: 'rgba(0,0,0,0)',
  })
}

// Match the canvas backing store to its CSS size so strokes are not blurry.
function setupCanvas(canvas: HTMLCanvasElement) {
  const ratio = Math.max(1, window.devicePixelRatio || 1)
  const width = canvas.offsetWidth
  const height = canvas.offsetHeight
  canvas.width = width * ratio
  canvas.height = height * ratio
  const ctx = canvas.getContext('2d')
  ctx?.scale(ratio, ratio)
}

// Crop the drawing to its bounding box and scale down to SIGNATURE_HEIGHT,
// keeping the stored PNG at a few KB.
function trimmedSignature(): Promise<string> {
  const source = document.createElement('canvas')
  const target = document.createElement('canvas')
  return new Promise((resolve, reject) => {
    if (!pad || pad.isEmpty()) {
      reject(new Error('请先签名'))
      return
    }
    const image = new Image()
    image.onload = () => {
      source.width = image.width
      source.height = image.height
      const ctx = source.getContext('2d')
      if (!ctx) {
        reject(new Error('无法读取签名'))
        return
      }
      ctx.drawImage(image, 0, 0)
      const { data } = ctx.getImageData(0, 0, source.width, source.height)
      let minX = source.width
      let minY = source.height
      let maxX = -1
      let maxY = -1
      for (let y = 0; y < source.height; y += 1) {
        for (let x = 0; x < source.width; x += 1) {
          if ((data[(y * source.width + x) * 4 + 3] ?? 0) > 0) {
            if (x < minX) minX = x
            if (x > maxX) maxX = x
            if (y < minY) minY = y
            if (y > maxY) maxY = y
          }
        }
      }
      if (maxX < 0) {
        reject(new Error('签名为空'))
        return
      }
      const padding = 8
      minX = Math.max(0, minX - padding)
      minY = Math.max(0, minY - padding)
      maxX = Math.min(source.width - 1, maxX + padding)
      maxY = Math.min(source.height - 1, maxY + padding)
      const boxWidth = maxX - minX + 1
      const boxHeight = maxY - minY + 1
      const scale = SIGNATURE_HEIGHT / boxHeight
      target.width = Math.max(1, Math.round(boxWidth * scale))
      target.height = SIGNATURE_HEIGHT
      const out = target.getContext('2d')
      if (!out) {
        reject(new Error('无法生成签名图片'))
        return
      }
      out.imageSmoothingEnabled = true
      out.imageSmoothingQuality = 'high'
      out.drawImage(source, minX, minY, boxWidth, boxHeight, 0, 0, target.width, target.height)
      resolve(target.toDataURL('image/png'))
    }
    image.onerror = () => reject(new Error('无法生成签名图片'))
    image.src = pad.toDataURL('image/png')
  })
}

function clearSignature() {
  pad?.clear()
}

async function confirmSignature() {
  let signature: string
  try {
    signature = await trimmedSignature()
  } catch (caught) {
    showError(caught, '签名无效')
    return
  }
  submitting.value = true
  try {
    await api<AdminRedemption>('/api/admin/claims/pickup', {
      method: 'POST',
      body: JSON.stringify({ code: lookupCode.value, signature }),
    })
    push.success(`已确认领奖：${lookup.value?.winner.name ?? ''}`)
    stage.value = 'done'
    pad = null
    await refresh()
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 409) {
      push.error(caught.message)
      backToScan()
    } else {
      showError(caught, '提交失败')
    }
  } finally {
    submitting.value = false
  }
}

watch(stage, (value) => {
  if (value !== 'sign') pad = null
})

onMounted(() => {
  void startCamera()
})

onBeforeUnmount(() => {
  void stopCamera()
  pad = null
})

function redemptionStatusLabel(status: AdminRedemption['status']) {
  return { submitted: '待备货', procuring: '待备货', ready: '待领取', picked_up: '已领取', cancelled: '已取消' }[status]
}
</script>

<template>
  <section class="mt-6 space-y-6">
    <!-- 扫码 / 手动输入 -->
    <div v-if="stage === 'scan'" class="card space-y-5">
      <div>
        <h2 class="text-lg font-semibold">扫码领奖</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          扫描获奖人邮件中的二维码，或手动输入兑换码。
        </p>
      </div>
      <div
        :id="READER_ID"
        class="mx-auto min-h-64 w-full max-w-md overflow-hidden rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800"
      />
      <p v-if="cameraStarting" class="text-center text-sm text-slate-500 dark:text-slate-400">
        正在启动摄像头…
      </p>
      <p v-else-if="cameraError" class="text-center text-sm text-amber-600 dark:text-amber-400">
        {{ cameraError }}
      </p>
      <button v-if="cameraError" class="btn-secondary mx-auto block" type="button" @click="startCamera">
        重试摄像头
      </button>
      <button
        v-if="cameras.length > 1"
        class="btn-secondary mx-auto block"
        type="button"
        :disabled="cameraStarting"
        @click="switchCamera"
      >
        切换摄像头{{ cameraLabel(cameraIndex) }}
      </button>
      <form class="flex max-w-md gap-2 mx-auto" @submit.prevent="submitManualCode">
        <input
          v-model="manualCode"
          class="field flex-1 font-mono uppercase"
          placeholder="手动输入兑换码"
          autocomplete="off"
          spellcheck="false"
        />
        <button class="btn-primary" type="submit">查询</button>
      </form>
    </div>

    <!-- 获奖人信息 -->
    <div v-else-if="stage === 'info' && lookup" class="card space-y-5">
      <div class="flex items-start justify-between gap-4">
        <div>
          <p class="text-sm text-slate-500 dark:text-slate-400">{{ lookup.winner.email }}</p>
          <h2 class="mt-1 text-3xl font-bold">{{ lookup.winner.name }}</h2>
          <p v-if="lookup.winner.award_name" class="mt-1 text-lg text-blue-600 dark:text-blue-400">
            {{ lookup.winner.award_name }}
          </p>
        </div>
        <span
          class="rounded-full px-3 py-1 text-xs"
          :class="
            lookup.claimable
              ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300'
          "
        >
          {{ lookup.claimable ? '可领奖' : lookup.reason ?? '不可领奖' }}
        </span>
      </div>

      <div v-if="lookup.redemption" class="space-y-1 text-sm">
        <p>
          兑换单号：<span class="font-mono">{{ lookup.redemption.order_no }}</span
          >（{{ redemptionStatusLabel(lookup.redemption.status) }}）
        </p>
        <p>奖品：{{ lookup.redemption.items_summary || '—' }}</p>
        <p>总抵扣：{{ lookup.redemption.total_redeem_value }}</p>
        <p v-if="lookup.redemption.picked_up_at">
          领取时间：{{ new Date(lookup.redemption.picked_up_at).toLocaleString() }}
        </p>
        <img
          v-if="lookup.redemption.signature"
          :src="lookup.redemption.signature"
          alt="领奖签名"
          class="mt-3 h-20 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-700"
        />
      </div>
      <p v-else class="text-sm text-slate-500 dark:text-slate-400">该获奖人尚未提交兑换单。</p>

      <div class="flex gap-2">
        <button class="btn-secondary" type="button" @click="backToScan">返回</button>
        <button
          v-if="lookup.claimable"
          class="btn-primary ml-auto"
          type="button"
          @click="beginSigning"
        >
          开始签字
        </button>
      </div>
    </div>

    <!-- 签字 -->
    <div v-else-if="stage === 'sign'" class="card space-y-5">
      <div>
        <h2 class="text-lg font-semibold">请 {{ lookup?.winner.name }} 签字确认领奖</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          奖品：{{ lookup?.redemption?.items_summary || '—' }}
        </p>
      </div>
      <canvas
        id="claim-signature"
        class="h-64 w-full touch-none rounded-xl border-2 border-dashed border-slate-300 bg-white dark:border-slate-600"
      />
      <div class="flex gap-2">
        <button class="btn-secondary" type="button" @click="backToScan">取消</button>
        <button class="btn-secondary ml-auto" type="button" @click="clearSignature">清除重写</button>
        <button class="btn-primary" type="button" :disabled="submitting" @click="confirmSignature">
          {{ submitting ? '提交中…' : '确认领奖' }}
        </button>
      </div>
    </div>

    <!-- 完成 -->
    <div v-else class="card text-center">
      <p class="text-2xl font-bold text-green-600 dark:text-green-400">✓ 领奖完成</p>
      <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
        {{ lookup?.winner.name }} 的签名已保存，兑换单已标记为已领取。
      </p>
      <button class="btn-primary mt-5" type="button" @click="backToScan">继续下一位</button>
    </div>
  </section>
</template>
