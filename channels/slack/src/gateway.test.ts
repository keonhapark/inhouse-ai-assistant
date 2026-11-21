import { describe, expect, it } from 'vitest'
import { GatewayError, httpGateway, UNAVAILABLE } from './gateway.js'

type Seen = { url: string; init: RequestInit }
function fakeFetch(respond: (url: string, init: RequestInit) => Response) {
  const seen: Seen[] = []
  const f = (async (url: string, init: RequestInit) => {
    seen.push({ url, init })
    return respond(url, init)
  }) as unknown as typeof fetch
  return { f, seen }
}

const sse = (lines: string) => new Response(lines, { headers: { 'Content-Type': 'text/event-stream' } })
const problem = (status: number, title: string) => new Response(JSON.stringify({ title, status }), { status, headers: { 'Content-Type': 'application/problem+json' } })

describe('httpGateway', () => {
  it('슬랙 로그인은 브리지 비밀값 헤더와 사용자 ID를 보내고, 403이면 null', async () => {
    const { f, seen } = fakeFetch(() => Response.json({ accessToken: 'jwt', tokenType: 'Bearer', expiresIn: 600, employee: {} }))
    const gw = httpGateway({ baseUrl: 'http://gw/api/', bridgeSecret: 's3cret', fetch: f })
    expect(await gw.login('U1')).toEqual({ token: 'jwt', expiresIn: 600 })
    expect(seen[0].url).toBe('http://gw/api/auth/slack')
    expect((seen[0].init.headers as Record<string, string>)['X-Slack-Bridge-Secret']).toBe('s3cret')
    expect(JSON.parse(String(seen[0].init.body))).toEqual({ slackUserId: 'U1' })

    const denied = httpGateway({ baseUrl: 'http://gw/api', bridgeSecret: 's', fetch: fakeFetch(() => problem(403, '매핑 없음')).f })
    expect(await denied.login('U2')).toBeNull()
  })

  it('메시지 스트림을 이벤트로 읽고 직원 토큰을 붙입니다', async () => {
    const { f, seen } = fakeFetch(() => sse('event: message\ndata: {"type":"message","text":"안녕"}\n\nevent: done\ndata: {"type":"done"}\n\n'))
    const gw = httpGateway({ baseUrl: 'http://gw/api', bridgeSecret: 's', fetch: f })
    const events = []
    for await (const e of gw.send('tok', 'c 1', '질문')) events.push(e.type)
    expect(events).toEqual(['message', 'done'])
    expect(seen[0].url).toBe('http://gw/api/conversations/c%201/messages')
    expect((seen[0].init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
  })

  it('done 없이 닫히면 끊겼다고 알립니다', async () => {
    const gw = httpGateway({ baseUrl: 'http://gw/api', bridgeSecret: 's', fetch: fakeFetch(() => sse('data: {"type":"delta","text":"반"}\n\n')).f })
    const read = async () => {
      for await (const _ of gw.send('t', 'c', 'x')) void _
    }
    await expect(read()).rejects.toThrow('응답이 중간에 끊겼습니다.')
  })

  it('오류는 problem title과 상태로, 연결 실패는 상태 0으로', async () => {
    const gw = httpGateway({ baseUrl: 'http://gw/api', bridgeSecret: 's', fetch: fakeFetch(() => problem(409, '이미 결정한 실행 승인입니다.')).f })
    await expect(gw.undo('t', 'a', 'k')).rejects.toMatchObject({ message: '이미 결정한 실행 승인입니다.', status: 409 })
    // 5xx는 detail을 슬랙에 올리지 않도록 고정 문구로 바꾸고 원문은 internal에만 둡니다.
    const five = httpGateway({
      baseUrl: 'http://gw/api',
      bridgeSecret: 's',
      fetch: fakeFetch(() => new Response(JSON.stringify({ title: 'Bad Gateway', detail: 'http://litellm:4000 timeout' }), { status: 502 })).f,
    })
    const err = (await five.createConversation('t').catch((e: unknown) => e)) as GatewayError
    expect(err).toMatchObject({ message: UNAVAILABLE, status: 502 })
    expect(err.internal).toContain('litellm')
    const down = httpGateway({
      baseUrl: 'http://gw/api',
      bridgeSecret: 's',
      fetch: (async () => {
        throw new TypeError('fetch failed')
      }) as unknown as typeof fetch,
    })
    await expect(down.createConversation('t')).rejects.toBeInstanceOf(GatewayError)
  })

  it('되돌리기에 Idempotency-Key를 붙입니다', async () => {
    const { f, seen } = fakeFetch(() => Response.json({ actionId: 'u', undoOf: 'a' }, { status: 201 }))
    await httpGateway({ baseUrl: 'http://gw/api', bridgeSecret: 's', fetch: f }).undo('t', 'a', 'slack-undo-a')
    expect((seen[0].init.headers as Record<string, string>)['Idempotency-Key']).toBe('slack-undo-a')
  })
})
