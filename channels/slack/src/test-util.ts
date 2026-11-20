import type { Slack } from './bridge.js'
import type { ChatEvent, Gateway, Schemas } from './gateway.js'
import type { SlackMessage } from './render.js'

type Draft = Omit<ChatEvent, 'conversationId' | 'seq' | 'at'>
export const ev = (drafts: Draft[]): ChatEvent[] => drafts.map((d, seq) => ({ ...d, conversationId: 'c1', seq, at: '2026-11-21T00:00:00Z' }) as ChatEvent)

export function fakeGateway(over: Partial<Gateway> = {}) {
  const calls: string[] = []
  const gw: Gateway = {
    async login(u) {
      calls.push(`login ${u}`)
      return u === 'U_UNMAPPED' ? null : { token: `tok-${u}`, expiresIn: 600 }
    },
    async createConversation(t) {
      calls.push(`create ${t}`)
      return `conv-${calls.length}`
    },
    async *send(t, c, content) {
      calls.push(`send ${t} ${c} ${content}`)
      yield* ev([{ type: 'route', route: { agentId: 'assistant', agentName: '전사 비서', method: 'llm', reason: '' } }, { type: 'message', text: '답입니다.' }, { type: 'done' }])
    },
    async *decide(t, id, d) {
      calls.push(`decide ${t} ${id} ${d}`)
      yield* ev([{ type: 'approval_decided', decision: { approvalId: id, decision: d } }, { type: 'done' }])
    },
    async undo(t, id, key) {
      calls.push(`undo ${t} ${id} ${key}`)
      return { actionId: 'u1', operation: 'undoAction', summary: '되돌림', changes: [], undoable: false, resource: {}, undoOf: id } as Schemas['ActionResult']
    },
    async notifications(t) {
      calls.push(`notifications ${t}`)
      return []
    },
    ...over,
  }
  return { gw, calls }
}

export function fakeSlack() {
  const posts: { channel: string; threadTs: string | undefined; msg: SlackMessage; ts: string }[] = []
  const updates: { channel: string; ts: string; msg: SlackMessage }[] = []
  const ephemerals: { channel: string; user: string; text: string }[] = []
  const opened: string[] = []
  const slack: Slack = {
    async post(channel, threadTs, msg) {
      const ts = `ts-${posts.length + 1}`
      posts.push({ channel, threadTs, msg, ts })
      return ts
    },
    async update(channel, ts, msg) {
      updates.push({ channel, ts, msg })
    },
    async ephemeral(channel, user, _threadTs, text) {
      ephemerals.push({ channel, user, text })
    },
    async openDm(user) {
      opened.push(user)
      return `D-${user}`
    },
  }
  /** DM 채널(D-<user>)에 올린 것 */
  const dms = () => posts.filter((p) => p.channel.startsWith('D-'))
  return { slack, posts, updates, ephemerals, dms, opened }
}

/** 블록 안의 글을 모두 이어 붙입니다(시험에서 내용 확인용). */
export const flat = (m: SlackMessage) => JSON.stringify(m.blocks)
