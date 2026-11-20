import bolt from '@slack/bolt'
import type { Bridge, Incoming, Slack } from './bridge.js'
import { ACTION } from './render.js'

const { App, LogLevel } = bolt

/** Bolt 앱(Socket Mode)을 만들고 브리지에 잇습니다. 브리지는 slack 포트로 메시지를 올립니다. */
export function createApp(appToken: string, botToken: string) {
  return new App({ token: botToken, appToken, socketMode: true, logLevel: LogLevel.INFO })
}

export function slackPort(app: ReturnType<typeof createApp>): Slack {
  const c = app.client
  return {
    async post(channel, threadTs, msg) {
      const res = await c.chat.postMessage({ channel, ...(threadTs ? { thread_ts: threadTs } : {}), text: msg.text, blocks: msg.blocks as never })
      return res.ts ?? ''
    },
    async update(channel, ts, msg) {
      await c.chat.update({ channel, ts, text: msg.text, blocks: msg.blocks as never })
    },
    async ephemeral(channel, user, threadTs, text) {
      await c.chat.postEphemeral({ channel, user, text, ...(threadTs ? { thread_ts: threadTs } : {}) })
    },
    async openDm(user) {
      const open = await c.conversations.open({ users: user })
      if (!open.channel?.id) throw new Error('DM 채널을 열지 못했습니다.')
      return open.channel.id
    },
  }
}

/**
 * DM(message.im)과 채널 멘션(app_mention)을 브리지로 넘깁니다.
 * 채널의 일반 메시지는 멘션이 없으면 받지 않습니다(DM만 message로 받음). 멘션 이벤트에는 channel_type이 없어 채널로 봅니다.
 */
export function wire(app: ReturnType<typeof createApp>, bridge: Bridge) {
  app.message(async ({ message }) => {
    const m = message as Incoming & { channel_type?: string }
    if (m.channel_type !== 'im') return
    await bridge.onMessage(m)
  })
  app.event('app_mention', async ({ event }) => {
    const e = event as unknown as Incoming
    await bridge.onMessage({ ...e, channel_type: 'channel' })
  })
  for (const [id, decision] of [
    [ACTION.approve, 'approve'],
    [ACTION.reject, 'reject'],
  ] as const) {
    app.action(id, async ({ ack, body, action }) => {
      await ack()
      const b = body as { user: { id: string }; channel?: { id: string } }
      await bridge.onDecision(b.user.id, (action as { value: string }).value, decision, b.channel?.id)
    })
  }
  app.action(ACTION.undo, async ({ ack, body, action }) => {
    await ack()
    const b = body as { user: { id: string }; channel?: { id: string } }
    await bridge.onUndo(b.user.id, (action as { value: string }).value, b.channel?.id)
  })
}
