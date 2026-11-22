import { useEffect, useState } from 'react'
import type { Schemas } from '../api/client'
import { Badge, LocalBadge, RiskBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { newIdempotencyKey, type UndoResult } from './api'
import { changeRows, formatTime, opLabel } from './format'
import { Markdown } from './markdown'
import type { Citation, ThreadItem } from './thread'

type Approval = NonNullable<Schemas['ChatEvent']['approval']>

export function AssistantMessage({ item }: { item: Extract<ThreadItem, { kind: 'assistant' }> }) {
  return (
    <div className="msg msg--assistant">
      <span className="visually-hidden">답: </span>
      <div className="msg__text md">
        <Markdown text={item.text} tail={item.streaming && <span className="msg__cursor" aria-hidden="true" />} />
      </div>
      {item.model?.location === 'local' && <LocalBadge />}
      {item.citations && item.citations.length > 0 && <Citations citations={item.citations} />}
    </div>
  )
}

export function Citations({ citations }: { citations: Citation[] }) {
  return (
    <details className="citations">
      <summary>근거 {citations.length}건</summary>
      <ul>
        {citations.map((c, i) => (
          <li key={`${c.docId}-${i}`}>
            <div className="citations__head">
              <strong>{c.title}</strong>
              {c.article && <span>{c.article}</span>}
              {!c.verified && <Badge tone="warning">인용 확인 안 됨</Badge>}
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
  const expired = closed === 'expired' || (!decision && approval.expiresAt !== undefined && Date.parse(approval.expiresAt) <= now)
  useEffect(() => {
    if (expired && !decision && !closed) onExpire?.()
  }, [expired, decision, closed, onExpire])
  return (
    <Card
      className="preview"
      aria-label={`실행 미리보기: ${approval.toolLabel ?? approval.tool}`}
      header={
        <>
          {agentName && <strong>{agentName}</strong>}
          <span>{approval.toolLabel ?? <code>{approval.tool}</code>}</span>
          <RiskBadge risk={approval.risk} />
          {fromImage && <Badge tone="warning">이미지에서 읽은 값(확인 필요)</Badge>}
        </>
      }
      footer={
        decision ? (
          <Badge tone={decision === 'approve' ? 'success' : 'neutral'}>{decision === 'approve' ? '실행함' : '취소함'}</Badge>
        ) : closed === 'failed' ? (
          <Badge>더 결정할 수 없음</Badge>
        ) : (
          <>
            {approval.expiresAt && (
              <span className="muted mono">{expired ? '만료됨' : `만료 ${formatTime(approval.expiresAt)}`}</span>
            )}
            <Button disabled={busy || expired} onClick={() => onDecide('reject')}>
              취소
            </Button>
            <Button
              variant={approval.risk === 'irreversible' ? 'danger' : 'primary'}
              disabled={busy || expired}
              onClick={() => onDecide('approve')}
            >
              실행
            </Button>
          </>
        )
      }
    >
      <p>{preview.summary}</p>
      {fromImage && (
        <p className="warning-line">첨부한 사진에서 읽은 값이 들어 있을 수 있습니다. 금액·날짜 같은 값이 사진과 맞는지 확인한 뒤 실행해 주세요.</p>
      )}
      <PreviewChanges preview={preview} />
      {!preview.undoable && <p className="warning-line">실행하면 되돌릴 수 없습니다.</p>}
    </Card>
  )
}

/** 미리보기(WritePreview)의 바뀌는 값과 경고. 채팅 미리보기 카드와 대결 등록이 같이 씁니다. */
export function PreviewChanges({ preview }: { preview: Schemas['WritePreview'] }) {
  return (
    <>
      {preview.changes.map((c, i) => (
        <div key={i} className="changes">
          <span className="muted">
            {c.resource} {opLabel(c.op)}
          </span>
          <dl>
            {changeRows(c).map((r) => (
              <div key={r.field} className="changes__row">
                <dt className="mono">{r.field}</dt>
                <dd>
                  {r.before !== undefined && <span className={r.after !== undefined ? 'changes__before' : ''}>{r.before}</span>}
                  {r.before !== undefined && r.after !== undefined && ' → '}
                  {r.after !== undefined && <span>{r.after}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
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
  // 같은 되돌리기를 다시 눌러도 같은 키로 보내 두 번 되돌리지 않게 합니다.
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
    <Card className={`action${undone ? ' action--undone' : ''}`} aria-label="실행한 일">
      <div className="action__row">
        <Badge tone={undone ? 'neutral' : 'success'}>{undone ? '되돌림' : '실행됨'}</Badge>
        <span>{action.summary}</span>
        {action.undoable && !undone && (
          <Button className="action__undo" disabled={busy} onClick={undo}>
            되돌리기
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

export function ToolCall({ item }: { item: Extract<ThreadItem, { kind: 'tool' }> }) {
  const { call } = item
  return (
    <details className="tool">
      <summary>
        도구 실행 <code>{call.tool}</code>
      </summary>
      <div className="row">
        {call.risk && <RiskBadge risk={call.risk} />}
        {call.status && <Badge tone={call.status === 'ok' ? 'success' : 'danger'}>{call.status === 'ok' ? '성공' : call.status === 'blocked' ? '차단' : '오류'}</Badge>}
      </div>
    </details>
  )
}
