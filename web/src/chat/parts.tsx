import { Globe, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Schemas } from '../api/client'
import { Badge, RiskBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { newIdempotencyKey, type UndoResult } from './api'
import { previewView } from '../display/preview'
import { toolName } from '../display/names'
import { useLookups } from '../display/useLookups'
import { formatTime } from './format'
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
  agentName?: string | null
  approval: Approval
  /** 사진을 붙인 턴의 카드. 값 일부가 사진에서 읽은 것일 수 있습니다 */
  fromImage?: boolean
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

export function PreviewCard({ agentName, approval, fromImage, decision, closed, busy, now: fixedNow, onDecide, onExpire }: PreviewProps) {
  const ticking = useNow(fixedNow === undefined && !decision && !closed && approval.expiresAt !== undefined)
  const now = fixedNow ?? ticking
  const { preview } = approval
  const label = approval.toolLabel ?? toolName(approval.tool)
  const expired = closed === 'expired' || (!decision && approval.expiresAt !== undefined && Date.parse(approval.expiresAt) <= now)
  useEffect(() => {
    if (expired && !decision && !closed) onExpire?.()
  }, [expired, decision, closed, onExpire])
  return (
    <Card
      className="preview"
      aria-label={`실행 전 확인: ${label}`}
      header={
        <>
          {agentName && <strong>{agentName}</strong>}
          <span>{label}</span>
          <RiskBadge risk={approval.risk} />
          {fromImage && <Badge tone="warning">사진에서 읽은 값</Badge>}
        </>
      }
      footer={
        decision ? (
          <Badge tone={decision === 'approve' ? 'success' : 'neutral'}>{decision === 'approve' ? '완료' : '실행 안 함'}</Badge>
        ) : closed === 'failed' ? (
          <Badge>진행 불가</Badge>
        ) : (
          <>
            {approval.expiresAt && (
              <span className="muted">{expired ? '확인 시간 지남' : `${formatTime(approval.expiresAt)}까지 확인`}</span>
            )}
            <Button disabled={busy || expired} onClick={() => onDecide('reject')}>
              취소
            </Button>
            <Button
              variant={approval.risk === 'irreversible' ? 'danger' : 'primary'}
              disabled={busy || expired}
              onClick={() => onDecide('approve')}
            >
              {label}
            </Button>
          </>
        )
      }
    >
      <p>{preview.summary}</p>
      {fromImage && <p className="warning-line">영수증과 맞는지 확인해 주세요.</p>}
      <PreviewChanges preview={preview} />
      {!preview.undoable && <p className="warning-line">실행하면 취소할 수 없습니다.</p>}
    </Card>
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

/**
 * 미리보기(WritePreview)의 바뀌는 값과 경고. 채팅 미리보기 카드와 대결 등록이 같이 씁니다.
 * 양식 필드 이름·한국어 값·결재선만 보이고, API가 준 원래 값은 "자세히" 안에 둡니다(#556).
 */
export function PreviewChanges({ preview }: { preview: Schemas['WritePreview'] }) {
  const lookups = useLookups()
  return (
    <>
      {preview.changes.map((c, i) => {
        const v = previewView(c, lookups)
        return (
          <div key={i} className="changes">
            <span className="muted">
              {v.title} {v.op}
            </span>
            {v.rows.length > 0 && (
              <dl>
                {v.rows.map((r) => (
                  <div key={r.key} className="changes__row">
                    <dt>{r.label}</dt>
                    <ChangeValue before={r.before} after={r.after} />
                  </div>
                ))}
              </dl>
            )}
            {v.line.length > 0 && (
              <div className="changes__line">
                <span className="muted">결재선</span>
                <ol>
                  {v.line.map((s) => (
                    <li key={s.order}>
                      {s.who} · {s.status}
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {v.raw.length > 0 && (
              <details className="changes__raw">
                <summary>자세히</summary>
                <dl>
                  {v.raw.map((r) => (
                    <div key={r.field} className="changes__row">
                      <dt className="mono">{r.field}</dt>
                      <ChangeValue before={r.before} after={r.after} />
                    </div>
                  ))}
                </dl>
              </details>
            )}
          </div>
        )
      })}
      {preview.warnings?.map((w) => (
        <p key={w} className="warning-line">
          {w}
        </p>
      ))}
    </>
  )
}

type ActionProps = {
  item: Extract<ThreadItem, { kind: 'action' }>
  onUndo(actionId: string, idempotencyKey: string): Promise<UndoResult>
}

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
    <Card className={`action${undone ? ' action--undone' : ''}`} aria-label="완료한 일">
      <div className="action__row">
        <Badge tone={undone ? 'neutral' : 'success'}>{undone ? '취소됨' : '완료'}</Badge>
        <span>{action.summary}</span>
        {action.undoable && !undone && (
          <Button className="action__undo" disabled={busy} onClick={undo}>
            실행 취소
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </Card>
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
