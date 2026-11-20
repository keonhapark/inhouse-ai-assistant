import type { Schemas } from '../api/client'

export type ChatEvent = Schemas['ChatEvent']
export type HistoryEvent = Schemas['Conversation']['events'][number]
type Approval = NonNullable<ChatEvent['approval']>
type Action = NonNullable<ChatEvent['action']>
export type Citation = Schemas['Citation']
type Model = NonNullable<ChatEvent['model']>
export type Route = NonNullable<ChatEvent['route']>

export type ThreadItem =
  | { kind: 'user'; key: string; text: string }
  | { kind: 'assistant'; key: string; text: string; streaming: boolean; model?: Model; citations?: Citation[] }
  | { kind: 'tool'; key: string; call: NonNullable<ChatEvent['toolCall']> }
  | { kind: 'approval'; key: string; approval: Approval; decision?: 'approve' | 'reject'; closed?: 'expired' | 'failed' }
  | { kind: 'action'; key: string; action: Action; undone: boolean }
  | { kind: 'blocked'; key: string; reason: string; code?: string }
  | { kind: 'error'; key: string; message: string; retryable: boolean }

export type ThreadState = {
  items: ThreadItem[]
  /** 마지막으로 반영한 ChatEvent.seq. 복원한 기록과 스트림이 겹치면 이 값 이하는 버립니다. */
  lastSeq: number
  streaming: boolean
  route?: Route
  /** 답보다 먼저 온 근거. 다음 답에 붙입니다. */
  pendingCitations?: Citation[]
}

export type ThreadAction =
  | { type: 'reset'; events?: HistoryEvent[] }
  | { type: 'user'; text: string }
  | { type: 'event'; event: ChatEvent }
  | { type: 'stream-start' }
  | { type: 'stream-end' }
  | { type: 'undone'; actionId: string }
  | { type: 'local-error'; message: string; retryable: boolean }
  /** 만료됐거나 결정 요청이 거절된 실행 승인. 더는 결정할 수 없어 대기에서 뺍니다. */
  | { type: 'approval-closed'; approvalId: string; reason: 'expired' | 'failed' }

export const emptyThread: ThreadState = { items: [], lastSeq: -1, streaming: false }

let localKey = 0
const nextKey = (p: string) => `${p}-${++localKey}`

function lastAssistantIndex(items: ThreadItem[]): number {
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].kind === 'assistant') return i
    if (items[i].kind === 'user') return -1
  }
  return -1
}

/** 마지막 사용자 메시지 뒤에서 아직 스트리밍 중인 답의 위치들 */
function streamingInTurn(items: ThreadItem[]): number[] {
  const out: number[] = []
  for (let i = items.length - 1; i >= 0 && items[i].kind !== 'user'; i--) {
    const it = items[i]
    if (it.kind === 'assistant' && it.streaming) out.unshift(i)
  }
  return out
}

function withPendingCitations(st: ThreadState): ThreadState {
  if (!st.pendingCitations) return st
  const { pendingCitations, ...rest } = st
  return { ...rest, items: updateAt(st.items, st.items.length - 1, { citations: pendingCitations }) }
}

function updateAt(items: ThreadItem[], i: number, patch: Partial<ThreadItem>): ThreadItem[] {
  const copy = items.slice()
  copy[i] = { ...copy[i], ...patch } as ThreadItem
  return copy
}

function applyEvent(s: ThreadState, e: ChatEvent): ThreadState {
  if (e.seq <= s.lastSeq) return s
  const st = { ...s, lastSeq: e.seq }
  const items = st.items
  const last = items[items.length - 1]
  switch (e.type) {
    case 'route':
      return { ...st, route: e.route }
    case 'delta': {
      if (last?.kind === 'assistant' && last.streaming) {
        return { ...st, items: updateAt(items, items.length - 1, { text: last.text + (e.text ?? '') }) }
      }
      return withPendingCitations({
        ...st,
        items: [...items, { kind: 'assistant', key: `a-${e.seq}`, text: e.text ?? '', streaming: true }],
      })
    }
    case 'message': {
      // 조각 사이에 도구 호출 등이 끼어 말풍선이 나뉘었어도 완성된 답 하나로 합칩니다.
      const open = streamingInTurn(items)
      if (open.length) {
        const [first, ...rest] = open
        const merged = updateAt(items, first, { text: e.text ?? '', streaming: false, model: e.model })
        return { ...st, items: merged.filter((_, i) => !rest.includes(i)) }
      }
      return withPendingCitations({
        ...st,
        items: [...items, { kind: 'assistant', key: `a-${e.seq}`, text: e.text ?? '', streaming: false, model: e.model }],
      })
    }
    case 'tool_call':
      return e.toolCall ? { ...st, items: [...items, { kind: 'tool', key: `t-${e.seq}`, call: e.toolCall }] } : st
    case 'approval_required':
      return e.approval
        ? { ...st, items: [...items, { kind: 'approval', key: e.approval.approvalId, approval: e.approval }] }
        : st
    case 'approval_decided': {
      const d = e.decision
      if (!d?.approvalId || !d.decision) return st
      const decision = d.decision
      return {
        ...st,
        items: items.map((it) =>
          it.kind === 'approval' && it.approval.approvalId === d.approvalId ? { ...it, decision } : it,
        ),
      }
    }
    case 'action':
      return e.action
        ? { ...st, items: [...items, { kind: 'action', key: e.action.actionId, action: e.action, undone: false }] }
        : st
    case 'citations': {
      if (!e.citations) return st
      const i = lastAssistantIndex(items)
      if (i < 0) return { ...st, pendingCitations: e.citations }
      return { ...st, items: updateAt(items, i, { citations: e.citations }) }
    }
    case 'blocked':
      return {
        ...st,
        items: [
          ...items,
          { kind: 'blocked', key: `b-${e.seq}`, reason: e.blocked?.reason ?? '요청을 처리할 수 없습니다.', code: e.blocked?.code },
        ],
      }
    case 'error':
      return {
        ...st,
        items: [
          ...items,
          {
            kind: 'error',
            key: `e-${e.seq}`,
            message: e.error?.message ?? '답을 만들지 못했습니다.',
            retryable: e.error?.retryable ?? false,
          },
        ],
      }
    case 'done': {
      const i = lastAssistantIndex(items)
      let next = items.map((it) => (it.kind === 'assistant' && it.streaming ? { ...it, streaming: false } : it))
      if (i >= 0 && e.model && !(next[i] as { model?: Model }).model) next = updateAt(next, i, { model: e.model })
      return { ...st, items: next, streaming: false }
    }
  }
}

export function threadReducer(s: ThreadState, a: ThreadAction): ThreadState {
  switch (a.type) {
    case 'reset': {
      let st = emptyThread
      for (const e of a.events ?? []) {
        st = e.type === 'user_message' ? threadReducer(st, { type: 'user', text: e.content }) : applyEvent(st, e)
      }
      return { ...st, streaming: false }
    }
    case 'user':
      return { ...s, pendingCitations: undefined, items: [...s.items, { kind: 'user', key: nextKey('u'), text: a.text }] }
    case 'event':
      return applyEvent(s, a.event)
    case 'stream-start':
      return { ...s, streaming: true }
    case 'stream-end':
      return {
        ...s,
        streaming: false,
        items: s.items.map((it) => (it.kind === 'assistant' && it.streaming ? { ...it, streaming: false } : it)),
      }
    case 'undone':
      return {
        ...s,
        items: s.items.map((it) => (it.kind === 'action' && it.action.actionId === a.actionId ? { ...it, undone: true } : it)),
      }
    case 'local-error':
      return { ...s, items: [...s.items, { kind: 'error', key: nextKey('le'), message: a.message, retryable: a.retryable }] }
    case 'approval-closed':
      return {
        ...s,
        items: s.items.map((it) =>
          it.kind === 'approval' && it.approval.approvalId === a.approvalId && !it.decision ? { ...it, closed: a.reason } : it,
        ),
      }
  }
}

/** 결정하지 않은 실행 승인이 남아 있으면 그 카드. 이때 gateway는 새 메시지를 409로 거절합니다. */
export function pendingApproval(s: ThreadState): Approval | undefined {
  for (let i = s.items.length - 1; i >= 0; i--) {
    const it = s.items[i]
    if (it.kind === 'approval' && !it.decision && !it.closed) return it.approval
  }
  return undefined
}
