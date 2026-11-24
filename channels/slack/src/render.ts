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

// 문구는 ux/copy-guide.md 용어집과 web 화면을 따릅니다(#579, ux/copy-audit/slack-agent.md 1절)
const RISK: Record<Risk, string> = { read: '조회', reversible_write: '실행 취소 가능', irreversible: '실행 취소 불가' }

/** 슬랙 mrkdwn의 제어 문자(&, <, >)를 바꿉니다. 사용자·모델 글이 링크나 멘션으로 읽히지 않게 합니다. */
export function escape(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 모델 답의 마크다운 굵게(**x**)를 슬랙 굵게(*x*)로 바꿉니다. 나머지는 그대로 둡니다. */
export function toMrkdwn(text: string): string {
  // 슬랙은 굵게 기호 바로 앞뒤에 글자가 붙으면(예: '*회의실 A*를') 굵게로 그리지 않고 별표를 그대로 보입니다.
  // 앞뒤에 폭 없는 공백(U+200B)을 넣어 단어 경계를 만듭니다.
  return escape(text).replace(/\*\*(.+?)\*\*/g, '\u200b*$1*\u200b')
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
    else if (e.type === 'blocked' && e.blocked) notes.push(`*처리할 수 없는 요청* ${escape(e.blocked.reason ?? '회사 정책상 처리할 수 없는 요청입니다. 담당 부서에 문의하세요.')}`)
    else if (e.type === 'error' && e.error) notes.push(`*오류* ${escape(e.error.message ?? '처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.')}`)
    else if (e.type === 'approval_required' && e.approval) approvals.push(e.approval)
    else if (e.type === 'action' && e.action) actions.push(e.action)
    if ((e.type === 'message' || e.type === 'done') && e.model?.location === 'local') local = true
  }
  const blocks: Block[] = []
  for (const t of texts) blocks.push(...sections(toMrkdwn(t)))
  for (const n of notes) blocks.push(...sections(n))
  if (citations.length) blocks.push(...sections(citations.map(citationLine).join('\n')))
  const meta = [agentName && escape(agentName), local && '사내 처리'].filter(Boolean) as string[]
  if (blocks.length && meta.length) blocks.push(context(meta.join(' · ')))
  // 대체 text도 슬랙이 멘션·링크로 읽으므로 escape한 글만 둡니다.
  const plain = [...texts.map(escape), ...notes.map((n) => n.replace(/\*/g, ''))].join('\n')
  return { agentName, reply: blocks.length ? { text: plain.slice(0, 3000) || '답을 받았습니다.', blocks: limit(blocks) } : null, approvals, actions }
}

function citationLine(c: Citation): string {
  const head = `*${escape(c.title ?? c.docId ?? '문서')}* ${escape(c.article ?? '')}${c.verified === false ? '  `원문 대조 안 됨`' : ''}`
  const quote = c.quote ? `\n> ${escape(c.quote).replace(/\n/g, '\n> ')}` : ''
  return `${head}${quote}`
}

/** 긴 값(JSON 등)은 카드에서 줄입니다. */
const short = (v: string, max = 80) => (v.length > max ? `${v.slice(0, max - 1)}…` : v)

/**
 * 필드 표시 이름. web의 display/names.ts FIELD_LABELS에서 슬랙 카드에 자주 나오는 것만 옮겼습니다(계약에 표시 이름이 없음).
 * 모르는 필드는 코드 이름 그대로 둡니다.
 */
const FIELD: Record<string, string> = {
  title: '제목',
  amount: '금액',
  totalAmount: '합계',
  total_amount: '합계',
  reason: '사유',
  startsAt: '시작',
  endsAt: '끝',
  startDate: '시작일',
  endDate: '종료일',
  roomId: '회의실',
  attendees: '참석 인원',
  delegateId: '대결자',
  scope: '범위',
  status: '상태',
  note: '메모',
  description: '설명',
  category: '분류',
  priority: '우선순위',
  quantity: '수량',
  itemName: '품목',
  customerName: '고객사',
}
// 모르는 필드는 코드 이름이라 백틱으로 둡니다(snake_case의 _가 기울임으로 읽히지 않게)
const field = (k: string) => (FIELD[k] ? escape(FIELD[k]) : `\`${escape(k)}\``)
/** 상태 값(web display/names.ts ENUM_LABELS.status와 같음) */
const STATUS: Record<string, string> = {
  in_progress: '진행 중', pending: '대기', approved: '승인', rejected: '반려', withdrawn: '회수', draft: '초안', confirmed: '확정',
  cancelled: '취소', issued: '발행', open: '접수', resolved: '해결', closed: '닫힘', scheduled: '예정', active: '대결 중', expired: '종료', revoked: '해제',
}
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/
const KST_DATETIME = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Seoul' })

const YMD = /^(\d{4})-(\d{2})-(\d{2})$/
const WEEK = ['일', '월', '화', '수', '목', '금', '토']
/** YYYY-MM-DD가 달력에 있는 날인지(2026-02-30은 아님) */
function realDay(ymd: string): boolean {
  const [y, m, d] = ymd.split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1, d))
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d
}

/** 값 하나를 사람이 읽는 글로 바꿉니다. 시각은 web과 같은 "2026. 11. 24. 오후 2:30", 날짜는 "2026. 11. 24.(화)", 금액 필드는 원 단위 */
function value(k: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '없음'
  if (typeof v === 'string' && ISO_DATETIME.test(v)) {
    // 꼴은 맞아도 없는 날(2026-02-30T10:00)이면 Date가 Invalid가 되거나(format이 던짐) 다음 달로 넘기므로 원래 값을 둡니다
    const d = new Date(v)
    return Number.isNaN(d.getTime()) || !realDay(v.slice(0, 10)) ? v : KST_DATETIME.format(d)
  }
  if (typeof v === 'string' && YMD.test(v)) {
    const [y, m, day] = v.split('-').map(Number)
    return realDay(v) ? `${y}. ${m}. ${day}.(${WEEK[new Date(Date.UTC(y, m - 1, day)).getUTCDay()]})` : v
  }
  if (k === 'status' && typeof v === 'string') return STATUS[v] ?? v
  if (typeof v === 'number' && /(^|_)(amount|price)$|(Amount|Price)$/.test(k)) return `${v.toLocaleString('ko-KR')}원`
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 실행 전 확인 카드. state가 있으면 버튼 대신 결정 결과를 보여 줍니다. */
export function approvalCard(a: Approval, agentName: string | undefined, state?: 'pending' | 'approved' | 'rejected' | 'failed'): SlackMessage {
  const p = a.preview ?? ({} as NonNullable<Approval['preview']>)
  // 도구 표시 이름(toolLabel, #575)이 없으면 코드 이름 대신 "실행 전 확인"만 둡니다
  const title = a.toolLabel ? `실행 전 확인: ${escape(a.toolLabel)}` : '실행 전 확인'
  const blocks: Block[] = [section(`*${title}*  \`${RISK[a.risk]}\`${agentName ? `  ${escape(agentName)}` : ''}`)]
  if (p.summary) blocks.push(section(escape(p.summary)))
  const lines: string[] = []
  for (const c of p.changes ?? []) {
    const before = (c.before ?? null) as Record<string, unknown> | null
    const after = (c.after ?? null) as Record<string, unknown> | null
    for (const k of new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])) {
      const b = before && k in before ? value(k, before[k]) : null
      const n = after && k in after ? value(k, after[k]) : null
      // 바꾸기(전·후가 다 있음)는 달라진 값만 보여 줍니다. 문서 전체가 오면 바뀌지 않은 필드가 카드를 덮기 때문입니다.
      if (before && after && b === n) continue
      lines.push(b !== null && n !== null ? `${field(k)} ~${escape(short(b))}~ → ${escape(short(n))}` : `${field(k)} ${escape(short(n ?? b ?? '없음'))}`)
    }
  }
  if (lines.length) blocks.push(...sections(lines.join('\n')))
  if (p.undoable === false) blocks.push(context('실행한 뒤에는 실행 취소할 수 없습니다.'))
  if (state) {
    const label = { pending: '처리 중', approved: '완료', rejected: '실행 안 함', failed: '진행 불가' }[state]
    blocks.push(context(label))
  } else {
    blocks.push({
      type: 'actions',
      elements: [
        // 실행 버튼은 일 이름(회의실 예약, 결재 회수)으로 둡니다. 표시 이름이 없으면 "실행"
        button(short(a.toolLabel ?? '실행', 75), ACTION.approve, a.approvalId, a.risk === 'irreversible' ? 'danger' : 'primary'),
        button('취소', ACTION.reject, a.approvalId),
      ],
    })
    blocks.push(context(a.expiresAt ? `요청한 사람만 누를 수 있습니다. ${time(a.expiresAt)}까지 확인해 주세요.` : '요청한 사람만 누를 수 있습니다.'))
  }
  return { text: p.summary ? `${title} · ${escape(p.summary)}` : title, blocks: limit(blocks) }
}

/** 완료한 일 카드. undoable이면 실행 취소 버튼을 둡니다. */
export function actionCard(a: Action, state?: 'undone' | { failed: string }): SlackMessage {
  const blocks: Block[] = [section(`*완료*  ${escape(a.summary)}`)]
  if (state === 'undone') blocks.push(context('취소됨'))
  else if (state) blocks.push(context(`실행 취소하지 못했습니다. ${escape(state.failed)}`))
  else if (a.undoable) blocks.push({ type: 'actions', elements: [button('실행 취소', ACTION.undo, a.actionId)] })
  return { text: `완료: ${escape(a.summary)}`, blocks }
}

const KST = new Intl.DateTimeFormat('ko-KR', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Seoul' })
function time(iso: string | undefined): string {
  if (!iso) return '–'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '–' : KST.format(d)
}

export function text(t: string): SlackMessage {
  return { text: escape(t), blocks: [section(escape(t))] }
}

/** 팀장 결재 알림. 승인·반려는 사람 전용 기능이라 web 결재 대기 링크만 둡니다. */
export function notificationMessage(n: Schemas['Notification'], webUrl: string): SlackMessage {
  const link = `${webUrl.replace(/\/$/, '')}/approvals`
  return {
    text: escape(n.message),
    blocks: [section(escape(n.message)), context(`승인·반려는 웹의 <${link}|결재 대기>에서 하세요.`)],
  }
}
