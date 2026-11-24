import { describe, expect, it } from 'vitest'
import { Bridge, jwtExp, MESSAGES, toPlainText } from './bridge.js'
import { GatewayError, RATE_LIMITED, UNAVAILABLE, type ChatEvent, type Gateway } from './gateway.js'
import { ACTION } from './render.js'
import { ev, fakeGateway, fakeSlack, flat } from './test-util.js'

const APPROVAL: NonNullable<ChatEvent['approval']> = {
  approvalId: 'ap-1',
  tool: 'approval_withdraw',
  toolLabel: '결재 회수',
  risk: 'irreversible',
  expiresAt: '2999-01-01T00:00:00Z',
  preview: {
    dryRun: true,
    operation: 'withdrawApproval',
    summary: '휴가 결재를 회수합니다.',
    undoable: false,
    changes: [{ op: 'update', resource: 'approval', resourceId: 'A1', before: { status: 'pending' }, after: { status: 'withdrawn' } }],
  },
}

function setup(over: Partial<Gateway> = {}, botUserId?: string) {
  const g = fakeGateway(over)
  const s = fakeSlack()
  const bridge = new Bridge({ gateway: g.gw, slack: s.slack, webUrl: 'http://web.test', botUserId })
  return { bridge, ...g, ...s }
}

const dm = (user: string, text: string, ts: string, thread_ts?: string) => ({ user, text, channel: 'D1', ts, thread_ts, channel_type: 'im' })

describe('Bridge 메시지', () => {
  it('DM 하나로 대화를 만들고 답을 스레드에 올립니다. 같은 스레드는 같은 대화를 씁니다', async () => {
    const { bridge, calls, posts } = setup()
    await bridge.onMessage(dm('U1', '회의실 잡아 줘', '100.1'))
    await bridge.onMessage(dm('U1', '내일로', '100.2', '100.1'))
    expect(calls.filter((c) => c.startsWith('create'))).toHaveLength(1)
    const sends = calls.filter((c) => c.startsWith('send')).map((c) => c.split(' ')[2])
    expect(new Set(sends).size).toBe(1)
    expect(posts.map((p) => p.threadTs)).toEqual(['100.1', '100.1'])
    expect(flat(posts[0].msg)).toContain('답입니다.')
    expect(flat(posts[0].msg)).toContain('전사 비서')
  })

  it('채널 멘션은 스레드에 안내만 남기고, 답은 요청자 DM에 올립니다', async () => {
    const { bridge, posts, opened, calls } = setup({}, 'UBOT')
    await bridge.onMessage({ user: 'U1', text: '<@UBOT> 내 연차 며칠 남았어?', channel: 'C1', ts: '5.1', channel_type: 'channel' })
    expect(posts[0]).toMatchObject({ channel: 'C1', threadTs: '5.1' })
    expect(posts[0].msg.text).toBe(MESSAGES.movedToDm)
    expect(opened).toEqual(['U1'])
    expect(posts.slice(1).every((p) => p.channel === 'D-U1')).toBe(true)
    expect(posts.filter((p) => p.channel === 'C1')).toHaveLength(1)
    expect(calls.find((c) => c.startsWith('send'))).toMatch(/ 내 연차 며칠 남았어\?$/)
  })

  it('맨 앞의 봇 멘션만 지우고 질문 속 다른 사람 멘션은 둡니다', async () => {
    const { bridge, calls } = setup({}, 'UBOT')
    await bridge.onMessage(dm('U1', '<@UBOT|bot> <@U9>에게 회의실 알려 줘', '1'))
    expect(calls.find((c) => c.startsWith('send'))).toMatch(/ <@U9>에게 회의실 알려 줘$/)
  })

  it('봇 메시지, 편집(하위 형식), 같은 이벤트의 재전달은 무시합니다', async () => {
    const { bridge, calls } = setup()
    await bridge.onMessage({ ...dm('U1', 'x', '1'), bot_id: 'B1' })
    await bridge.onMessage({ ...dm('U1', 'x', '2'), subtype: 'message_changed' })
    await bridge.onMessage(dm('U1', 'x', '3'))
    await bridge.onMessage(dm('U1', 'x', '3'))
    expect(calls.filter((c) => c.startsWith('send'))).toHaveLength(1)
  })

  it('매핑이 없는 사용자에게는 안내만 하고, 잠시 동안 다시 로그인하지 않습니다', async () => {
    const { bridge, calls, posts } = setup()
    await bridge.onMessage(dm('U_UNMAPPED', '안녕', '1'))
    await bridge.onMessage(dm('U_UNMAPPED', '안녕?', '2'))
    expect(calls).toEqual(['login U_UNMAPPED'])
    expect(posts.map((p) => p.msg.text)).toEqual([MESSAGES.unmapped, MESSAGES.unmapped])
  })

  it('다른 사람이 남의 스레드에 쓰면 그 사람에게만 안내합니다', async () => {
    const { bridge, calls, ephemerals } = setup()
    await bridge.onMessage(dm('U1', '질문', '1'))
    await bridge.onMessage(dm('U2', '끼어들기', '2', '1'))
    expect(calls.filter((c) => c.startsWith('send'))).toHaveLength(1)
    expect(ephemerals).toEqual([{ channel: 'D1', user: 'U2', text: MESSAGES.othersThread }])
  })

  it('한 사람은 한 번에 한 메시지만 처리합니다(스레드가 달라도)', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const { bridge, calls, ephemerals } = setup({
      async *send() {
        await gate
        yield* ev([{ type: 'message', text: '끝' }, { type: 'done' }])
      },
    })
    const first = bridge.onMessage(dm('U1', '하나', '1'))
    await new Promise((r) => setTimeout(r, 0))
    await bridge.onMessage(dm('U1', '둘', '2'))
    release()
    await first
    expect(ephemerals.map((e) => e.text)).toEqual([MESSAGES.busy])
    expect(calls.filter((c) => c.startsWith('create'))).toHaveLength(1)
  })

  it('4xx는 problem title을, 5xx는 고정 문구를 올리고 내부 원문은 올리지 않습니다', async () => {
    let status = 409
    const { bridge, posts } = setup({
      // eslint-disable-next-line require-yield
      async *send() {
        throw status === 409 ? new GatewayError('실행 승인을 기다리는 중입니다.', 409) : new GatewayError(UNAVAILABLE, 502, '502 upstream http://litellm:4000 timeout')
      },
    })
    await bridge.onMessage(dm('U1', '또', '1'))
    status = 502
    await bridge.onMessage(dm('U1', '다시', '2'))
    expect(posts.map((p) => p.msg.text)).toEqual(['실행 승인을 기다리는 중입니다.', UNAVAILABLE])
    expect(JSON.stringify(posts)).not.toContain('litellm')
  })

  it('401이면 한 번 다시 로그인해 다시 보냅니다', async () => {
    let n = 0
    const { bridge, calls, posts } = setup({
      async createConversation() {
        n++
        if (n === 1) throw new GatewayError('로그인이 필요합니다.', 401)
        return 'conv-x'
      },
    })
    await bridge.onMessage(dm('U1', '안녕', '1'))
    expect(calls.filter((c) => c.startsWith('login'))).toHaveLength(2)
    expect(flat(posts[0].msg)).toContain('답입니다.')
  })

  it('토큰은 만료 1분 전까지 다시 쓰고, 지나면 다시 로그인합니다', async () => {
    let now = Date.parse('2026-11-21T00:00:00Z')
    const exp = now / 1000 + 600
    const jwt = `x.${Buffer.from(JSON.stringify({ exp })).toString('base64url')}.y`
    const logins: string[] = []
    const { gw } = fakeGateway({
      async login(u) {
        logins.push(u)
        return { token: jwt, expiresIn: 600 }
      },
    })
    const bridge = new Bridge({ gateway: gw, slack: fakeSlack().slack, webUrl: '', now: () => now })
    await bridge.onMessage(dm('U1', 'a', '1'))
    now += 8 * 60_000
    await bridge.onMessage(dm('U1', 'b', '2'))
    now += 2 * 60_000
    await bridge.onMessage(dm('U1', 'c', '3'))
    expect(logins).toHaveLength(2)
    expect(jwtExp(jwt)).toBe(exp * 1000)
    expect(jwtExp('not-a-jwt')).toBeNull()
  })

  it('모델 답의 멘션·링크 문자열은 대체 text와 블록 모두에서 바꿔 올립니다', async () => {
    const { bridge, posts } = setup({
      async *send() {
        yield* ev([{ type: 'message', text: '<!channel> <https://evil.example|사내포털>' }, { type: 'done' }])
      },
    })
    await bridge.onMessage(dm('U1', 'x', '1'))
    expect(posts[0].msg.text).not.toContain('<!')
    expect(flat(posts[0].msg)).not.toContain('<!channel>')
    expect(flat(posts[0].msg)).not.toContain('<https')
  })
})

describe('Bridge /auth/slack 횟수 제한', () => {
  function limited(times: number, retryAfter?: number) {
    let n = 0
    const waits: number[] = []
    const g = fakeGateway({
      async login(u) {
        n++
        if (n <= times) throw new GatewayError(RATE_LIMITED, 429, '429 rate-limited', retryAfter)
        return { token: `tok-${u}`, expiresIn: 900 }
      },
    })
    const s = fakeSlack()
    const bridge = new Bridge({ gateway: g.gw, slack: s.slack, webUrl: '', sleep: async (ms) => void waits.push(ms) })
    return { bridge, waits, logins: () => n, ...g, ...s }
  }

  it('429면 Retry-After만큼 기다렸다 한 번 다시 로그인해 이어 갑니다', async () => {
    const t = limited(1, 2)
    await t.bridge.onMessage(dm('U1', '안녕', '1'))
    expect(t.waits).toEqual([2000])
    expect(t.logins()).toBe(2)
    expect(flat(t.posts[0].msg)).toContain('답입니다.')
  })

  it('다시 해도 막히거나 Retry-After가 30초보다 길면 잠시 뒤 다시 하라고 안내합니다', async () => {
    const twice = limited(2, 1)
    await twice.bridge.onMessage(dm('U1', '안녕', '1'))
    expect(twice.logins()).toBe(2)
    expect(twice.posts[0].msg.text).toBe(RATE_LIMITED)

    const long = limited(1, 120)
    await long.bridge.onMessage(dm('U1', '안녕', '1'))
    expect(long.waits).toEqual([])
    expect(long.logins()).toBe(1)
    expect(long.posts[0].msg.text).toBe(RATE_LIMITED)
  })

  it('토큰 유효 시간이 길어도 15분까지만 다시 씁니다', async () => {
    let now = Date.parse('2026-11-21T00:00:00Z')
    const jwt = `x.${Buffer.from(JSON.stringify({ exp: now / 1000 + 3600 })).toString('base64url')}.y`
    let logins = 0
    const { gw } = fakeGateway({
      async login() {
        logins++
        return { token: jwt, expiresIn: 3600 }
      },
    })
    const bridge = new Bridge({ gateway: gw, slack: fakeSlack().slack, webUrl: '', now: () => now })
    await bridge.onMessage(dm('U1', 'a', '1'))
    now += 14 * 60_000
    await bridge.onMessage(dm('U1', 'b', '2'))
    now += 2 * 60_000
    await bridge.onMessage(dm('U1', 'c', '3'))
    expect(logins).toBe(2)
  })
})

describe('Bridge 실행 승인과 되돌리기', () => {
  async function withCard(over: Partial<Gateway> = {}) {
    const t = setup({
      async *send() {
        yield* ev([
          { type: 'route', route: { agentId: 'hr', agentName: '인사', method: 'keyword', reason: '' } },
          { type: 'message', text: '회수하면 되돌릴 수 없습니다.' },
          { type: 'approval_required', approval: APPROVAL },
          { type: 'done' },
        ])
      },
      ...over,
    })
    await t.bridge.onMessage(dm('U1', '결재 회수', '1'))
    return t
  }

  it('미리보기 카드를 올리고, 요청자가 실행하면 처리 중을 거쳐 실행함으로 바꿉니다', async () => {
    const { bridge, posts, updates, calls } = await withCard()
    const card = posts[1]
    expect(flat(card.msg)).toContain('실행 전 확인: 결재 회수')
    expect(flat(card.msg)).toContain(ACTION.approve)
    expect(flat(card.msg)).toContain('상태 ~대기~ → 회수')
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(calls).toContain('decide tok-U1 ap-1 approve')
    expect(updates.map((u) => u.ts)).toEqual([card.ts, card.ts])
    expect(flat(updates[0].msg)).toContain('처리 중')
    expect(flat(updates[1].msg)).toContain('완료')
    expect(flat(updates[1].msg)).not.toContain(ACTION.approve)
  })

  it('요청자가 아닌 사람이 누르면 결정하지 않고 그 사람에게만 알립니다', async () => {
    const { bridge, calls, ephemerals, updates } = await withCard()
    await bridge.onDecision('U2', 'ap-1', 'approve', 'D1')
    expect(calls.some((c) => c.startsWith('decide'))).toBe(false)
    expect(updates).toEqual([])
    expect(ephemerals[0]).toMatchObject({ user: 'U2', text: MESSAGES.onlyRequester })
    await bridge.onDecision('U1', 'ap-1', 'reject', 'D1')
    expect(calls).toContain('decide tok-U1 ap-1 reject')
  })

  it('두 번 눌러도 한 번만 결정합니다', async () => {
    const { bridge, calls } = await withCard()
    await Promise.all([bridge.onDecision('U1', 'ap-1', 'approve', 'D1'), bridge.onDecision('U1', 'ap-1', 'approve', 'D1')])
    expect(calls.filter((c) => c.startsWith('decide'))).toHaveLength(1)
  })

  it('결정이 4xx로 거절되면 카드를 "더 결정할 수 없음"으로 바꿉니다', async () => {
    const { bridge, updates, posts } = await withCard({
      // eslint-disable-next-line require-yield
      async *decide() {
        throw new GatewayError('이미 결정한 실행 승인입니다.', 409)
      },
    })
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(flat(updates.at(-1)!.msg)).toContain('진행 불가')
    expect(posts.at(-1)!.msg.text).toBe('이미 결정한 실행 승인입니다.')
  })

  it('5xx나 끊김으로 결정이 확인되지 않으면 버튼을 되살려 다시 누를 수 있게 합니다', async () => {
    let fail = true
    const { bridge, updates, calls } = await withCard({
      async *decide(_t, id, d) {
        calls.push(`decide ${id} ${d}`)
        if (fail) throw new GatewayError(UNAVAILABLE, 0)
        yield* ev([{ type: 'approval_decided', decision: { approvalId: id, decision: d } }, { type: 'done' }])
      },
    })
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(flat(updates.at(-1)!.msg)).toContain(ACTION.approve)
    fail = false
    await bridge.onDecision('U1', 'ap-1', 'approve', 'D1')
    expect(calls.filter((c) => c.startsWith('decide'))).toHaveLength(2)
    expect(flat(updates.at(-1)!.msg)).toContain('완료')
  })

  it('되돌리기는 요청자만, 같은 키로 한 번 부르고 카드를 되돌림으로 바꿉니다', async () => {
    const { bridge, posts, updates, calls, ephemerals } = setup({
      async *send() {
        yield* ev([{ type: 'action', action: { actionId: 'act-9', tool: 'room_reserve', summary: '회의실을 예약했습니다.', undoable: true } }, { type: 'done' }])
      },
    })
    await bridge.onMessage(dm('U1', '회의실', '1'))
    expect(flat(posts[0].msg)).toContain(ACTION.undo)
    await bridge.onUndo('U2', 'act-9', 'D1')
    expect(ephemerals[0].text).toBe(MESSAGES.onlyRequester)
    await bridge.onUndo('U1', 'act-9', 'D1')
    await bridge.onUndo('U1', 'act-9', 'D1')
    expect(calls.filter((c) => c.startsWith('undo'))).toEqual(['undo tok-U1 act-9 slack-undo-act-9'])
    expect(flat(updates[0].msg)).toContain('취소됨')
    expect(ephemerals.at(-1)!.text).toBe(MESSAGES.staleCard)
  })

  it('되돌리기가 실패하면 카드에 슬랙에 보여도 되는 문구만 남깁니다', async () => {
    const { bridge, updates } = setup({
      async *send() {
        yield* ev([{ type: 'action', action: { actionId: 'act-1', tool: 'room_reserve', summary: '예약', undoable: true } }, { type: 'done' }])
      },
      async undo() {
        throw new GatewayError('그 사이 상태가 바뀌어 되돌릴 수 없습니다.', 409, '409 conflict at /api/v1/rooms/42')
      },
    })
    await bridge.onMessage(dm('U1', '회의실', '1'))
    await bridge.onUndo('U1', 'act-1', 'D1')
    expect(flat(updates[0].msg)).toContain('그 사이 상태가 바뀌어 되돌릴 수 없습니다.')
    expect(flat(updates[0].msg)).not.toContain('/api/v1')
  })
})

describe('결재 알림', () => {
  type N = Awaited<ReturnType<Gateway['notifications']>>[number]
  const n = (id: string, message: string, read = false): N => ({ id, kind: 'approval_turn', message, createdAt: '2026-11-21T00:00:00Z', read })

  it('처음 본 알림은 보내지 않고, 새로 온 읽지 않은 알림만 웹 승인함 링크와 함께 DM으로 보냅니다', async () => {
    let items = [n('n1', '옛 알림')]
    const { bridge, dms } = setup({ async notifications() { return items } })
    await bridge.onMessage(dm('U1', '안녕', '1'))
    await bridge.pollNotifications()
    expect(dms()).toEqual([])
    items = [...items, n('n2', '한지우님의 휴가 신청이 결재 차례입니다.'), n('n3', '이미 읽음', true)]
    await bridge.pollNotifications()
    await bridge.pollNotifications()
    expect(dms()).toHaveLength(1)
    expect(dms()[0].channel).toBe('D-U1')
    expect(flat(dms()[0].msg)).toContain('http://web.test/approvals')
    expect(flat(dms()[0].msg)).not.toContain(ACTION.approve)
  })

  it('DM을 보내지 못한 알림은 다음 조회 때 다시 보냅니다', async () => {
    let items = [n('n1', '옛 알림')]
    const t = setup({ async notifications() { return items } })
    let broken = true
    const post = t.slack.post
    t.slack.post = async (c, th, m) => {
      if (broken && c.startsWith('D-')) throw new Error('rate_limited')
      return post(c, th, m)
    }
    await t.bridge.onMessage(dm('U1', '안녕', '1'))
    await t.bridge.pollNotifications()
    items = [...items, n('n2', '결재 차례')]
    await t.bridge.pollNotifications()
    expect(t.dms()).toHaveLength(0)
    broken = false
    await t.bridge.pollNotifications()
    expect(t.dms()).toHaveLength(1)
  })

  it('앞 조회가 끝나지 않았으면 겹쳐 돌지 않고, 매핑 없는 사용자는 대상에 넣지 않습니다', async () => {
    let calls = 0
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const { bridge } = setup({
      async notifications() {
        calls++
        await gate
        return []
      },
    })
    await bridge.onMessage(dm('U1', '안녕', '1'))
    await bridge.onMessage(dm('U_UNMAPPED', '안녕', '2'))
    const first = bridge.pollNotifications()
    await bridge.pollNotifications()
    release()
    await first
    expect(calls).toBe(1)
  })
})

describe('toPlainText', () => {
  it('슬랙 서식 기호와 이스케이프를 풀어 일반 글로 넘깁니다', () => {
    expect(toPlainText('*2026-11-20 가온식당에서 42,000원 썼어*')).toBe('2026-11-20 가온식당에서 42,000원 썼어')
    expect(toPlainText('_목적_은 ~점심~ 접대')).toBe('_목적_은 점심 접대')
    expect(toPlainText('목적은 _접대_ 야')).toBe('목적은 접대 야')
    expect(toPlainText('3*4 와 a_b_c 는 그대로')).toBe('3*4 와 a_b_c 는 그대로')
    expect(toPlainText('규정 <https://x.example/a|여비 규정> 봐 줘')).toBe('규정 여비 규정(https://x.example/a) 봐 줘')
    expect(toPlainText('메일 <mailto:a@example.com|a@example.com> &amp; &lt;b&gt;')).toBe('메일 a@example.com & <b>')
    expect(toPlainText('`어제 점심 4만 2천 원 정산`')).toBe('어제 점심 4만 2천 원 정산')
    expect(toPlainText('```\n여러 줄\n```')).toBe('여러 줄')
  })

  it('굵게 쓴 메시지도 서식 없이 gateway로 보냅니다', async () => {
    const { bridge, calls } = setup()
    await bridge.onMessage(dm('U1', '*2026-11-20 점심 42,000원 정산*', '1'))
    expect(calls.find((c) => c.startsWith('send'))).toMatch(/ 2026-11-20 점심 42,000원 정산$/)
  })
})
