import { GatewayError, type ChatEvent, type Gateway } from './gateway.js'
import { actionCard, approvalCard, collect, notificationMessage, text, type SlackMessage } from './render.js'

/** 브리지가 슬랙에 바라는 것. Bolt 클라이언트를 감싼 것이고, 시험에서는 가짜로 바꿉니다. */
export interface Slack {
  /** 채널(또는 DM)에 올리고 메시지 ts를 돌려줍니다. threadTs가 있으면 그 스레드에 답합니다. */
  post(channel: string, threadTs: string | undefined, msg: SlackMessage): Promise<string>
  update(channel: string, ts: string, msg: SlackMessage): Promise<void>
  /** 한 사람에게만 보이는 안내(누를 권한이 없을 때 등) */
  ephemeral(channel: string, user: string, threadTs: string | undefined, text: string): Promise<void>
  /** 직원과의 DM 채널 ID를 엽니다. */
  openDm(user: string): Promise<string>
}

/** 슬랙 메시지 이벤트에서 브리지가 쓰는 필드. */
export type Incoming = {
  user?: string
  text?: string
  channel: string
  ts: string
  thread_ts?: string
  bot_id?: string
  subtype?: string
  /** 'im'이면 DM, 아니면 채널 멘션 */
  channel_type?: string
}

type Conversation = { conversationId: string; slackUserId: string; at: number }
type Card<T> = { slackUserId: string; channel: string; threadTs: string; ts: string; item: T; agentName?: string; at: number }
type Approval = NonNullable<ChatEvent['approval']>
type Action = NonNullable<ChatEvent['action']>

export const MESSAGES = {
  unmapped: '이 슬랙 계정과 연결된 직원 계정이 없습니다. 관리자에게 슬랙 사용자 연결을 요청해 주세요.',
  othersThread: '이 스레드는 다른 사람의 대화입니다. 새 메시지로 시작해 주세요.',
  busy: '앞 메시지를 처리하는 중입니다. 답이 온 뒤에 보내 주세요.',
  onlyRequester: '실행을 요청한 사람만 누를 수 있습니다.',
  empty: '무엇을 도와드릴까요? 회의실 예약, 연차 규정처럼 물어보면 맞는 부서 에이전트가 답합니다.',
  movedToDm: '답에 개인 정보가 들어갈 수 있어 DM으로 이어 갑니다.',
  staleCard: '이 카드는 더 누를 수 없습니다(브리지가 다시 시작됐거나 이미 처리함).',
  failed: '처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.',
} as const

/** 스레드↔대화, 실행한 일 카드를 기억하는 시간. 지나면 새 스레드로 시작하고 되돌리기는 웹에서 합니다. */
const KEEP_MS = 24 * 60 * 60_000
/** 매핑 없는 사용자의 로그인 실패를 기억하는 시간(매 메시지마다 gateway를 부르지 않게) */
const UNMAPPED_MS = 5 * 60_000
/** 같은 이벤트가 다시 와도 한 번만 처리하도록 기억하는 시간 */
const DEDUPE_MS = 10 * 60_000
/** 직원 토큰을 다시 쓰는 최대 시간(/auth/slack 호출을 줄임). 토큰 만료 1분 전이 더 이르면 그때까지 */
const TOKEN_REUSE_MS = 15 * 60_000
/** /auth/slack이 429면 Retry-After만큼 한 번 기다립니다. 이보다 길면 기다리지 않고 안내합니다 */
const MAX_RETRY_WAIT_S = 30

type Options = {
  gateway: Gateway
  slack: Slack
  webUrl: string
  /** 봇 자신의 슬랙 사용자 ID(멘션에서 이것만 지웁니다). 모르면 맨 앞 멘션 하나를 지웁니다. */
  botUserId?: string
  now?: () => number
  /** 기다리기(시험에서 바꿉니다) */
  sleep?: (ms: number) => Promise<void>
  log?: (msg: string, err?: unknown) => void
}

/**
 * 슬랙과 gateway를 잇습니다.
 * - DM은 그 스레드에서, 채널 멘션은 스레드에 안내만 남기고 요청자와의 DM에서 대화합니다(답에 개인 정보가 들어갈 수 있음).
 * - 같은 스레드는 같은 gateway 대화이고, 스레드를 시작한 사람만 그 대화를 이어 갑니다.
 * - 한 사람은 한 번에 한 메시지만 처리합니다.
 * - 상태는 메모리에만 두고 오래된 것은 지웁니다. 다시 시작하면 새 스레드로 시작합니다.
 */
export class Bridge {
  private readonly gateway: Gateway
  private readonly slack: Slack
  private readonly webUrl: string
  private readonly botUserId?: string
  private readonly now: () => number
  private readonly sleep: (ms: number) => Promise<void>
  private readonly log: (msg: string, err?: unknown) => void
  private readonly threads = new Map<string, Conversation>()
  private readonly busyUsers = new Set<string>()
  private readonly seenEvents = new Map<string, number>()
  private readonly tokens = new Map<string, { token: string | null; exp: number }>()
  private readonly approvals = new Map<string, Card<Approval>>()
  private readonly actions = new Map<string, Card<Action>>()
  /** 알림을 받을 사람(브리지에 말을 건 직원)과 지난 조회 때 본 알림 ID. null이면 아직 기준을 잡지 않음 */
  private readonly watchers = new Map<string, Set<string> | null>()
  private polling = false

  constructor(o: Options) {
    this.gateway = o.gateway
    this.slack = o.slack
    this.webUrl = o.webUrl
    this.botUserId = o.botUserId
    this.now = o.now ?? Date.now
    this.sleep = o.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)))
    this.log = o.log ?? (() => undefined)
  }

  /** DM이나 멘션 하나를 처리합니다. 봇 메시지·편집·삭제 같은 하위 형식과 이미 본 이벤트는 무시합니다. */
  async onMessage(m: Incoming): Promise<void> {
    if (m.bot_id || m.subtype || !m.user) return
    const user = m.user
    this.prune()
    const eventKey = `${m.channel}:${m.ts}`
    if (this.seenEvents.has(eventKey)) return
    this.seenEvents.set(eventKey, this.now())

    try {
      const content = toPlainText(this.stripMention(m.text ?? ''))
      // 채널 멘션은 스레드에 안내만 남기고 DM에서 새 대화로 답합니다.
      let channel = m.channel
      let threadTs = m.thread_ts ?? m.ts
      if (m.channel_type !== 'im') {
        await this.slack.post(m.channel, threadTs, text(MESSAGES.movedToDm))
        channel = await this.slack.openDm(user)
        threadTs = await this.slack.post(channel, undefined, text(`채널에서 물어본 내용: ${content || '(내용 없음)'}`))
      }
      if (!content) {
        await this.slack.post(channel, threadTs, text(MESSAGES.empty))
        return
      }
      const key = `${channel}:${threadTs}`
      const known = this.threads.get(key)
      if (known && known.slackUserId !== user) {
        await this.slack.ephemeral(channel, user, threadTs, MESSAGES.othersThread)
        return
      }
      if (this.busyUsers.has(user)) {
        await this.slack.ephemeral(channel, user, threadTs, MESSAGES.busy)
        return
      }
      this.busyUsers.add(user)
      try {
        await this.withToken(user, async (token) => {
          if (!this.watchers.has(user)) this.watchers.set(user, null)
          let conv = this.threads.get(key)
          if (!conv) {
            conv = { conversationId: await this.gateway.createConversation(token), slackUserId: user, at: this.now() }
            this.threads.set(key, conv)
          }
          conv.at = this.now()
          const conversationId = conv.conversationId
          await this.relay(user, channel, threadTs, () => this.gateway.send(token, conversationId, content))
        }, async () => this.slack.post(channel, threadTs, text(MESSAGES.unmapped)).then(() => undefined))
      } catch (e) {
        await this.fail(channel, threadTs, e)
      } finally {
        this.busyUsers.delete(user)
      }
    } catch (e) {
      this.log('message handling failed', e)
    }
  }

  /** 실행·취소 버튼. 요청자 본인이 아니면 안내만 합니다. */
  async onDecision(user: string, approvalId: string, decision: 'approve' | 'reject', channel?: string): Promise<void> {
    try {
      const card = this.approvals.get(approvalId)
      if (!card) {
        if (channel) await this.slack.ephemeral(channel, user, undefined, MESSAGES.staleCard)
        return
      }
      if (card.slackUserId !== user) {
        await this.slack.ephemeral(card.channel, user, card.threadTs, MESSAGES.onlyRequester)
        return
      }
      // 두 번 눌러도 한 번만 보내도록 먼저 지우고, 결과를 받기 전에는 "처리하는 중"으로 둡니다.
      this.approvals.delete(approvalId)
      await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName, 'pending'))
      let decided = false
      try {
        await this.withToken(user, async (token) => {
          const events = await this.relay(user, card.channel, card.threadTs, () => this.gateway.decide(token, approvalId, decision))
          decided = events.some((e) => e.type === 'approval_decided')
        })
      } catch (e) {
        await this.fail(card.channel, card.threadTs, e)
        if (e instanceof GatewayError && e.status >= 400 && e.status < 500) {
          await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName, 'failed'))
          return
        }
      }
      if (decided) {
        await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName, decision === 'approve' ? 'approved' : 'rejected'))
      } else {
        // 결정이 확인되지 않았으면(5xx·끊김·오류 이벤트) 버튼을 되살려 다시 누를 수 있게 합니다.
        this.approvals.set(approvalId, card)
        await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName))
      }
    } catch (e) {
      this.log('decision handling failed', e)
    }
  }

  async onUndo(user: string, actionId: string, channel?: string): Promise<void> {
    try {
      const card = this.actions.get(actionId)
      if (!card) {
        if (channel) await this.slack.ephemeral(channel, user, undefined, MESSAGES.staleCard)
        return
      }
      if (card.slackUserId !== user) {
        await this.slack.ephemeral(card.channel, user, card.threadTs, MESSAGES.onlyRequester)
        return
      }
      this.actions.delete(actionId)
      try {
        await this.withToken(user, async (token) => {
          // 같은 행동의 되돌리기는 같은 키로 보내 다시 눌러도 한 번만 되돌립니다.
          await this.gateway.undo(token, actionId, `slack-undo-${actionId}`)
        })
        await this.slack.update(card.channel, card.ts, actionCard(card.item, 'undone'))
      } catch (e) {
        this.log('undo failed', e)
        const message = e instanceof GatewayError ? e.message : MESSAGES.failed
        await this.slack.update(card.channel, card.ts, actionCard(card.item, { failed: message }))
      }
    } catch (e) {
      this.log('undo handling failed', e)
    }
  }

  /**
   * 브리지에 말을 건 직원의 erp 알림 중 새로 생긴 읽지 않은 것을 DM으로 보냅니다. 처음 볼 때 이미 있던 알림은 보내지 않습니다.
   * 브리지를 다시 시작하면 그 사이 알림은 보내지 않습니다(직원이 다시 말을 건 뒤부터). 앞 조회가 끝나지 않았으면 건너뜁니다.
   */
  async pollNotifications(): Promise<void> {
    if (this.polling) return
    this.polling = true
    try {
      for (const [user, seen] of this.watchers) {
        try {
          await this.withToken(user, async (token) => {
            const items = await this.gateway.notifications(token)
            const next = new Set<string>()
            for (const n of items) {
              if (seen && !seen.has(n.id) && !n.read) {
                try {
                  const dm = await this.slack.openDm(user)
                  await this.slack.post(dm, undefined, notificationMessage(n, this.webUrl))
                } catch (e) {
                  // 보내지 못한 알림은 다음 조회 때 다시 시도합니다.
                  this.log('notification dm failed', e)
                  continue
                }
              }
              next.add(n.id)
            }
            // 지금 목록에 있는 ID만 남겨 크기가 늘지 않게 합니다.
            this.watchers.set(user, next)
          })
        } catch (e) {
          this.log('notifications failed', e)
        }
      }
    } finally {
      this.polling = false
    }
  }

  /** 스트림을 끝까지 받아 답·카드를 스레드에 올리고, 받은 이벤트를 돌려줍니다. */
  private async relay(user: string, channel: string, threadTs: string, open: () => AsyncGenerator<ChatEvent>): Promise<ChatEvent[]> {
    const events: ChatEvent[] = []
    for await (const e of open()) events.push(e)
    const turn = collect(events)
    if (turn.reply) await this.slack.post(channel, threadTs, turn.reply)
    for (const a of turn.actions) {
      const ts = await this.slack.post(channel, threadTs, actionCard(a))
      if (a.undoable) this.actions.set(a.actionId, { slackUserId: user, channel, threadTs, ts, item: a, at: this.now() })
    }
    for (const a of turn.approvals) {
      const ts = await this.slack.post(channel, threadTs, approvalCard(a, turn.agentName))
      this.approvals.set(a.approvalId, { slackUserId: user, channel, threadTs, ts, item: a, agentName: turn.agentName, at: this.now() })
    }
    if (!turn.reply && !turn.actions.length && !turn.approvals.length && !events.some((e) => e.type === 'approval_decided')) {
      await this.slack.post(channel, threadTs, text('답이 비어 있습니다.'))
    }
    return events
  }

  private async fail(channel: string, threadTs: string, e: unknown): Promise<void> {
    this.log('request failed', e)
    // GatewayError.message는 슬랙에 보여도 되는 문구입니다(5xx·연결 실패는 고정 문구).
    await this.slack.post(channel, threadTs, text(e instanceof GatewayError ? e.message : MESSAGES.failed))
  }

  /**
   * 직원 토큰으로 fn을 부릅니다. 토큰은 만료 1분 전까지 다시 쓰고, 401이면 한 번 다시 로그인해 다시 부릅니다.
   * 매핑이 없으면 unmapped를 부릅니다(없으면 오류).
   */
  private async withToken(user: string, fn: (token: string) => Promise<void>, unmapped?: () => Promise<void>): Promise<void> {
    for (let attempt = 0; ; attempt++) {
      const token = await this.token(user)
      if (!token) {
        if (unmapped) return unmapped()
        throw new GatewayError(MESSAGES.unmapped, 403)
      }
      try {
        return await fn(token)
      } catch (e) {
        if (attempt === 0 && e instanceof GatewayError && e.status === 401) {
          this.tokens.delete(user)
          continue
        }
        throw e
      }
    }
  }

  private async token(slackUserId: string): Promise<string | null> {
    const cached = this.tokens.get(slackUserId)
    if (cached && cached.exp > this.now()) return cached.token
    const res = await this.login(slackUserId)
    if (!res) {
      this.tokens.set(slackUserId, { token: null, exp: this.now() + UNMAPPED_MS })
      return null
    }
    const exp = jwtExp(res.token) ?? this.now() + res.expiresIn * 1000
    this.tokens.set(slackUserId, { token: res.token, exp: Math.min(exp - 60_000, this.now() + TOKEN_REUSE_MS) })
    return res.token
  }

  /** /auth/slack이 429면 Retry-After만큼(최대 30초) 기다렸다 한 번 다시 부릅니다. 그래도 막히면 429 오류(안내 문구)를 던집니다. */
  private async login(slackUserId: string) {
    try {
      return await this.gateway.login(slackUserId)
    } catch (e) {
      if (!(e instanceof GatewayError) || e.status !== 429) throw e
      const wait = e.retryAfter ?? 1
      if (wait > MAX_RETRY_WAIT_S) throw e
      await this.sleep(wait * 1000)
      return this.gateway.login(slackUserId)
    }
  }

  /** 맨 앞의 봇 멘션 하나만 지웁니다. 질문 안의 다른 사람 멘션은 둡니다. */
  private stripMention(raw: string): string {
    const lead = /^\s*<@([A-Z0-9]+)(?:\|[^>]*)?>\s*/.exec(raw)
    if (lead && (!this.botUserId || lead[1] === this.botUserId)) return raw.slice(lead[0].length).trim()
    return raw.trim()
  }

  /** 오래된 상태를 지웁니다. 실행 승인은 만료 시각이 지나면 지웁니다. */
  private prune(): void {
    const now = this.now()
    for (const [k, v] of this.threads) if (now - v.at > KEEP_MS) this.threads.delete(k)
    for (const [k, v] of this.actions) if (now - v.at > KEEP_MS) this.actions.delete(k)
    for (const [k, v] of this.approvals) {
      const exp = v.item.expiresAt ? Date.parse(v.item.expiresAt) : v.at + KEEP_MS
      if (now > exp) this.approvals.delete(k)
    }
    for (const [k, at] of this.seenEvents) if (now - at > DEDUPE_MS) this.seenEvents.delete(k)
    for (const [k, v] of this.tokens) if (v.exp <= now) this.tokens.delete(k)
  }
}

/** JWT의 exp(초)를 밀리초로. 서명은 gateway가 검증하므로 여기서는 읽기만 합니다. */
export function jwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1] ?? '', 'base64url').toString('utf8')) as { exp?: number }
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

/**
 * 슬랙 메시지 글(mrkdwn)을 모델에 넘길 일반 글로 바꿉니다. 사용자가 굵게·기울임·취소선을 쓰거나 링크를 붙이면
 * 슬랙은 `*굵게*`, 백틱 코드, `<https://x|이름>`, `&amp;`처럼 보냅니다. 그대로 넘기면 모델이 기호를 값에 섞습니다
 * (예: 날짜 `*2026-11-20`이 도구 입력 검증에서 거절됨).
 */
export function toPlainText(text: string): string {
  return (
    text
      // 링크: <url|이름> → 이름(url), <url> → url, <mailto:a|a> → a
      .replace(/<mailto:([^|>]+)(?:\|[^>]*)?>/g, '$1')
      .replace(/<((?:https?|ftp):[^|>]+)\|([^>]+)>/g, '$2($1)')
      .replace(/<((?:https?|ftp):[^>]+)>/g, '$1')
      // 코드 서식: ```여러 줄``` 과 `한 줄`의 백틱만 지웁니다
      .replace(/```([\s\S]*?)```/g, '$1')
      .replace(/`([^`\n]+)`/g, '$1')
      // 굵게·기울임·취소선: 단어 경계에 붙은 짝 기호만 지웁니다(곱셈 3*4 같은 글은 두기)
      .replace(/(^|[\s(])\*(?!\s)([^*\n]+?)(?<!\s)\*(?=$|[\s).,!?:;])/g, '$1$2')
      .replace(/(^|[\s(])_(?!\s)([^_\n]+?)(?<!\s)_(?=$|[\s).,!?:;])/g, '$1$2')
      .replace(/(^|[\s(])~(?!\s)([^~\n]+?)(?<!\s)~(?=$|[\s).,!?:;])/g, '$1$2')
      // 슬랙이 바꿔 보낸 제어 문자를 되돌립니다(&amp;는 마지막에)
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&')
      .trim()
  )
}
