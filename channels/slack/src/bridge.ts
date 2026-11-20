import { GatewayError, type ChatEvent, type Gateway } from './gateway.js'
import { actionCard, approvalCard, collect, notificationMessage, text, type SlackMessage } from './render.js'

/** 브리지가 슬랙에 바라는 것. Bolt 클라이언트를 감싼 것이고, 시험에서는 가짜로 바꿉니다. */
export interface Slack {
  /** 채널(또는 DM)의 스레드에 올리고 메시지 ts를 돌려줍니다. */
  post(channel: string, threadTs: string, msg: SlackMessage): Promise<string>
  update(channel: string, ts: string, msg: SlackMessage): Promise<void>
  /** 한 사람에게만 보이는 안내(누를 권한이 없을 때 등) */
  ephemeral(channel: string, user: string, threadTs: string | undefined, text: string): Promise<void>
  /** 직원에게 DM을 보냅니다. */
  dm(user: string, msg: SlackMessage): Promise<void>
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
}

type Conversation = { conversationId: string; slackUserId: string }
type Card<T> = { slackUserId: string; channel: string; threadTs: string; ts: string; item: T; agentName?: string }
type Approval = NonNullable<ChatEvent['approval']>
type Action = NonNullable<ChatEvent['action']>

export const MESSAGES = {
  unmapped: '이 슬랙 계정과 연결된 직원 계정이 없습니다. 관리자에게 슬랙 사용자 연결을 요청해 주세요.',
  othersThread: '이 스레드는 다른 사람의 대화입니다. 새 메시지로 시작해 주세요.',
  busy: '앞 메시지를 처리하는 중입니다. 답이 온 뒤에 보내 주세요.',
  onlyRequester: '실행을 요청한 사람만 누를 수 있습니다.',
  empty: '무엇을 도와드릴까요? 회의실 예약, 연차 규정처럼 물어보면 맞는 부서 에이전트가 답합니다.',
} as const

type Options = {
  gateway: Gateway
  slack: Slack
  webUrl: string
  now?: () => number
  log?: (msg: string, err?: unknown) => void
}

/**
 * 슬랙과 gateway를 잇습니다. 같은 스레드는 같은 gateway 대화로, 스레드를 시작한 사람만 그 대화를 이어 갑니다.
 * 상태(스레드↔대화, 카드)는 메모리에만 둡니다. 다시 시작하면 새 스레드로 시작합니다.
 */
export class Bridge {
  private readonly gateway: Gateway
  private readonly slack: Slack
  private readonly webUrl: string
  private readonly now: () => number
  private readonly log: (msg: string, err?: unknown) => void
  private readonly threads = new Map<string, Conversation>()
  private readonly busy = new Set<string>()
  private readonly tokens = new Map<string, { token: string; exp: number }>()
  private readonly approvals = new Map<string, Card<Approval>>()
  private readonly actions = new Map<string, Card<Action>>()
  /** 알림을 받을 사람(브리지에 말을 건 직원)과 이미 보낸 알림 ID */
  private readonly watchers = new Map<string, Set<string> | null>()

  constructor(o: Options) {
    this.gateway = o.gateway
    this.slack = o.slack
    this.webUrl = o.webUrl
    this.now = o.now ?? Date.now
    this.log = o.log ?? (() => undefined)
  }

  /** DM이나 멘션 하나를 처리합니다. 봇 메시지·편집·삭제 같은 하위 형식은 무시합니다. */
  async onMessage(m: Incoming): Promise<void> {
    if (m.bot_id || m.subtype || !m.user) return
    const threadTs = m.thread_ts ?? m.ts
    const key = `${m.channel}:${threadTs}`
    const content = (m.text ?? '').replace(/<@[A-Z0-9]+>/g, '').trim()
    if (!content) {
      await this.slack.post(m.channel, threadTs, text(MESSAGES.empty))
      return
    }
    const known = this.threads.get(key)
    if (known && known.slackUserId !== m.user) {
      await this.slack.ephemeral(m.channel, m.user, threadTs, MESSAGES.othersThread)
      return
    }
    if (this.busy.has(key)) {
      await this.slack.ephemeral(m.channel, m.user, threadTs, MESSAGES.busy)
      return
    }
    this.busy.add(key)
    try {
      const token = await this.token(m.user)
      if (!token) {
        await this.slack.post(m.channel, threadTs, text(MESSAGES.unmapped))
        return
      }
      if (!this.watchers.has(m.user)) this.watchers.set(m.user, null)
      let conv = known
      if (!conv) {
        conv = { conversationId: await this.gateway.createConversation(token), slackUserId: m.user }
        this.threads.set(key, conv)
      }
      const conversationId = conv.conversationId
      await this.relay(m.user, m.channel, threadTs, () => this.gateway.send(token, conversationId, content))
    } catch (e) {
      await this.fail(m.channel, threadTs, e)
    } finally {
      this.busy.delete(key)
    }
  }

  /** 실행·취소 버튼. 요청자 본인이 아니면 안내만 합니다. */
  async onDecision(user: string, approvalId: string, decision: 'approve' | 'reject', channel: string): Promise<void> {
    const card = this.approvals.get(approvalId)
    if (!card) {
      await this.slack.ephemeral(channel, user, undefined, '이 카드는 더 결정할 수 없습니다(브리지가 다시 시작됐거나 이미 결정함).')
      return
    }
    if (card.slackUserId !== user) {
      await this.slack.ephemeral(card.channel, user, card.threadTs, MESSAGES.onlyRequester)
      return
    }
    // 두 번 눌러도 한 번만 보냅니다.
    this.approvals.delete(approvalId)
    await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName, decision === 'approve' ? 'approved' : 'rejected'))
    try {
      const token = await this.token(user)
      if (!token) throw new GatewayError(MESSAGES.unmapped, 403)
      await this.relay(user, card.channel, card.threadTs, () => this.gateway.decide(token, approvalId, decision))
    } catch (e) {
      if (e instanceof GatewayError && e.status >= 400 && e.status < 500) {
        await this.slack.update(card.channel, card.ts, approvalCard(card.item, card.agentName, 'failed'))
      }
      await this.fail(card.channel, card.threadTs, e)
    }
  }

  async onUndo(user: string, actionId: string, channel: string): Promise<void> {
    const card = this.actions.get(actionId)
    if (!card) {
      await this.slack.ephemeral(channel, user, undefined, '이 행동은 더 되돌릴 수 없습니다(브리지가 다시 시작됐거나 이미 되돌림).')
      return
    }
    if (card.slackUserId !== user) {
      await this.slack.ephemeral(card.channel, user, card.threadTs, MESSAGES.onlyRequester)
      return
    }
    this.actions.delete(actionId)
    try {
      const token = await this.token(user)
      if (!token) throw new GatewayError(MESSAGES.unmapped, 403)
      // 같은 행동의 되돌리기는 같은 키로 보내 다시 눌러도 한 번만 되돌립니다.
      await this.gateway.undo(token, actionId, `slack-undo-${actionId}`)
      await this.slack.update(card.channel, card.ts, actionCard(card.item, 'undone'))
    } catch (e) {
      const message = e instanceof GatewayError ? e.message : '되돌리지 못했습니다.'
      await this.slack.update(card.channel, card.ts, actionCard(card.item, { failed: message }))
      this.log('undo failed', e)
    }
  }

  /**
   * 브리지에 말을 건 직원의 결재 알림을 DM으로 보냅니다. 처음 볼 때 이미 있던 알림은 보내지 않습니다.
   * 주기적으로 부릅니다(main.ts).
   */
  async pollNotifications(): Promise<void> {
    for (const [user, seen] of this.watchers) {
      try {
        const token = await this.token(user)
        if (!token) continue
        const items = await this.gateway.notifications(token)
        if (seen === null) {
          this.watchers.set(user, new Set(items.map((n) => n.id)))
          continue
        }
        for (const n of items) {
          if (seen.has(n.id)) continue
          seen.add(n.id)
          if (!n.read) await this.slack.dm(user, notificationMessage(n, this.webUrl))
        }
      } catch (e) {
        this.log(`notifications failed for ${user}`, e)
      }
    }
  }

  /** 스트림을 끝까지 받아 답·카드를 스레드에 올립니다. */
  private async relay(user: string, channel: string, threadTs: string, open: () => AsyncGenerator<ChatEvent>): Promise<void> {
    const events: ChatEvent[] = []
    for await (const e of open()) events.push(e)
    const turn = collect(events)
    if (turn.reply) await this.slack.post(channel, threadTs, turn.reply)
    for (const a of turn.actions) {
      const ts = await this.slack.post(channel, threadTs, actionCard(a))
      if (a.undoable) this.actions.set(a.actionId, { slackUserId: user, channel, threadTs, ts, item: a })
    }
    for (const a of turn.approvals) {
      const ts = await this.slack.post(channel, threadTs, approvalCard(a, turn.agentName))
      this.approvals.set(a.approvalId, { slackUserId: user, channel, threadTs, ts, item: a, agentName: turn.agentName })
    }
    if (!turn.reply && !turn.actions.length && !turn.approvals.length) await this.slack.post(channel, threadTs, text('답이 비어 있습니다.'))
  }

  private async fail(channel: string, threadTs: string, e: unknown): Promise<void> {
    this.log('request failed', e)
    const message = e instanceof GatewayError ? e.message : '처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
    await this.slack.post(channel, threadTs, text(message))
  }

  /** 직원 토큰을 만료 1분 전까지 다시 씁니다. 매핑이 없으면 null */
  private async token(slackUserId: string): Promise<string | null> {
    const cached = this.tokens.get(slackUserId)
    if (cached && cached.exp - 60_000 > this.now()) return cached.token
    const token = await this.gateway.login(slackUserId)
    if (!token) {
      this.tokens.delete(slackUserId)
      return null
    }
    this.tokens.set(slackUserId, { token, exp: jwtExp(token) ?? this.now() + 5 * 60_000 })
    return token
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
