import { describe, expect, it } from 'vitest'
import { actionCard, collect, escape, toMrkdwn } from './render.js'
import { ev, flat } from './test-util.js'

describe('render', () => {
  it('슬랙 제어 문자를 바꾸고 굵게를 슬랙 형식으로 씁니다', () => {
    expect(escape('<@U1> & <!channel>')).toBe('&lt;@U1&gt; &amp; &lt;!channel&gt;')
    expect(toMrkdwn('남은 일수 **9.5일**입니다.')).toBe('남은 일수 *9.5일*입니다.')
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
