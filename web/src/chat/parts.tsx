import { CircleCheck, Globe, Image as ImageIcon, TriangleAlert, Undo2, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Schemas } from '../api/client'
import { Button } from '../components/Button'
import { newIdempotencyKey, type UndoResult } from './api'
import type { StatusTone } from '../display/conversation'
import { previewView } from '../display/preview'
import { toolName } from '../display/names'
import { useLookups } from '../display/useLookups'
import { formatTime } from '../display/format'
import { Markdown } from './markdown'
import type { Citation, ThreadItem } from './thread'

type Approval = NonNullable<Schemas['ChatEvent']['approval']>
type ToolCallInfo = NonNullable<Schemas['ChatEvent']['toolCall']>

/** 답 머리: "재무 담당 AI · 사내 처리"(ux/design-system.md 3.8). 한 턴의 첫 답에만 붙입니다 */
export type AnswerHead = { agent: string; location?: 'local' | 'external' }

export function AssistantMessage({ item, head }: { item: Extract<ThreadItem, { kind: 'assistant' }>; head?: AnswerHead }) {
  return (
    <div className="msg msg--assistant">
      {head ? (
        <div className="msg__who">
          <b>{head.agent}</b>
          {head.location === 'local' && <span className="status status--blue">사내 처리</span>}
          {head.location === 'external' && (
            <span className="status">
              <Globe aria-hidden />
              외부 AI 사용
            </span>
          )}
          <span className="visually-hidden">답: </span>
        </div>
      ) : (
        <span className="visually-hidden">답: </span>
      )}
      <div className="msg__text md">
        <Markdown text={item.text} tail={item.streaming && <span className="msg__cursor" aria-hidden="true" />} />
      </div>
      {item.citations && item.citations.length > 0 && <Citations citations={item.citations} />}
    </div>
  )
}

export function Citations({ citations }: { citations: Citation[] }) {
  return (
    <details className="citations">
      <summary>근거 규정 {citations.length}건</summary>
      <ul>
        {citations.map((c, i) => (
          <li key={`${c.docId}-${i}`}>
            <div className="citations__head">
              <strong>{c.title}</strong>
              {c.article && <span>{c.article}</span>}
              {!c.verified && (
                <span className="citations__unverified">
                  <TriangleAlert aria-hidden />
                  원문 대조 안 됨
                </span>
              )}
            </div>
            <blockquote>{c.quote}</blockquote>
          </li>
        ))}
      </ul>
    </details>
  )
}

type PreviewProps = {
  approval: Approval
  /** 사진을 붙인 턴의 카드. 값 일부가 사진에서 읽은 것일 수 있습니다 */
  fromImage?: boolean
  /** 이 화면에서 보낸 사진(값 옆에 둡니다). 복원한 기록에는 없습니다 */
  photo?: { url: string; name: string }
  decision?: 'approve' | 'reject'
  closed?: 'expired' | 'failed'
  busy: boolean
  /** 시험에서 현재 시각을 고정합니다. */
  now?: number
  onDecide(decision: 'approve' | 'reject'): void
  /** 만료 시각이 지나면 한 번 부릅니다(대화 입력 잠금을 풀기 위해). */
  onExpire?(): void
}

/** 만료 표시가 시간이 지나면 바뀌도록 1초마다 현재 시각을 갱신합니다. */
function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [enabled])
  return now
}

/**
 * 실행 전 확인 시트(ux/design-system.md 3.6): 제목(일 이름) → 금액 → [사진 | 값 행] → 결재선 → "…까지 확인" [취소] [일 이름].
 * 결정이 나면(완료·실행 안 함·진행 불가) 한 줄로 접습니다. 실행해 완료한 일 행이 뒤따르면 대화 화면이 이 시트를 그리지 않습니다(같은 자리에서 바뀜).
 */
export function PreviewCard({ approval, fromImage, photo, decision, closed, busy, now: fixedNow, onDecide, onExpire }: PreviewProps) {
  const ticking = useNow(fixedNow === undefined && !decision && !closed && approval.expiresAt !== undefined)
  const now = fixedNow ?? ticking
  const { preview } = approval
  const label = approval.toolLabel ?? toolName(approval.tool)
  const expired = closed === 'expired' || (!decision && approval.expiresAt !== undefined && Date.parse(approval.expiresAt) <= now)
  useEffect(() => {
    if (expired && !decision && !closed) onExpire?.()
  }, [expired, decision, closed, onExpire])

  const result: { label: string; tone: StatusTone } | null = decision
    ? decision === 'approve'
      ? { label: '완료', tone: 'green' }
      : { label: '실행 안 함', tone: 'gray' }
    : closed === 'failed'
      ? { label: '진행 불가', tone: 'gray' }
      : expired
        ? { label: '진행 불가 · 확인 시간 지남', tone: 'gray' }
        : null

  if (result) {
    return (
      <section className="sheet sheet--closed" aria-label={`실행 전 확인: ${label}`}>
        <h2 className="sheet__title">{label}</h2>
        <span className={`status status--${result.tone}`}>{result.label}</span>
        <span className="sheet__closed-summary">{preview.summary}</span>
      </section>
    )
  }

  // 실행 취소할 수 없는 일은 버튼을 위험 모양으로 두고 경고 줄을 붙입니다(색만으로 알리지 않음)
  const danger = approval.risk === 'irreversible' || !preview.undoable
  return (
    <section className="sheet" aria-label={`실행 전 확인: ${label}`}>
      <header className="sheet__head">
        <h2 className="sheet__title">{label}</h2>
        {fromImage && (
          <span className="tag">
            <ImageIcon aria-hidden />
            사진에서 읽은 값
          </span>
        )}
      </header>
      <PreviewSheetBody preview={preview} photo={fromImage ? photo : undefined} danger={danger} />
      <footer className="sheet__foot">
        <span className="sheet__when">
          {fromImage
            ? `영수증과 맞는지 확인해 주세요.${approval.expiresAt ? ` ${formatTime(approval.expiresAt)}까지` : ''}`
            : approval.expiresAt && `${formatTime(approval.expiresAt)}까지 확인`}
        </span>
        <Button disabled={busy} onClick={() => onDecide('reject')}>
          취소
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} disabled={busy} onClick={() => onDecide('approve')}>
          {label}
        </Button>
      </footer>
    </section>
  )
}

/** 실행 전 확인 시트의 본문(금액 → 요약 → 값 행 → 결재선 → 경고 → 자세히). 채팅 시트와 대결 지정 확인이 같이 씁니다 */
export function PreviewSheetBody({ preview, photo, danger }: { preview: Schemas['WritePreview']; photo?: { url: string; name: string }; danger: boolean }) {
  const lookups = useLookups()
  const views = preview.changes.map((c) => previewView(c, lookups))
  // 금액은 값 행에서 빼 맨 위에 크게 둡니다(첫 변경의 금액 하나)
  const first = views[0]
  const amountRow = first?.amountKey ? first.rows.find((r) => r.key === first.amountKey) : undefined
  const amount = amountRow?.after ?? amountRow?.before
  return (
    <>
      {amount && (
        <div className="sheet__amount">
          <b>{amount}</b>
        </div>
      )}
      <p className="sheet__summary">{preview.summary}</p>
      <div className={`sheet__body${photo ? ' sheet__body--photo' : ''}`}>
        {photo && (
          <figure className="sheet__photo">
            <img src={photo.url} alt={`첨부한 사진: ${photo.name}`} />
            <a className="btn btn--link" href={photo.url} target="_blank" rel="noreferrer">
              크게 보기
            </a>
          </figure>
        )}
        <div className="sheet__values">
          {views.map((v, i) => {
            const rows = v.rows.filter((r) => r !== amountRow)
            return (
              <div key={i} className="sheet__change">
                {views.length > 1 && (
                  <span className="sheet__change-title">
                    {v.title} {v.op}
                  </span>
                )}
                {rows.length > 0 && (
                  <dl className="rows">
                    {rows.map((r) => (
                      <div key={r.key} className="row">
                        <dt className="row__label">{r.label}</dt>
                        <ChangeValue before={r.before} after={r.after} />
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            )
          })}
        </div>
      </div>
      {views.map(
        (v, i) =>
          v.line.length > 0 && (
            <p key={i} className="sheet__line">
              <Users aria-hidden />
              {views.length > 1 ? `${v.title} 결재선` : '결재선'}
              {v.line.map((s) => (
                <span key={s.order}>
                  <b>{s.who}</b> {s.status}
                </span>
              ))}
            </p>
          ),
      )}
      {danger && (
        <p className="sheet__line sheet__line--danger">
          <TriangleAlert aria-hidden />
          실행하면 취소할 수 없습니다.
        </p>
      )}
      {preview.warnings?.map((w) => (
        <p key={w} className="sheet__warning">
          {w}
        </p>
      ))}
      {views.some((v) => v.raw.length > 0) && (
        <details className="sheet__raw changes__raw">
          <summary>자세히</summary>
          {views.map(
            (v, i) =>
              v.raw.length > 0 && (
                <div key={i}>
                  {views.length > 1 && <span className="sheet__change-title">{`${v.title} ${v.op}`}</span>}
                  <dl>
                    {v.raw.map((r) => (
                      <div key={r.field} className="changes__row">
                        <dt className="mono">{r.field}</dt>
                        <ChangeValue before={r.before} after={r.after} />
                      </div>
                    ))}
                  </dl>
                </div>
              ),
          )}
        </details>
      )}
    </>
  )
}

function ChangeValue({ before, after }: { before?: string; after?: string }) {
  return (
    <dd>
      {before !== undefined && <span className={after !== undefined ? 'changes__before' : ''}>{before}</span>}
      {before !== undefined && after !== undefined && ' → '}
      {after !== undefined && <span>{after}</span>}
    </dd>
  )
}

type ActionProps = {
  item: Extract<ThreadItem, { kind: 'action' }>
  onUndo(actionId: string, idempotencyKey: string): Promise<UndoResult>
}

/** 결재 문서를 만드는 일. 완료한 일 행에 "결재 문서 보기"를 붙입니다 */
const APPROVAL_TOOLS = new Set(['expense_request', 'purchase_request', 'leave_request', 'loan_request'])

/** 완료한 일 행(ux/design-system.md 3.6): ✓ 완료 + 요약 + 결재 문서 보기 + 실행 취소 */
export function ActionCard({ item, onUndo }: ActionProps) {
  // 실행 취소를 다시 눌러도 같은 키로 보내 두 번 취소하지 않게 합니다.
  const [key] = useState(() => newIdempotencyKey('undo'))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { action, undone } = item
  async function undo() {
    setBusy(true)
    setError(null)
    const r = await onUndo(action.actionId, key)
    setBusy(false)
    if (!r.ok) setError(r.message)
  }
  return (
    <section className={`done${undone ? ' done--undone' : ''}`} aria-label="완료한 일">
      <div className="done__row">
        <span className="done__state">
          {undone ? <Undo2 aria-hidden /> : <CircleCheck aria-hidden />}
          {undone ? '취소됨' : '완료'}
        </span>
        <span className="done__summary">{action.summary}</span>
        {APPROVAL_TOOLS.has(action.tool) && !undone && (
          <Link className="btn btn--link" to="/approvals?box=outbox">
            결재 문서 보기
          </Link>
        )}
        {action.undoable && !undone && (
          <Button className="btn--sm" disabled={busy} onClick={undo}>
            실행 취소
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </section>
  )
}

const STEP_STATUS: Record<NonNullable<ToolCallInfo['status']>, string | null> = { ok: null, error: '실패', blocked: '처리할 수 없음' }

/**
 * 에이전트가 쓴 기능(도구). 직원 화면에서는 접어 두고, 펼치면 표시 이름만 보입니다(ux/copy-guide.md 1.2).
 * 이어서 온 도구 줄을 한 묶음으로 받습니다.
 */
export function ToolSteps({ calls }: { calls: ToolCallInfo[] }) {
  return (
    <details className="steps">
      <summary>처리 과정 {calls.length}단계</summary>
      <ol>
        {calls.map((c, i) => {
          const status = c.status ? STEP_STATUS[c.status] : null
          return (
            <li key={i}>
              {c.tool ? toolName(c.tool) : '알 수 없는 기능'}
              {status && <span className="steps__status"> · {status}</span>}
            </li>
          )
        })}
      </ol>
    </details>
  )
}
