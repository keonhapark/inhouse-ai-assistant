import * as Popover from '@radix-ui/react-popover'
import { Check, Clock, Minus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Button } from '../components/Button'
import { newIdempotencyKey } from '../chat/api'
import { formatDateTime, formatWon } from '../display/format'
import { formRows } from '../display/preview'
import { josa } from '../org/labels'
import { type InboxItem, type Step } from './types'
import { DOC_STATUS, STEP_STATUS, TONE_DOT } from './labels'

type Props = {
  doc: InboxItem
  /** 이 문서의 양식(필드 이름·값 표시용). 모르면 키를 그대로 보여 줍니다 */
  form?: Schemas['ApprovalForm']
  /** 이 칸에서 결재할 수 있는지(결재 대기·대결 대기) */
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

const STEP_ICON = { approved: Check, rejected: X, pending: Clock, waiting: Minus, skipped: Minus } as const
const initials = (name: string) => (name.length > 2 ? name.slice(-2) : name)

/**
 * 결재 상세(ux/design-system.md 3.7): 양식·번호·상태 → 제목 → 기안자 → 결재선(가로) → 금액 → 값 행 → 의견·반려·승인.
 * 승인은 버튼 위 확인 팝오버를 거치고, 반려는 의견(반려 사유)이 있어야 누를 수 있습니다.
 */
export function DocDetail({ doc, form, canDecide, onDecided, onReload, onClose }: Props) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  // 같은 요청(결정·버전·의견이 같음)을 다시 보낼 때만 같은 멱등 키를 씁니다.
  // 내용이 다른데 키가 같으면 erp가 idempotency-key-reused로 거절합니다.
  const lastKey = useRef<{ sig: string; value: string } | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const approveRef = useRef<HTMLButtonElement>(null)
  const rejectRef = useRef<HTMLButtonElement>(null)
  // 팝오버에서 승인을 눌러 닫힐 때는 Radix가 (비활성이 된) 승인 버튼으로 초점을 돌려보내지 않게 합니다
  const deciding = useRef(false)
  // 실패하면 누른 버튼으로 초점을 돌려줍니다. 진행 중에는 비활성이라 초점이 빠지므로 다시 켜진 뒤에 옮깁니다
  const refocus = useRef<'approve' | 'reject' | null>(null)
  useEffect(() => {
    if (busy || !refocus.current) return
    ;(refocus.current === 'approve' ? approveRef : rejectRef).current?.focus()
    refocus.current = null
  }, [busy])

  // 문서를 열면 제목으로 초점을 옮겨 스크린 리더가 바로 읽게 합니다.
  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  async function decide(kind: 'approve' | 'reject') {
    deciding.current = kind === 'approve'
    setConfirming(false)
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
      refocus.current = kind
      const message = problemTitle(problem, kind === 'approve' ? '승인하지 못했습니다.' : '반려하지 못했습니다.')
      setError(message)
      // 버전이 바뀌었으면 새 내용을 불러와 다시 판단하게 합니다.
      if (response.status === 409 && !(await onReload())) setError(`${message} 새 내용을 불러오지 못했습니다.`)
    } catch {
      refocus.current = kind
      setError('서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  const status = DOC_STATUS[doc.status]
  const decidable = canDecide && doc.status === 'in_progress'
  const cur = doc.currentStep ?? 0
  const lastStep = doc.steps.every((s) => s.order <= cur || s.status === 'skipped')
  const next = doc.steps.find((s) => s.order > cur && s.status === 'waiting')
  const noReason = !comment.trim()
  const rows = formRows(doc.fields, form).filter((r) => r.key !== form?.amountField)
  return (
    <section className="detail" aria-label={`결재 문서: ${doc.title}`}>
      <div className="detail__scroll">
        <div className="detail__kicker">
          <span>{doc.formName}</span>
          <span className={`status status--${TONE_DOT[status.tone]}`}>{status.label}</span>
          <button type="button" className="icon-btn detail__close" aria-label="닫기" onClick={onClose}>
            <X aria-hidden />
          </button>
        </div>
        <h2 className="detail__title" ref={titleRef} tabIndex={-1}>
          {doc.title}
        </h2>
        <p className="detail__who">
          <span className="avatar" aria-hidden>
            {initials(doc.requesterName)}
          </span>
          <b>{doc.requesterName}</b>
          <span>
            {doc.requesterUnitName && `${doc.requesterUnitName}, `}
            {formatDateTime(doc.createdAt)} 상신
          </span>
        </p>

        {doc.viaDelegation && (
          <p className="detail__proxy">
            {doc.viaDelegation.originalApproverName}님 대신 결재합니다.
            {doc.viaDelegation.endsAt && ` 대결은 ${formatDateTime(doc.viaDelegation.endsAt)}까지입니다.`}
          </p>
        )}

        <ol className="timeline" aria-label="결재선">
          <li className="timeline__done">
            <span className="timeline__dot" aria-hidden>
              <Check />
            </span>
            <b>{doc.requesterName}</b> <small>기안</small>
          </li>
          {doc.steps.map((s) => {
            const st = STEP_STATUS[s.status]
            const Icon = STEP_ICON[s.status]
            return (
              <li key={s.order} className={`timeline__${s.status}`} aria-current={s.order === doc.currentStep && s.status === 'pending' ? 'step' : undefined}>
                <span className="timeline__dot" aria-hidden>
                  <Icon />
                </span>
                <b>{stepName(s, 'approver')}</b> <small>{st.label}</small>
                {s.onBehalfOf && <small> · 대결 {stepName(s, 'actedBy')}</small>}
                {s.actedAt && <small> · {formatDateTime(s.actedAt)}</small>}
                {s.comment && <small className="timeline__comment">“{s.comment}”</small>}
              </li>
            )
          })}
        </ol>

        {doc.amount != null && (
          <div className="detail__amount">
            <b>{formatWon(doc.amount)}</b>
          </div>
        )}

        {rows.length > 0 && (
          <dl className="rows">
            {rows.map((r) => (
              <div key={r.key} className="row">
                <dt className="row__label">{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        )}

        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
      </div>

      {decidable && (
        <footer className="detail__foot">
          <div className="detail__opinion">
            <label className="visually-hidden" htmlFor={`opinion-${doc.id}`}>
              의견
            </label>
            <textarea
              id={`opinion-${doc.id}`}
              rows={1}
              maxLength={200}
              placeholder="의견"
              value={comment}
              aria-describedby={`opinion-help-${doc.id}`}
              onChange={(e) => setComment(e.target.value)}
            />
            <small id={`opinion-help-${doc.id}`}>반려할 때는 반려 사유를 적어 주세요</small>
          </div>
          <Button ref={rejectRef} variant="danger" disabled={busy || noReason} onClick={() => void decide('reject')}>
            반려
          </Button>
          <Popover.Root
            modal
            open={confirming}
            onOpenChange={(o) => {
              if (o) deciding.current = false
              setConfirming(o)
            }}
          >
            <Popover.Trigger asChild>
              <Button ref={approveRef} variant="primary" disabled={busy} className={confirming ? 'is-pressed' : undefined}>
                승인
              </Button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                className="popover"
                side="top"
                align="end"
                sideOffset={8}
                aria-labelledby={`approve-title-${doc.id}`}
                onCloseAutoFocus={(e) => deciding.current && e.preventDefault()}
              >
                <h3 id={`approve-title-${doc.id}`}>
                  {doc.amount != null ? `${formatWon(doc.amount)} ` : ''}
                  {`${doc.formName}${josa(doc.formName, '을', '를')} 승인할까요?`}
                </h3>
                <p>
                  {lastStep
                    ? '승인하면 결재가 끝나고, 승인은 취소할 수 없습니다.'
                    : `승인하면 ${next ? `${stepName(next, 'approver')}에게` : '다음 결재자에게'} 넘어가고, 승인은 취소할 수 없습니다.`}
                </p>
                <div className="popover__actions">
                  <Popover.Close asChild>
                    <Button>취소</Button>
                  </Popover.Close>
                  <Button variant="primary" onClick={() => void decide('approve')}>
                    승인
                  </Button>
                </div>
                <Popover.Arrow className="popover__arrow" width={14} height={7} />
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </footer>
      )}
    </section>
  )
}
