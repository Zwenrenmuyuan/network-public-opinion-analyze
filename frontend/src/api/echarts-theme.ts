import type { EmotionLabel } from '@/types/api'

export const EMOTION_COLORS: Record<EmotionLabel, string> = {
  '积极': '#4ade80',
  '愤怒': '#ff4d52',
  '悲伤': '#4b8aff',
  '恐惧': '#a78bfa',
  '惊讶': '#ffa028',
  '中性': '#94a3b8',
}

export const EMOTION_ORDER: EmotionLabel[] = ['积极', '愤怒', '悲伤', '恐惧', '惊讶', '中性']

export const baseDark = {
  backgroundColor: 'transparent',
  textStyle: { color: '#d1d5db', fontFamily: 'Noto Sans SC, sans-serif' },
  tooltip: {
    backgroundColor: '#0d1117',
    borderColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    textStyle: { color: '#f3f4f6', fontFamily: 'Noto Sans SC, sans-serif', fontSize: 12 },
    extraCssText: 'border-radius: 4px; box-shadow: 0 12px 32px rgba(0,0,0,0.4);',
  },
}
