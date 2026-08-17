// 生成带标识信息与时间戳的导出文件名：{scope}-{...info}-yyyymmdd-hhmm.{ext}
export function exportFilename(scope: string, ext: string, ...info: (string | number | undefined)[]): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
  const segments = [scope, ...info.map((piece) => (piece === undefined ? '' : String(piece))), stamp]
    .map((s) => s.replace(/[\\/:*?"<>|\s]+/g, '-').replace(/^-+|-+$/g, ''))
    .filter(Boolean)
  return `${segments.join('-')}.${ext}`
}
