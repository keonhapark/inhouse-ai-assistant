import type { Schemas } from '../api/client'
import type { BadgeTone } from '../components/Badge'

type Label = { label: string; tone: BadgeTone }

export const DOC_STATUS: Record<Schemas['ApprovalStatus'], Label> = {
  in_progress: { label: '진행', tone: 'accent' },
  approved: { label: '승인', tone: 'success' },
  rejected: { label: '반려', tone: 'danger' },
  withdrawn: { label: '회수', tone: 'neutral' },
}

export const STEP_STATUS: Record<Schemas['ApprovalStep']['status'], Label> = {
  waiting: { label: '대기', tone: 'neutral' },
  pending: { label: '결재 차례', tone: 'accent' },
  approved: { label: '승인', tone: 'success' },
  rejected: { label: '반려', tone: 'danger' },
  skipped: { label: '건너뜀', tone: 'neutral' },
}

export const DELEGATION_STATUS: Record<Schemas['Delegation']['status'], Label> = {
  scheduled: { label: '예정', tone: 'neutral' },
  active: { label: '대결 중', tone: 'success' },
  expired: { label: '종료', tone: 'neutral' },
  revoked: { label: '해제', tone: 'neutral' },
}

export const BOXES = [
  { box: 'inbox', label: '내 차례' },
  { box: 'delegated', label: '대결' },
  { box: 'done', label: '처리함' },
  { box: 'outbox', label: '올린 것' },
] as const

export type Box = (typeof BOXES)[number]['box']

const dt = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
const dty = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
/** 올해면 연도를 빼고, 다른 해면 연도까지 보여 줍니다. */
export const formatDateTime = (iso: string, now = new Date()) => {
  const d = new Date(iso)
  return (d.getFullYear() === now.getFullYear() ? dt : dty).format(d)
}
export const formatAmount = (n: number | null | undefined) => (n == null ? '–' : `${n.toLocaleString('ko-KR')}원`)
