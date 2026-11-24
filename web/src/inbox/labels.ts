import type { Schemas } from '../api/client'
import type { BadgeTone } from '../components/Badge'

type Label = { label: string; tone: BadgeTone }

/** 상태 이름의 색 → 상태 점 클래스(.status--*, ux/design-system.md 3.3) */
export const TONE_DOT = { accent: 'progress', success: 'green', danger: 'red', neutral: 'gray', warning: 'orange', local: 'blue' } as const satisfies Record<BadgeTone, string>

export const DOC_STATUS: Record<Schemas['ApprovalStatus'], Label> = {
  in_progress: { label: '진행 중', tone: 'accent' },
  approved: { label: '승인', tone: 'success' },
  rejected: { label: '반려', tone: 'danger' },
  withdrawn: { label: '회수', tone: 'neutral' },
}

export const STEP_STATUS: Record<Schemas['ApprovalStep']['status'], Label> = {
  waiting: { label: '대기', tone: 'neutral' },
  pending: { label: '결재 대기', tone: 'accent' },
  approved: { label: '승인', tone: 'success' },
  rejected: { label: '반려', tone: 'danger' },
  skipped: { label: '생략', tone: 'neutral' },
}

export const DELEGATION_STATUS: Record<Schemas['Delegation']['status'], Label> = {
  scheduled: { label: '예정', tone: 'neutral' },
  active: { label: '대결 중', tone: 'success' },
  expired: { label: '종료', tone: 'neutral' },
  revoked: { label: '해제', tone: 'neutral' },
}

export const BOXES = [
  { box: 'inbox', label: '결재 대기' },
  { box: 'delegated', label: '대결 대기' },
  { box: 'done', label: '결재 완료' },
  { box: 'outbox', label: '기안함' },
] as const

export type Box = (typeof BOXES)[number]['box']
