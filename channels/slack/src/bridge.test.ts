import { describe, expect, it } from 'vitest'
import { Bridge, jwtExp, MESSAGES } from './bridge.js'
import { GatewayError } from './gateway.js'
import type { ChatEvent } from './gateway.js'
import { ACTION } from './render.js'
import { ev, fakeGateway, fakeSlack, flat } from './test-util.js'

const APPROVAL: NonNullable<ChatEvent['approval']> = {
  approvalId: 'ap-1',
  tool: 'approval_withdraw',
  toolLabel: '결재 회수',
  risk: 'irreversible',
  expiresAt: '2026-11-21T01:00:00Z',
  preview: { dryRun: true, operation: 'withdrawApproval', summary: '휴가 결재를 회수합니다.', undoable: false, changes: [{ op: 'update' as const, resource: 'approval', resourceId: 'A1', before: { status: 'pending' }, after: { status: 'withdrawn' } }] },
}

function setup(over = {}) {
  const g = fakeGateway(over)
  const s = fakeSlack()
  const bridge = new Bridge({ gateway: g.gw, slack: s.slack, webUrl: 'http://web.test' })
  return { bridge, ...g, ...s }
}

describe('Bridge 메시지', () => {
  it('DM 하나로 대화를 만들고 답을 스레드에 올립니다. 같은 스레드는 같은 대화를 씁니다', async () => {
    const { bridge, calls, posts } = setup()
    await bridge.onMessage({ user: 'U1', text: '회의실 잡아 줘', channel: 'D1', ts: '100.1' })
    await bridge.onMessage({ user: 'U1', text: '내일로', channel: 'D1', ts: '100.2', thread_ts: '100.1' })
    expect(calls.filter((c) => c.startsWith('create'))).toHaveLength(1)
    expect(calls.filter((c) => c.startsWith('send')).map((c) => c.split(' ')[2])).toEqual(['conv-2', 'conv-2'])
    expect(posts.map((p) => p.threadTs)).toEqual(['100.1', '100.1'])
    expect(flat(posts[0].msg)).toContain('답입니다.')
    expect(flat(posts[0].msg)).toContain('전사 비서')
  })

  it('멘션 표시를 빼고 보냅니다', async () => {
    const { bridge, calls } = setup()
    await bridge.onMessage({ user: 'U1', text: '<@UBOT> 연차 규정', channel: 'C1', ts: '1.1' })
    expect(calls.find((c) => c.startsWith('send'))).toMatch(/ 연차 규정$/)
  })

  it('봇 메시지와 편집(하위 형식)은 무시합니다', async () => {
    const { bridge, calls, posts } = setup()
    await bridge.onMessage({ user: 'U1', text: 'x', channel: 'D1', ts: '1', bot_id: 'B1' })
    await bridge.onMessage({ user: 'U1', text: 'x', channel: 'D1', ts: '2', subtype: 'message_changed' })
    expect(calls).toEqual([])
    expect(posts).toEqual([])
  })

  it('매핑이 없는 사용자에게는 안내만 하고 대화를 만들지 않습니다', async () => {
    const { bridge, calls, posts } = setup()
    await bridge.onMessage({ user: 'U_UNMAPPED', text: '안녕', channel: 'D1', ts: '1' })
    expect(calls).toEqual(['login U_UNMAPPED'])
    expect(posts[0].msg.text).toBe(MESSAGES.unmapped)
  })

  it('다른 사람이 남의 스레드에 쓰면 그 사람에게만 안내합니다', async () => {
    const { bridge, calls, ephemerals } = setup()
    await bridge.onMessage({ user: 'U1', text: '질문', channel: 'C1', ts: '1' })
    await bridge.onMessage({ user: 'U2', text: '끼어들기', channel: 'C1', ts: '2', thread_ts: '1' })
    expect(calls.filter((c) => c.startsWith('send'))).toHaveLength(1)
    expect(ephemerals).toEqual([{ channel: 'C1', user: 'U2', text: MESSAGES.othersThread }])
  })

  it('gateway 오류는 problem title을 스레드에 올립니다', async () => {
    const { bridge, posts } = setup({
      // eslint-disable-next-line require-yield
      async *send() {
        throw new GatewayError('실행 승인을 기다리는 중입니다.', 409)
      },
    })
    await bridge.onMessage({ user: 'U1', text: '또', channel: 'D1', ts: '1' })
    expect(posts[0].msg.text).toBe('실행 승인을 기다리는 중입니다.')
  })

  it('토큰은 만료 전까지 다시 씁니다', async () => {
    const exp = Math.floor(Date.now() / 1000) + 3600
    const jwt = `x.${Buffer.from(JSON.stringify({ exp })).toString('base64url')}.y`
    const { gw, calls } = fakeGateway({ async login() { calls.push('login'); return jwt } })
    const bridge = new Bridge({ gateway: gw, slack: fakeSlack().slack, webUrl: '' })
    await bridge.onMessage({ user: 'U1', text: 'a', channel: 'D1', ts: '1' })
    await bridge.onMessage({ user: 'U1', text: 'b', channel: 'D1', ts: '2' })
    expect(calls.filter((c) => c === 'login')).toHaveLength(1)
    expect(jwtExp(jwt)).toBe(exp * 1000)
    expect(jwtExp('not-a-jwt')).toBeNull()
  })
})

describe('Bridge 실행 승인과 되돌리기', () => {
  async function withCard() {
    const t = setup({
      async *send() {
        yield* ev([
          { type: 'route', route: { agentId: 'hr', agentName: '인사', method: 'keyword', reason: '' } },
          { type: 'message', text: '회수하면 되돌릴 수 없습니다.' },
          { type: 'approval_required', approval: APPROVAL },
          { type: 'done' },
        ])
      },
    })
    await t.bridge.onMessage({ user: 'U1', text: '결재 회수', channel: 'D1', ts: '1' })
    return t
  }

  it('실행 미리보기 카드를 올리고, 요청자가 실행을 누르면 결정하고 카드를 바꿉니다', async () => {
    const { bridge, posts, updates, calls } = await withCard()
    const card = posts[1]
    expect(flat(card.msg)).toContain('실행 미리보기: 결재 회수')
    expect(flat(card.msg)).toContain(ACTION.approve)
    expect(flat(card.msg)).toContain('~pending~ → withdrawn')
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(calls).toContain('decide tok-U1 ap-1 approve')
    expect(updates[0].ts).toBe(card.ts)
    expect(flat(updates[0].msg)).toContain('실행함')
    expect(flat(updates[0].msg)).not.toContain(ACTION.approve)
  })

  it('요청자가 아닌 사람이 누르면 결정하지 않고 그 사람에게만 알립니다', async () => {
    const { bridge, calls, ephemerals, updates } = await withCard()
    await bridge.onDecision('U2', 'ap-1', 'approve', 'D1')
    expect(calls.some((c) => c.startsWith('decide'))).toBe(false)
    expect(updates).toEqual([])
    expect(ephemerals[0]).toMatchObject({ user: 'U2', text: MESSAGES.onlyRequester })
    // 요청자는 그 뒤에도 결정할 수 있습니다.
    await bridge.onDecision('U1', 'ap-1', 'reject', 'D1')
    expect(calls).toContain('decide tok-U1 ap-1 reject')
  })

  it('두 번 눌러도 한 번만 결정합니다', async () => {
    const { bridge, calls } = await withCard()
    await Promise.all([bridge.onDecision('U1', 'ap-1', 'approve', 'D1'), bridge.onDecision('U1', 'ap-1', 'approve', 'D1')])
    expect(calls.filter((c) => c.startsWith('decide'))).toHaveLength(1)
  })

  it('결정이 4xx로 거절되면 카드를 "더 결정할 수 없음"으로 바꿉니다', async () => {
    const t = await withCard()
    const bridge = new Bridge({
      gateway: {
        ...t.gw,
        // eslint-disable-next-line require-yield
        async *decide() {
          throw new GatewayError('이미 결정한 실행 승인입니다.', 409)
        },
      },
      slack: t.slack,
      webUrl: '',
    })
    // 새 브리지에 같은 카드를 만들기 위해 메시지를 다시 보냅니다.
    await bridge.onMessage({ user: 'U1', text: '결재 회수', channel: 'D1', ts: '9' })
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(flat(t.updates.at(-1)!.msg)).toContain('더 결정할 수 없음')
    expect(t.posts.at(-1)!.msg.text).toBe('이미 결정한 실행 승인입니다.')
  })

  it('되돌리기는 요청자만, 같은 키로 한 번 부르고 카드를 되돌림으로 바꿉니다', async () => {
    const { bridge, posts, updates, calls, ephemerals } = setup({
      async *send() {
        yield* ev([{ type: 'action', action: { actionId: 'act-9', tool: 'room_reserve', summary: '회의실을 예약했습니다.', undoable: true } }, { type: 'done' }])
      },
    })
    await bridge.onMessage({ user: 'U1', text: '회의실', channel: 'D1', ts: '1' })
    expect(flat(posts[0].msg)).toContain(ACTION.undo)
    await bridge.onUndo('U2', 'act-9', 'D1')
    expect(ephemerals[0].text).toBe(MESSAGES.onlyRequester)
    await bridge.onUndo('U1', 'act-9', 'D1')
    await bridge.onUndo('U1', 'act-9', 'D1')
    expect(calls.filter((c) => c.startsWith('undo'))).toEqual(['undo tok-U1 act-9 slack-undo-act-9'])
    expect(flat(updates[0].msg)).toContain('되돌림')
  })
})

describe('결재 알림', () => {
  it('처음 본 알림은 보내지 않고, 그 뒤 새 알림만 웹 승인함 링크와 함께 DM으로 보냅니다', async () => {
    let items = [{ id: 'n1', kind: 'approval_turn' as const, message: '옛 알림', createdAt: '2026-11-20T00:00:00Z', read: false }]
    const { bridge, dms } = setup({ async notifications() { return items } })
    await bridge.onMessage({ user: 'U1', text: '안녕', channel: 'D1', ts: '1' })
    await bridge.pollNotifications()
    expect(dms).toEqual([])
    items = [...items, { id: 'n2', kind: 'approval_turn', message: '한지우님의 휴가 신청이 결재 차례입니다.', createdAt: '2026-11-21T00:00:00Z', read: false }]
    await bridge.pollNotifications()
    await bridge.pollNotifications()
    expect(dms).toHaveLength(1)
    expect(flat(dms[0].msg)).toContain('http://web.test/inbox')
    expect(flat(dms[0].msg)).not.toContain(ACTION.approve)
  })
})
