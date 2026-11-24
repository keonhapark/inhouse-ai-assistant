import type { Schemas } from '../api/client'
import { formatWhen } from './format'
import { agentLabel } from './names'

type Summary = Schemas['ConversationSummary']

export type StatusTone = 'orange' | 'green' | 'gray' | 'red' | 'blue'

export type ConversationRow = {
  /** 담당 AI. 라우팅 전이면 "담당 AI 정하는 중" */
  agent: string
  /** 상태 점과 이름. 진행 중이면 표시하지 않습니다 */
  status: { label: string; tone: StatusTone } | null
  /** 마지막으로 바뀐 시각(없으면 만든 시각). 오늘 오후 12:41 · 어제 오전 9:05 · 2026. 11. 20. */
  when: string
}

/**
 * 대화 목록 한 줄(ux/design-system.md 3.8): 제목 + 시각, 둘째 줄에 담당 AI + 상태 점(#556).
 * 같은 말로 시작한 대화가 여럿이어도 언제·어떤 상태인지로 구별되게 합니다.
 */
export function conversationRow(c: Summary, now = new Date()): ConversationRow {
  return {
    agent: c.agentName ? agentLabel(c.agentName) : '담당 AI 정하는 중',
    status:
      c.status === 'awaiting_approval'
        ? { label: '확인 필요', tone: 'orange' }
        : c.status === 'closed'
          ? { label: '종료', tone: 'gray' }
          : null,
    when: formatWhen(c.updatedAt ?? c.createdAt, now),
  }
}
