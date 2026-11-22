import type { ReactNode } from 'react'

export type BadgeTone = 'neutral' | 'warning' | 'danger' | 'success' | 'accent' | 'local'

export type Risk = 'read' | 'reversible_write' | 'irreversible'

export function Badge({ tone = 'neutral', children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}

const RISK: Record<Risk, { tone: BadgeTone; label: string }> = {
  read: { tone: 'neutral', label: '조회' },
  reversible_write: { tone: 'warning', label: '실행 취소 가능' },
  irreversible: { tone: 'danger', label: '실행 취소 불가' },
}

export function RiskBadge({ risk }: { risk: Risk }) {
  const { tone, label } = RISK[risk]
  return <Badge tone={tone}>{label}</Badge>
}

export function LocalBadge() {
  return <Badge tone="local">사내 처리</Badge>
}
