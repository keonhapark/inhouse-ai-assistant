import { describe, expect, it } from 'vitest'
import { actionCard, approvalCard, collect, escape, toMrkdwn } from './render.js'
import { ev, flat } from './test-util.js'

describe('render', () => {
  it('슬랙 제어 문자를 바꾸고 굵게를 슬랙 형식으로 씁니다', () => {
    expect(escape('<@U1> & <!channel>')).toBe('&lt;@U1&gt; &amp; &lt;!channel&gt;')
    expect(toMrkdwn('남은 일수 **9.5일**입니다.')).toBe('남은 일수 \u200b*9.5일*\u200b입니다.')
  })

  it('근거는 인용 블록으로, 확인 안 된 인용은 표시하고, 로컬 처리를 밝힙니다', () => {
    const t = collect(
      ev([
        { type: 'route', route: { agentId: 'hr', agentName: '인사', method: 'llm', reason: '' } },
        { type: 'message', text: '15일입니다.', model: { name: 'local', location: 'local' } },
        {
          type: 'citations',
          citations: [
            { docId: 'r', title: '취업규칙', article: '제20조', quote: '15일의 유급휴가', verified: true },
            { docId: 'r', title: '취업규칙', article: '제20조 제4항', quote: '가산휴가', verified: false },
          ],
        },
        { type: 'done' },
      ]),
    )
    const s = flat(t.reply!)
    expect(s).toContain('> 15일의 유급휴가')
    expect(s).toContain('`원문 대조 안 됨`')
    expect(s).toContain('인사 · 사내 처리')
  })

  it('차단과 오류를 보여 줍니다', () => {
    const t = collect(ev([{ type: 'blocked', blocked: { reason: '급여는 볼 수 없습니다.', code: 'policy_denied' } }, { type: 'done' }]))
    expect(t.reply!.text).toContain('처리할 수 없는 요청 급여는 볼 수 없습니다.')
  })

  it('되돌릴 수 없는 행동에는 되돌리기 버튼이 없습니다', () => {
    expect(flat(actionCard({ actionId: 'a', tool: 't', summary: '회수함', undoable: false }))).not.toContain('action_undo')
  })
})

describe('render 한도', () => {
  it('긴 답은 3000자 안쪽 section으로 나누고, 블록이 50개를 넘으면 줄였다고 밝힙니다', () => {
    const long = Array.from({ length: 400 }, (_, i) => `${i}번째 줄입니다. 이 줄은 길이를 채우는 시험용 글입니다.`).join('\n')
    const t = collect(ev([{ type: 'message', text: long }, { type: 'done' }]))
    const blocks = t.reply!.blocks as { text?: { text: string } }[]
    expect(blocks.length).toBeGreaterThan(1)
    expect(blocks.every((b) => !b.text || b.text.text.length <= 3000)).toBe(true)
    const huge = collect(ev([...Array.from({ length: 60 }, () => ({ type: 'message' as const, text: '짧은 답' })), { type: 'done' }]))
    expect(huge.reply!.blocks).toHaveLength(50)
    expect(flat(huge.reply!)).toContain('뒷부분을 줄였습니다')
  })
})

describe('미리보기 카드 바뀌는 값', () => {
  it('바꾸기는 달라진 필드만, 긴 값은 줄여서 보여 줍니다', () => {
    const doc = { id: 'doc_1', status: 'in_progress', fields: { reason: '휴식', note: 'x'.repeat(200) }, version: 1 }
    const card = approvalCard(
      {
        approvalId: 'a', tool: 'approval_withdraw', risk: 'irreversible',
        preview: { dryRun: true, operation: 'withdraw', summary: '회수', undoable: false, changes: [{ op: 'update', resource: 'approval_document', resourceId: 'doc_1', before: doc, after: { ...doc, status: 'withdrawn', version: 2, note: 'y'.repeat(200) } }] },
      },
      '인사',
    )
    const s = flat(card)
    // 필드 표시 이름과 상태 이름으로 보입니다
    expect(s).toContain('상태 ~진행 중~ → 회수')
    expect(s).toContain('~1~ → 2')
    expect(s).not.toContain('doc_1')
    expect(s).not.toContain('reason')
    expect(s).toContain('…')
  })

  it('새로 만들기는 모든 값을 보여 줍니다', () => {
    const card = approvalCard(
      { approvalId: 'a', tool: 'room_reserve', risk: 'reversible_write', preview: { dryRun: true, operation: 'x', summary: '예약', undoable: true, changes: [{ op: 'create', resource: 'room', resourceId: null, before: null, after: { room: 'A', start: '14:00' } }] } },
      undefined,
    )
    // 모르는 필드는 코드 이름 그대로 둡니다
    expect(flat(card)).toContain('room A')
    expect(flat(card)).toContain('start 14:00')
  })

  it('필드 표시 이름, 시각, 금액을 사람이 읽는 꼴로 보여 주고 버튼과 제목은 일 이름입니다', () => {
    const card = approvalCard(
      {
        approvalId: 'a', tool: 'room_reserve', toolLabel: '회의실 예약', risk: 'reversible_write', expiresAt: '2026-11-24T05:30:00Z',
        preview: { dryRun: true, operation: 'x', summary: '예약', undoable: true, changes: [{ op: 'create', resource: 'room_reservation', resourceId: null, before: null, after: { startsAt: '2026-11-24T05:00:00Z', amount: 42000 } }] },
      },
      undefined,
    )
    const s = flat(card)
    expect(s).toContain('*실행 전 확인: 회의실 예약*')
    expect(s).toContain('시작 2026. 11. 24. 오후 2:00')
    expect(s).toContain('금액 42,000원')
    expect(s).toContain('"text":"회의실 예약"')
    expect(s).toContain('오후 2:30까지 확인해 주세요.')
    expect(s).not.toContain('room_reserve')
  })
})
