import { useEffect, useRef, useState } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { newIdempotencyKey } from '../chat/api'
import { fieldRows } from './fields'
import { type InboxItem, type Step } from './types'
import { DOC_STATUS, formatAmount, formatDateTime, STEP_STATUS } from './labels'


type Props = {
  doc: InboxItem
  /** 이 문서의 양식(필드 이름·값 표시용). 모르면 키를 그대로 보여 줍니다 */
  form?: Schemas['ApprovalForm']
  /** 이 탭에서 결재할 수 있는지(내 차례·대결) */
  canDecide: boolean
  onDecided(message: string): void
  /** 다시 불러오기. 실패하면 false */
  onReload(): Promise<boolean>
  onClose(): void
}

/** gateway가 붙인 이름(#67)이 있으면 이름, 없으면 ID */
function stepName(s: Step, who: 'approver' | 'actedBy'): string {
  return who === 'approver' ? (s.approverName ?? s.approverId) : (s.actedByName ?? s.actedBy ?? '처리자 미상')
}

export function DocDetail({ doc, form, canDecide, onDecided, onReload, onClose }: Props) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 같은 요청(결정·버전·의견이 같음)을 다시 보낼 때만 같은 멱등 키를 씁니다.
  // 내용이 다른데 키가 같으면 erp가 idempotency-key-reused로 거절합니다.
  const lastKey = useRef<{ sig: string; value: string } | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)

  // 문서를 열면 제목으로 초점을 옮겨 스크린 리더가 바로 읽게 합니다.
  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  async function decide(kind: 'approve' | 'reject') {
    const body = { version: doc.version, ...(comment.trim() ? { comment: comment.trim() } : {}) }
    const sig = JSON.stringify([kind, body])
    if (lastKey.current?.sig !== sig) lastKey.current = { sig, value: newIdempotencyKey('decide') }
    const value = lastKey.current.value
    setBusy(true)
    setError(null)
    const path = kind === 'approve' ? '/inbox/{documentId}/approve' : '/inbox/{documentId}/reject'
    try {
      const { data, error: problem, response } = await api.POST(path, {
        params: { path: { documentId: doc.id }, header: { 'Idempotency-Key': value } },
        body,
      })
      if (data) {
        onDecided(data.summary)
        return
      }
      const message = problemTitle(problem, kind === 'approve' ? '승인하지 못했습니다.' : '반려하지 못했습니다.')
      setError(message)
      // 버전이 바뀌었으면 새 내용을 불러와 다시 판단하게 합니다.
      if (response.status === 409 && !(await onReload())) setError(`${message} 새 내용을 불러오지 못했습니다.`)
    } catch {
      setError('서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  const status = DOC_STATUS[doc.status]
  const decidable = canDecide && doc.status === 'in_progress'
  return (
    <Card
      className="doc"
      aria-label={`결재 문서: ${doc.title}`}
      header={
        <>
          <h2 className="doc__title" ref={titleRef} tabIndex={-1}>
            {doc.title}
          </h2>
          <Badge tone={status.tone}>{status.label}</Badge>
          {doc.viaDelegation && <Badge tone="warning">대결: {doc.viaDelegation.originalApproverName}</Badge>}
          <Button className="doc__close" onClick={onClose}>
            닫기
          </Button>
        </>
      }
      footer={
        decidable ? (
          <>
            <Button variant="danger" disabled={busy} onClick={() => void decide('reject')}>
              반려
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void decide('approve')}>
              승인
            </Button>
          </>
        ) : undefined
      }
    >
      <dl className="doc__meta">
        <div>
          <dt>양식</dt>
          <dd>{doc.formName}</dd>
        </div>
        <div>
          <dt>요청자</dt>
          <dd>
            {doc.requesterName} {doc.requesterUnitName && <span className="muted">{doc.requesterUnitName}</span>}
          </dd>
        </div>
        <div>
          <dt>금액</dt>
          <dd className="mono">{formatAmount(doc.amount)}</dd>
        </div>
        <div>
          <dt>상신</dt>
          <dd className="mono">{formatDateTime(doc.createdAt)}</dd>
        </div>
        {fieldRows(doc.fields, form).map((r) => (
          <div key={r.key}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>

      <h3 className="doc__h">결재선</h3>
      <ol className="steps">
        {doc.steps.map((s) => {
          const st = STEP_STATUS[s.status]
          return (
            <li key={s.order} aria-current={s.order === doc.currentStep ? 'step' : undefined}>
              <span className="mono">{s.order}</span>
              <span>{stepName(s, 'approver')}</span>
              <Badge tone={st.tone}>{st.label}</Badge>
              {s.onBehalfOf && (
                <span className="muted">
                  대결 {stepName(s, 'actedBy')}
                </span>
              )}
              {s.actedAt && <span className="muted mono">{formatDateTime(s.actedAt)}</span>}
              {s.comment && <span className="muted">“{s.comment}”</span>}
            </li>
          )
        })}
      </ol>

      {doc.viaDelegation && (
        <p className="warning-line">
          {doc.viaDelegation.originalApproverName}님 대신 결재합니다.
          {doc.viaDelegation.endsAt && ` 위임은 ${formatDateTime(doc.viaDelegation.endsAt)}까지입니다.`}
        </p>
      )}

      {decidable && (
        <label className="doc__comment">
          의견(선택, 200자)
          <textarea rows={2} maxLength={200} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </Card>
  )
}
