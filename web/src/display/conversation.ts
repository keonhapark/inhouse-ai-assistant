import type { Schemas } from '../api/client'
import { formatWhen } from './format'

type Summary = Schemas['ConversationSummary']

/**
 * 대화 목록 한 줄의 둘째 줄: "재무 · 승인 대기 · 오늘 11:20"(#556).
 * 같은 말로 시작한 대화가 여럿이어도 언제·어떤 상태인지로 구별되게 합니다. 마지막으로 바뀐 시각(없으면 만든 시각)을 씁니다.
 */
export function conversationMeta(c: Summary, now = new Date()): string {
  return [
    c.agentName ?? '에이전트 미정',
    c.status === 'awaiting_approval' ? '승인 대기' : c.status === 'closed' ? '닫힘' : null,
    formatWhen(c.updatedAt ?? c.createdAt, now),
  ]
    .filter(Boolean)
    .join(' · ')
}
