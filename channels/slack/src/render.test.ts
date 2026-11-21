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
    expect(s).toContain('인용 확인 안 됨')
    expect(s).toContain('인사 · 로컬에서 처리')
  })

  it('차단과 오류를 보여 줍니다', () => {
    const t = collect(ev([{ type: 'blocked', blocked: { reason: '급여는 볼 수 없습니다.', code: 'policy_denied' } }, { type: 'done' }]))
    expect(t.reply!.text).toContain('차단 급여는 볼 수 없습니다.')
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
    expect(s).toContain('~in_progress~ → withdrawn')
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
    expect(flat(card)).toContain('`room` A')
    expect(flat(card)).toContain('`start` 14:00')
  })
})
