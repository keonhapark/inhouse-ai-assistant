import { useEffect, useState, type FormEvent } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Button } from '../components/Button'
import { DateTimeField } from '../components/DatePicker'
import { GroupHead } from '../components/Group'
import { newIdempotencyKey } from '../chat/api'
import { PreviewSheetBody } from '../chat/parts'
import { formatDateTime, formatWon } from '../display/format'
import { useAuth } from '../auth/useAuth'
import { DelegatePicker } from './DelegatePicker'
import { FormScope } from './FormScope'
import { checkDraft, initialDraft, ownDocWarning, scopeWarnings, toRequest, type Draft } from './draft'
import { DELEGATION_STATUS, TONE_DOT } from './labels'
import '../chat/chat.css'

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
  // 대결자가 올린 문서가 내 결재 차례에 있을 때의 경고. 확인 시트를 만들 때 결재 대기 목록에서 셉니다
  const [ownDocs, setOwnDocs] = useState<string | null>(null)

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
    setOwnDocs(null)
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
      // 확인 시트는 대결자 본인 문서 경고와 함께 한 번에 보여 줍니다(경고가 나중에 끼어들지 않게)
      const [{ data, error: p }, own] = await Promise.all([
        api.POST('/delegations', {
          params: { query: { dryRun }, header: dryRun ? {} : { 'Idempotency-Key': sent.key } },
          body: sent.body,
        }),
        dryRun ? countOwnDocs(sent.body.delegateId) : Promise.resolve(null),
      ])
      if (!data) {
        setError(problemTitle(p, dryRun ? '확인할 내용을 만들지 못했습니다.' : '대결을 지정하지 못했습니다.'))
        return
      }
      if ('dryRun' in data) {
        setPreview(data as Schemas['WritePreview'])
        setPreviewed(sent)
        setOwnDocs(own)
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
      {items && (
        <DelegationGroup
          id="delegation-given"
          title="맡긴 대결"
          empty="맡긴 대결이 없습니다."
          items={items.filter((d) => d.delegatorId === meId)}
          rowTitle={(d) => `${d.delegateName} 님에게 맡김`}
          forms={forms}
          onRevoke={revoke}
          canRevoke={(d) => d.status === 'active' || d.status === 'scheduled'}
        />
      )}
      {items && items.some((d) => d.delegateId === meId) && (
        <DelegationGroup
          id="delegation-taken"
          title="맡은 대결"
          items={items.filter((d) => d.delegateId === meId)}
          rowTitle={(d) => `${d.delegatorName} 님 대신 결재`}
          forms={forms}
        />
      )}

      <form className="delegation__form" onSubmit={onPreview}>
        <h2>새 대결 지정</h2>
        {/* 요청이 오가는 동안 입력을 막아 확인 카드와 다른 값이 섞이지 않게 합니다. */}
        <fieldset className="delegation__fields" disabled={busy}>
        <DelegatePicker value={draft.delegateId} excludeId={meId} onChange={(delegateId) => edit({ delegateId })} />
        <DateTimeField label="시작" value={draft.startsAt} disabled={busy} onChange={(startsAt) => edit({ startsAt })} />
        <DateTimeField label="끝" value={draft.endsAt} disabled={busy} defaultTime="18:00" onChange={(endsAt) => edit({ endsAt })} />
        <FormScope value={draft.formTypes} forms={forms} error={formsError} onChange={(formTypes) => edit({ formTypes })} />
        <label>
          금액 한도(원)
          <input type="number" min={0} step={1} inputMode="numeric" aria-describedby="delegation-max-help" value={draft.maxAmount} onChange={(e) => edit({ maxAmount: e.target.value })} />
        </label>
        {/* 도움말은 라벨 밖에 두어 입력칸 이름에 섞이지 않고 설명으로만 읽힙니다 */}
        <small id="delegation-max-help" className="field-help">
          비우면 한도 없음
        </small>
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
        <section className="sheet" aria-labelledby="delegation-confirm-title">
          <header className="sheet__head">
            <h2 id="delegation-confirm-title" className="sheet__title">
              대결 지정 확인
            </h2>
          </header>
          <PreviewSheetBody
            preview={{ ...preview, warnings: [...(preview.warnings ?? []), ...(previewed ? scopeWarnings(previewed.body) : []), ...(ownDocs ? [ownDocs] : [])] }}
            danger={false}
          />
          <footer className="sheet__foot">
            <span className="sheet__when" />
            <Button
              disabled={busy}
              onClick={() => {
                setPreview(null)
                setPreviewed(null)
                setOwnDocs(null)
              }}
            >
              취소
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void submit(false)}>
              대결 지정
            </Button>
          </footer>
        </section>
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

/** 대결 묶음 하나(맡긴 대결 / 맡은 대결). 화살표 대신 "○○ 님에게 맡김", "○○ 님 대신 결재"로 방향을 적습니다(ux #564 H-D3) */
function DelegationGroup(props: {
  id: string
  title: string
  empty?: string
  items: DelegationView[]
  rowTitle(d: DelegationView): string
  forms: Schemas['ApprovalForm'][]
  onRevoke?(d: DelegationView): Promise<void>
  canRevoke?(d: DelegationView): boolean
}) {
  const { id, title, empty, items, rowTitle, forms, onRevoke, canRevoke } = props
  return (
    <section className="group" aria-labelledby={id}>
      <GroupHead id={id} level={2} title={title} n={items.length > 0 ? `${items.length}건` : undefined} />
      {items.length === 0 && empty && <p className="group__empty">{empty}</p>}
      <ul className="group__list" hidden={items.length === 0}>
        {items.map((d) => {
          const st = DELEGATION_STATUS[d.status]
          const formNames = d.scope.formTypes.includes('*')
            ? '모든 양식'
            : d.scope.formTypes.map((f) => forms.find((x) => x.id === f)?.name ?? f).join(', ')
          return (
            <li key={d.id}>
              <div className="group__row">
                <span className="group__main">
                  <span className="group__title">{rowTitle(d)}</span>
                  <span className="group__sub">
                    {formatDateTime(d.startsAt)} ~ {formatDateTime(d.endsAt)}
                  </span>
                  <span className="group__sub">
                    {formNames} · {d.scope.maxAmount != null ? `${formatWon(d.scope.maxAmount)} 이하` : '금액 한도 없음'} · {d.reason}
                  </span>
                </span>
                <span className={`status status--${TONE_DOT[st.tone]}`}>{st.label}</span>
                {/* 같은 사람에게 여러 번 맡겼을 때 구별되게 이름에 시작 시각을 붙입니다 */}
                {onRevoke && canRevoke?.(d) && <RevokeButton onRevoke={() => onRevoke(d)} label={`${d.delegateName} 님에게 맡긴 대결 해제(${formatDateTime(d.startsAt)}부터)`} />}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** 대결자가 올린 문서가 지금 내 결재 차례(결재 대기)에 몇 건인지. 목록을 못 받으면 경고 없이 둡니다(지정 자체는 막지 않음) */
async function countOwnDocs(delegateId: string): Promise<string | null> {
  try {
    const { data } = await api.GET('/inbox', { params: { query: { box: 'inbox' } } })
    const mine = data?.items.filter((d) => d.requesterId === delegateId && d.status === 'in_progress') ?? []
    return mine.length ? ownDocWarning(mine[0].requesterName, mine.length) : null
  } catch {
    return null
  }
}

function RevokeButton({ onRevoke, label }: { onRevoke(): Promise<void>; label: string }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      className="btn--sm"
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
