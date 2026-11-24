import { useEffect, useState, type FormEvent } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { newIdempotencyKey } from '../chat/api'
import { PreviewChanges } from '../chat/parts'
import { useAuth } from '../auth/useAuth'
import { DelegatePicker } from './DelegatePicker'
import { FormScope } from './FormScope'
import { checkDraft, initialDraft, toRequest, type Draft } from './draft'
import { DELEGATION_STATUS, formatAmount, formatDateTime } from './labels'

type DelegationView = Schemas['DelegationView']
type DelegationCreate = Schemas['DelegationCreate']

const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'

type PanelProps = { forms: Schemas['ApprovalForm'][]; formsError: string | null }

export function DelegationPanel({ forms, formsError }: PanelProps) {
  const { state } = useAuth()
  const meId = state.status === 'signed-in' ? state.employee.id : null
  const [items, setItems] = useState<DelegationView[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(initialDraft)
  const [preview, setPreview] = useState<Schemas['WritePreview'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // 확인 카드를 만든 요청 본문과 멱등 키를 묶어 둡니다. 지정은 이 본문을 그대로 보내
  // 확인한 내용과 다른 대결이 지정되지 않게 하고, 다시 눌러도 같은 키로 한 번만 지정되게 합니다.
  const [previewed, setPreviewed] = useState<{ body: DelegationCreate; key: string } | null>(null)

  async function refresh() {
    try {
      const { data, error: p } = await api.GET('/delegations', { params: { query: { role: 'all' } } })
      if (data) {
        setItems(data.items)
        setListError(null)
      } else setListError(problemTitle(p, '대결 목록을 불러오지 못했습니다.'))
    } catch {
      setListError(NETWORK)
    }
  }

  useEffect(() => {
    let alive = true
    api.GET('/delegations', { params: { query: { role: 'all' } } }).then(
      ({ data, error: p }) => {
        if (!alive) return
        if (data) setItems(data.items)
        else setListError(problemTitle(p, '대결 목록을 불러오지 못했습니다.'))
      },
      () => alive && setListError(NETWORK),
    )
    return () => {
      alive = false
    }
  }, [])

  function edit(patch: Partial<Draft>) {
    setDraft((d) => ({ ...d, ...patch }))
    // 내용이 바뀌면 이전 확인 카드는 맞지 않으므로 지웁니다.
    setPreview(null)
    setPreviewed(null)
  }

  async function submit(dryRun: boolean) {
    let sent: { body: DelegationCreate; key: string }
    if (dryRun) {
      const invalid = checkDraft(draft)
      if (invalid) {
        setError(invalid)
        return
      }
      sent = { body: toRequest(draft), key: newIdempotencyKey('dlg') }
    } else if (previewed) {
      sent = previewed
    } else {
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const { data, error: p } = await api.POST('/delegations', {
        params: { query: { dryRun }, header: dryRun ? {} : { 'Idempotency-Key': sent.key } },
        body: sent.body,
      })
      if (!data) {
        setError(problemTitle(p, dryRun ? '확인할 내용을 만들지 못했습니다.' : '대결을 지정하지 못했습니다.'))
        return
      }
      if ('dryRun' in data) {
        setPreview(data as Schemas['WritePreview'])
        setPreviewed(sent)
      } else {
        setNotice(data.summary)
        setPreview(null)
        setPreviewed(null)
        setDraft(initialDraft())
        await refresh()
      }
    } catch {
      setError(NETWORK)
    } finally {
      setBusy(false)
    }
  }

  async function revoke(d: DelegationView) {
    setError(null)
    setNotice(null)
    try {
      const { data, error: p } = await api.POST('/delegations/{delegationId}/revoke', {
        params: { path: { delegationId: d.id }, header: { 'Idempotency-Key': newIdempotencyKey('revoke') } },
      })
      if (data) {
        setNotice(data.summary)
        await refresh()
      } else setError(problemTitle(p, '대결을 해제하지 못했습니다.'))
    } catch {
      setError(NETWORK)
    }
  }

  function onPreview(e: FormEvent) {
    e.preventDefault()
    void submit(true)
  }

  const ready = draft.delegateId && draft.startsAt && draft.endsAt && draft.reason.trim() && draft.formTypes.length > 0

  return (
    <section className="delegation">
      <p className="muted">자리를 비우는 동안 다른 사람이 내 결재를 대신 처리하게 지정합니다.</p>

      {listError && (
        <p role="alert" className="alert">
          {listError}
        </p>
      )}
      {items && items.length === 0 && <p className="muted">지정한 대결이 없습니다.</p>}
      {items && items.length > 0 && (
        <ul className="delegation__list">
          {items.map((d) => {
            const st = DELEGATION_STATUS[d.status]
            const canRevoke = d.delegatorId === meId && (d.status === 'active' || d.status === 'scheduled')
            return (
              <li key={d.id}>
                <div className="delegation__head">
                  <strong>
                    {d.delegatorName} → {d.delegateName}
                  </strong>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
                <span className="muted mono">
                  {formatDateTime(d.startsAt)} ~ {formatDateTime(d.endsAt)}
                </span>
                <span className="muted">
                  {d.scope.formTypes.includes('*')
                    ? '모든 양식'
                    : d.scope.formTypes.map((id) => forms.find((f) => f.id === id)?.name ?? id).join(', ')}
                  {d.scope.maxAmount != null && ` · ${formatAmount(d.scope.maxAmount)} 이하`} · {d.reason}
                </span>
                {canRevoke && <RevokeButton onRevoke={() => revoke(d)} label={`${d.delegateName} 대결 해제`} />}
              </li>
            )
          })}
        </ul>
      )}

      <form className="delegation__form" onSubmit={onPreview}>
        <h2>새 대결 지정</h2>
        {/* 요청이 오가는 동안 입력을 막아 확인 카드와 다른 값이 섞이지 않게 합니다. */}
        <fieldset className="delegation__fields" disabled={busy}>
        <DelegatePicker value={draft.delegateId} excludeId={meId} onChange={(delegateId) => edit({ delegateId })} />
        <label>
          시작
          <input type="datetime-local" value={draft.startsAt} onChange={(e) => edit({ startsAt: e.target.value })} required />
        </label>
        <label>
          끝
          <input type="datetime-local" value={draft.endsAt} onChange={(e) => edit({ endsAt: e.target.value })} required />
        </label>
        <FormScope value={draft.formTypes} forms={forms} error={formsError} onChange={(formTypes) => edit({ formTypes })} />
        <label>
          금액 한도(원, 비우면 없음)
          <input type="number" min={0} step={1} inputMode="numeric" value={draft.maxAmount} onChange={(e) => edit({ maxAmount: e.target.value })} />
        </label>
        <label>
          사유
          <input maxLength={200} value={draft.reason} onChange={(e) => edit({ reason: e.target.value })} required />
        </label>
        </fieldset>
        {!preview && (
          <Button type="submit" disabled={busy || !ready}>
            내용 확인
          </Button>
        )}
      </form>

      {preview && (
        <Card
          aria-label="대결 지정 확인"
          header={<strong>대결 지정 확인</strong>}
          footer={
            <>
              <Button
                disabled={busy}
                onClick={() => {
                  setPreview(null)
                  setPreviewed(null)
                }}
              >
                취소
              </Button>
              <Button variant="primary" disabled={busy} onClick={() => void submit(false)}>
                대결 지정
              </Button>
            </>
          }
        >
          <p>{preview.summary}</p>
          <PreviewChanges preview={preview} />
        </Card>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice-ok">
          {notice}
        </p>
      )}
    </section>
  )
}

function RevokeButton({ onRevoke, label }: { onRevoke(): Promise<void>; label: string }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      aria-label={label}
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        await onRevoke()
        setBusy(false)
      }}
    >
      대결 해제
    </Button>
  )
}
