import type { ChatEvent, Schemas } from './gateway.js'

/** 슬랙 메시지 하나(chat.postMessage의 text·blocks). text는 알림과 블록을 못 그리는 곳에 쓰입니다. */
export type SlackMessage = { text: string; blocks: Block[] }
// Block Kit은 형식이 넓어 여기서 쓰는 모양만 느슨하게 둡니다.
export type Block = Record<string, unknown>

export const ACTION = { approve: 'approval_approve', reject: 'approval_reject', undo: 'action_undo' } as const

type Approval = NonNullable<ChatEvent['approval']>
type Action = NonNullable<ChatEvent['action']>
type Citation = NonNullable<ChatEvent['citations']>[number]
type Risk = Approval['risk']

const RISK: Record<Risk, string> = { read: '조회', reversible_write: '되돌릴 수 있음', irreversible: '되돌릴 수 없음' }

/** 슬랙 mrkdwn의 제어 문자(&, <, >)를 바꿉니다. 사용자·모델 글이 링크나 멘션으로 읽히지 않게 합니다. */
export function escape(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 모델 답의 마크다운 굵게(**x**)를 슬랙 굵게(*x*)로 바꿉니다. 나머지는 그대로 둡니다. */
export function toMrkdwn(text: string): string {
  return escape(text).replace(/\*\*(.+?)\*\*/g, '*$1*')
}

/** 슬랙 section 글 한도(3000자)보다 조금 작게 나눕니다. */
const SECTION_MAX = 2900
/** 슬랙 메시지 블록 한도(50개) */
const BLOCKS_MAX = 50

// verbatim: 모델·사용자 글 속 맨 URL이나 채널 이름이 저절로 링크가 되지 않게 합니다.
const section = (text: string): Block => ({ type: 'section', text: { type: 'mrkdwn', text, verbatim: true } })

/** 긴 글을 여러 section으로 나눕니다. 가능하면 줄바꿈에서 자릅니다. */
function sections(text: string): Block[] {
  const out: Block[] = []
  let rest = text
  while (rest.length > SECTION_MAX) {
    const cut = rest.lastIndexOf('\n', SECTION_MAX)
    const at = cut > SECTION_MAX / 2 ? cut : SECTION_MAX
    out.push(section(rest.slice(0, at)))
    rest = rest.slice(at).replace(/^\n/, '')
  }
  if (rest) out.push(section(rest))
  return out
}

/** 블록이 한도를 넘으면 뒤를 자르고 잘렸다고 밝힙니다. */
function limit(blocks: Block[]): Block[] {
  if (blocks.length <= BLOCKS_MAX) return blocks
  return [...blocks.slice(0, BLOCKS_MAX - 1), context('답이 길어 뒷부분을 줄였습니다. 웹 화면에서 전체를 볼 수 있습니다.')]
}
const context = (...texts: string[]): Block => ({ type: 'context', elements: texts.map((t) => ({ type: 'mrkdwn', text: t })) })
const button = (text: string, action_id: string, value: string, style?: 'primary' | 'danger'): Block => ({
  type: 'button',
  text: { type: 'plain_text', text },
  action_id,
  value,
  ...(style ? { style } : {}),
})

/** 한 차례(메시지 하나 또는 실행 결정 하나)의 이벤트를 모아 슬랙 메시지들로 바꿉니다. 카드는 따로 올려 나중에 고칩니다. */
export type Turn = {
  agentName?: string
  /** 답 본문, 근거, 차단·오류를 담은 메시지. 보일 것이 없으면 null */
  reply: SlackMessage | null
  approvals: Approval[]
  actions: Action[]
}

export function collect(events: ChatEvent[]): Turn {
  let agentName: string | undefined
  const texts: string[] = []
  let citations: Citation[] = []
  const notes: string[] = []
  let local = false
  const approvals: Approval[] = []
  const actions: Action[] = []
  for (const e of events) {
    if (e.type === 'route' && e.route?.agentName) agentName = e.route.agentName
    else if (e.type === 'message' && e.text) texts.push(e.text)
    else if (e.type === 'citations' && e.citations) citations = e.citations
    else if (e.type === 'blocked' && e.blocked) notes.push(`*차단* ${escape(e.blocked.reason ?? '정책에 따라 막았습니다.')}`)
    else if (e.type === 'error' && e.error) notes.push(`*오류* ${escape(e.error.message ?? '처리하지 못했습니다.')}`)
    else if (e.type === 'approval_required' && e.approval) approvals.push(e.approval)
    else if (e.type === 'action' && e.action) actions.push(e.action)
    if ((e.type === 'message' || e.type === 'done') && e.model?.location === 'local') local = true
  }
  const blocks: Block[] = []
  for (const t of texts) blocks.push(...sections(toMrkdwn(t)))
  for (const n of notes) blocks.push(...sections(n))
  if (citations.length) blocks.push(...sections(citations.map(citationLine).join('\n')))
  const meta = [agentName && escape(agentName), local && '로컬에서 처리'].filter(Boolean) as string[]
  if (blocks.length && meta.length) blocks.push(context(meta.join(' · ')))
  // 대체 text도 슬랙이 멘션·링크로 읽으므로 escape한 글만 둡니다.
  const plain = [...texts.map(escape), ...notes.map((n) => n.replace(/\*/g, ''))].join('\n')
  return { agentName, reply: blocks.length ? { text: plain.slice(0, 3000) || '답을 받았습니다.', blocks: limit(blocks) } : null, approvals, actions }
}

function citationLine(c: Citation): string {
  const head = `*${escape(c.title ?? c.docId ?? '문서')}* ${escape(c.article ?? '')}${c.verified === false ? ' _(인용 확인 안 됨)_' : ''}`
  const quote = c.quote ? `\n> ${escape(c.quote).replace(/\n/g, '\n> ')}` : ''
  return `${head}${quote}`
}

function value(v: unknown): string {
  if (v === null || v === undefined) return '–'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 실행 미리보기 카드. state가 있으면 버튼 대신 결정 결과를 보여 줍니다. */
export function approvalCard(a: Approval, agentName: string | undefined, state?: 'pending' | 'approved' | 'rejected' | 'failed'): SlackMessage {
  const p = a.preview ?? ({} as NonNullable<Approval['preview']>)
  const title = `실행 미리보기: ${escape(a.toolLabel ?? a.tool)}`
  const blocks: Block[] = [section(`*${title}*  \`${RISK[a.risk]}\`${agentName ? `  ${escape(agentName)}` : ''}`)]
  if (p.summary) blocks.push(section(escape(p.summary)))
  const lines: string[] = []
  for (const c of p.changes ?? []) {
    const before = (c.before ?? {}) as Record<string, unknown>
    const after = (c.after ?? {}) as Record<string, unknown>
    for (const k of new Set([...Object.keys(before), ...Object.keys(after)])) {
      const b = k in before ? value(before[k]) : null
      const n = k in after ? value(after[k]) : null
      lines.push(b !== null && n !== null && b !== n ? `\`${escape(k)}\` ~${escape(b)}~ → ${escape(n)}` : `\`${escape(k)}\` ${escape(n ?? b ?? '–')}`)
    }
  }
  if (lines.length) blocks.push(...sections(lines.join('\n')))
  if (p.undoable === false) blocks.push(context('실행하면 되돌릴 수 없습니다.'))
  if (state) {
    const label = { pending: '처리하는 중', approved: '실행함', rejected: '취소함', failed: '더 결정할 수 없음' }[state]
    blocks.push(context(label))
  } else {
    blocks.push({
      type: 'actions',
      elements: [
        button('실행', ACTION.approve, a.approvalId, a.risk === 'irreversible' ? 'danger' : 'primary'),
        button('취소', ACTION.reject, a.approvalId),
      ],
    })
    blocks.push(context(`요청한 사람만 누를 수 있습니다. 만료 ${time(a.expiresAt)}`))
  }
  return { text: `${title}: ${escape(p.summary ?? '')}`, blocks: limit(blocks) }
}

/** 실행한 일 카드. undoable이면 되돌리기 버튼을 둡니다. */
export function actionCard(a: Action, state?: 'undone' | { failed: string }): SlackMessage {
  const blocks: Block[] = [section(`*실행한 일*  ${escape(a.summary)}`)]
  if (state === 'undone') blocks.push(context('되돌림'))
  else if (state) blocks.push(context(`되돌리지 못했습니다: ${escape(state.failed)}`))
  else if (a.undoable) blocks.push({ type: 'actions', elements: [button('되돌리기', ACTION.undo, a.actionId)] })
  return { text: `실행한 일: ${escape(a.summary)}`, blocks }
}

const KST = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
function time(iso: string | undefined): string {
  if (!iso) return '–'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '–' : KST.format(d)
}

export function text(t: string): SlackMessage {
  return { text: escape(t), blocks: [section(escape(t))] }
}

/** 팀장 결재 알림. 승인·반려는 사람 전용 기능이라 web 승인함 링크만 둡니다. */
export function notificationMessage(n: Schemas['Notification'], webUrl: string): SlackMessage {
  const link = `${webUrl.replace(/\/$/, '')}/inbox`
  return {
    text: escape(n.message),
    blocks: [section(escape(n.message)), context(`승인·반려는 <${link}|웹 승인함>에서 합니다.`)],
  }
}
