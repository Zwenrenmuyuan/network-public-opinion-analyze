export function formatLargeNumber(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  const v = Number(n)
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + ' 亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + ' 万'
  return v.toLocaleString('zh-CN')
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  return (Number(n) * 100).toFixed(digits) + '%'
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[1]} / ${m[2]} / ${m[3]}` : String(iso)
}
