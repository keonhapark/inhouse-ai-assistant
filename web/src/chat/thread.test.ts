import { describe, expect, it } from 'vitest'
import { emptyThread, pendingApproval, threadReducer, type ChatEvent, type ThreadState } from './thread'

const C = 'c-1'
let seq = 0
const ev = (e: Omit<ChatEvent, 'conversationId' | 'seq'> & { seq?: number }): ChatEvent => ({
  conversationId: C,
  seq: e.seq ?? seq++,
  ...e,
})

function run(events: ChatEvent[], from: ThreadState = emptyThread) {
  return events.reduce((s, event) => threadReducer(s, { type: 'event', event }), from)
}

const preview = { dryRun: true as const, operation: 'reserveRoom', summary: '3층 소회의실을 예약합니다', changes: [], undoable: true }

describe('threadReducer', () => {
  it('delta 조각을 한 답으로 잇고 message로 확정하며 모델 위치를 남깁니다', () => {
    seq = 0
    const s = run([
      ev({ type: 'route', route: { agentId: 'hr', agentName: '인사', method: 'llm', reason: '휴가' } }),
      ev({ type: 'delta', text: '연차는 ' }),
      ev({ type: 'delta', text: '15일입니다' }),
      ev({ type: 'message', text: '연차는 15일입니다.', model: { name: 'qwen', location: 'local' } }),
      ev({ type: 'done' }),
    ])
    expect(s.route?.agentName).toBe('인사')
    expect(s.items).toHaveLength(1)
    expect(s.items[0]).toMatchObject({ kind: 'assistant', text: '연차는 15일입니다.', streaming: false, model: { location: 'local' } })
  })

  it('done만 와도 스트리밍 중인 답을 닫고 model을 붙입니다', () => {
    seq = 0
    const s = run([ev({ type: 'delta', text: '부분' }), ev({ type: 'done', model: { name: 'm', location: 'external' } })])
    expect(s.items[0]).toMatchObject({ text: '부분', streaming: false, model: { location: 'external' } })
  })

  it('citations는 같은 차례의 마지막 답에 붙습니다', () => {
    seq = 0
    const citation = { docId: 'd', title: '취업규칙', article: '제20조', quote: '연차', verified: true }
    const s = run([ev({ type: 'message', text: '답' }), ev({ type: 'citations', citations: [citation] })])
    expect(s.items[0]).toMatchObject({ kind: 'assistant', citations: [citation] })
  })

  it('사용자 메시지 뒤 답이 없으면 citations를 앞 차례 답에 붙이지 않습니다', () => {
    seq = 0
    let s = run([ev({ type: 'message', text: '앞 답' })])
    s = threadReducer(s, { type: 'user', text: '질문' })
    s = run([ev({ type: 'citations', citations: [] })], s)
    expect(s.items[0]).not.toHaveProperty('citations')
  })

  it('실행 승인 카드는 결정이 오면 닫히고, 그 전까지 pendingApproval로 잡힙니다', () => {
    seq = 0
    let s = run([ev({ type: 'approval_required', approval: { approvalId: 'ap-1', tool: 'room_reserve', risk: 'reversible_write', preview } })])
    expect(pendingApproval(s)?.approvalId).toBe('ap-1')
    s = run([ev({ type: 'approval_decided', decision: { approvalId: 'ap-1', decision: 'approve' } })], s)
    expect(pendingApproval(s)).toBeUndefined()
    expect(s.items[0]).toMatchObject({ kind: 'approval', decision: 'approve' })
  })

  it('행동 카드는 되돌리면 undone이 됩니다', () => {
    seq = 0
    let s = run([ev({ type: 'action', action: { actionId: 'act-1', tool: 'room_reserve', summary: '예약함', undoable: true } })])
    s = threadReducer(s, { type: 'undone', actionId: 'act-1' })
    expect(s.items[0]).toMatchObject({ kind: 'action', undone: true })
  })

  it('이미 반영한 seq는 다시 반영하지 않습니다(복원과 스트림이 겹칠 때)', () => {
    const s = run([ev({ type: 'delta', text: 'a', seq: 3 }), ev({ type: 'delta', text: 'a', seq: 3 }), ev({ type: 'delta', text: 'b', seq: 2 })])
    expect(s.items[0]).toMatchObject({ text: 'a' })
    expect(s.lastSeq).toBe(3)
  })

  it('blocked·error는 이유 문장으로 남습니다', () => {
    seq = 0
    const s = run([
      ev({ type: 'blocked', blocked: { reason: '이 에이전트는 급여 정보를 볼 수 없습니다.', code: 'tool_not_allowed' } }),
      ev({ type: 'error', error: { message: '모델 응답 시간이 지났습니다.', retryable: true } }),
    ])
    expect(s.items.map((i) => i.kind)).toEqual(['blocked', 'error'])
  })

  it('reset은 사용자 메시지와 이벤트로 화면을 복원하고 스트리밍 상태를 끕니다', () => {
    const s = threadReducer(emptyThread, {
      type: 'reset',
      events: [
        { type: 'user_message', content: '안녕', at: '2026-11-20T10:00:00Z' },
        { type: 'message', conversationId: C, seq: 0, text: '안녕하세요' },
      ],
    })
    expect(s.items.map((i) => i.kind)).toEqual(['user', 'assistant'])
    expect(s.streaming).toBe(false)
    expect(s.lastSeq).toBe(0)
  })
  it('조각 사이에 도구 호출이 끼어도 message가 오면 답 하나로 합칩니다', () => {
    seq = 0
    const s = run([
      ev({ type: 'delta', text: '찾아' }),
      ev({ type: 'tool_call', toolCall: { tool: 'policy_search', risk: 'read', status: 'ok' } }),
      ev({ type: 'delta', text: '보니' }),
      ev({ type: 'message', text: '찾아보니 15일입니다.' }),
    ])
    expect(s.items.map((i) => i.kind)).toEqual(['assistant', 'tool'])
    expect(s.items[0]).toMatchObject({ text: '찾아보니 15일입니다.', streaming: false })
  })

  it('답보다 먼저 온 근거는 다음 답에 붙고, 새 사용자 메시지가 오면 버립니다', () => {
    seq = 0
    const citation = { docId: 'd', title: '취업규칙', article: null, quote: 'q', verified: true }
    let s = threadReducer(emptyThread, { type: 'user', text: '질문' })
    s = run([ev({ type: 'citations', citations: [citation] }), ev({ type: 'message', text: '답' })], s)
    expect(s.items[1]).toMatchObject({ kind: 'assistant', citations: [citation] })

    s = run([ev({ type: 'citations', citations: [citation] })], threadReducer(s, { type: 'user', text: '다음' }))
    s = threadReducer(s, { type: 'user', text: '또' })
    expect(s.pendingCitations).toBeUndefined()
  })

  it('만료되거나 거절된 승인은 대기에서 빠집니다', () => {
    seq = 0
    let s = run([ev({ type: 'approval_required', approval: { approvalId: 'ap-9', tool: 't', risk: 'read', preview } })])
    s = threadReducer(s, { type: 'approval-closed', approvalId: 'ap-9', reason: 'expired' })
    expect(pendingApproval(s)).toBeUndefined()
    expect(s.items[0]).toMatchObject({ closed: 'expired' })
  })
})
