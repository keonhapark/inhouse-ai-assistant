import { useState, type FormEvent } from 'react'
import { api, type Schemas } from '../api/client'
import { Badge, RiskBadge, type BadgeTone } from '../components/Badge'
import { Button } from '../components/Button'
import { toolName } from '../display/names'
import { useLookups } from '../display/useLookups'
import { formatDateTime } from '../inbox/labels'
import type { Range } from './AdminPage'
import { useLoad, usePaged } from './load'

type Audit = Schemas['audit.schema']

const KIND: Record<Audit['kind'], string> = {
  'erp.write': 'erp 쓰기',
  'erp.undo': 'erp 되돌리기',
  'erp.denied': 'erp 거절',
  'auth.login': '로그인',
  'auth.delegation_token_issued': '위임 토큰 발급',
  'route.decided': '라우팅',
  'tool.called': '도구 실행',
  'tool.blocked': '도구 차단',
  'execution_approval.requested': '실행 승인 요청',
  'execution_approval.decided': '실행 승인 결정',
  'llm.request': 'LLM 요청',
  'llm.redacted': 'LLM 가림',
  'rag.answered': '규정 답변',
  'rag.access_denied': '문서 접근 거절',
  'rag.document_purged': '문서 파기',
}

const RESULT: Record<Audit['result'], { label: string; tone: BadgeTone }> = {
  ok: { label: '성공', tone: 'success' },
  denied: { label: '거절', tone: 'danger' },
  conflict: { label: '충돌', tone: 'warning' },
  error: { label: '오류', tone: 'danger' },
  pending: { label: '대기', tone: 'neutral' },
}

const UNKNOWN = { label: '', tone: 'neutral' as BadgeTone }

type Filters = { kind: string; agentId: string; actorId: string }
const EMPTY: Filters = { kind: '', agentId: '', actorId: '' }

export function AuditPanel({ range }: { range: Range }) {
  // 입력 중인 값과 적용한 값을 나눕니다. 적용(Enter·버튼)할 때만 다시 불러옵니다.
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [applied, setApplied] = useState<Filters>(EMPTY)
  const agents = useLoad('registry', () => api.GET('/agent-registry'), '에이전트 목록을 불러오지 못했습니다.')
  // 직원·에이전트는 이름으로 보이고 ID는 작게 붙입니다(ia.md 3절). 사전을 못 받으면 ID만 보입니다
  const { people } = useLookups()
  const agentName = (id: string) => (agents.status === 'ok' ? agents.data.items.find((a) => a.id === id)?.name : undefined)
  const { first, items, next, loadMore, loadingMore, moreError } = usePaged<Audit>(
    `${range.since}|${range.until}|${applied.kind}|${applied.agentId}|${applied.actorId}`,
    (cursor) =>
      api.GET('/audit-events', {
        params: {
          query: {
            ...range,
            kind: applied.kind || undefined,
            agentId: applied.agentId || undefined,
            actorId: applied.actorId.trim() || undefined,
            cursor,
            limit: 20,
          },
        },
      }),
    '감사 로그를 불러오지 못했습니다.',
  )

  function apply(e: FormEvent) {
    e.preventDefault()
    setApplied(draft)
  }

  return (
    <div className="audit">
      <form className="admin__row" onSubmit={apply} aria-label="감사 로그 필터">
        <label className="admin__field">
          <span className="muted">종류</span>
          <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
            <option value="">전체</option>
            {Object.entries(KIND).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="admin__field">
          <span className="muted">에이전트</span>
          <select value={draft.agentId} onChange={(e) => setDraft({ ...draft, agentId: e.target.value })}>
            <option value="">전체</option>
            {agents.status === 'ok' &&
              agents.data.items.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <label className="admin__field">
          <span className="muted">직원 ID</span>
          <input value={draft.actorId} onChange={(e) => setDraft({ ...draft, actorId: e.target.value })} placeholder="예: E0007" />
        </label>
        <Button type="submit" variant="primary">
          적용
        </Button>
        {(applied.kind || applied.agentId || applied.actorId) && (
          <Button
            onClick={() => {
              setDraft(EMPTY)
              setApplied(EMPTY)
            }}
          >
            필터 지우기
          </Button>
        )}
      </form>

      {agents.status === 'error' && <p className="muted">{agents.message}</p>}
      {first.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {first.status === 'error' && <p role="alert">{first.message}</p>}
      {first.status === 'ok' && items.length === 0 && <p className="muted">조건에 맞는 감사 이벤트가 없습니다.</p>}
      {items.length > 0 && (
        <div className="table-scroll" role="region" aria-label="감사 이벤트 표" tabIndex={0}>
        <table className="table audit__table">
          <caption className="muted">{items.length}건{next ? ' (더 있음)' : ''}</caption>
          <thead>
            <tr>
              <th scope="col">시각</th>
              <th scope="col">종류</th>
              <th scope="col">직원</th>
              <th scope="col">에이전트</th>
              <th scope="col">작업</th>
              <th scope="col">결과</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.eventId}>
                <td className="audit__when">{formatDateTime(e.occurredAt)}</td>
                <td>
                  {KIND[e.kind] ?? e.kind} <span className="muted">{e.source}</span>
                </td>
                <td>
                  {e.actor.employeeId ? <Named name={people?.get(e.actor.employeeId)?.name} id={e.actor.employeeId} /> : <span className="muted">시스템</span>}
                  {e.actor.viaDelegationToken && <span className="muted"> · 위임 토큰</span>}
                </td>
                <td>{e.actor.agentId ? <Named name={agentName(e.actor.agentId)} id={e.actor.agentId} /> : '–'}</td>
                <td>
                  {e.operation ? <Named name={toolName(e.operation) === e.operation ? undefined : toolName(e.operation)} id={e.operation} /> : '–'}
                  {e.riskLevel && <RiskBadge risk={e.riskLevel} />}
                  {e.detail && <div className="muted audit__detail">{e.detail}</div>}
                </td>
                <td>
                  <Badge tone={(RESULT[e.result] ?? UNKNOWN).tone}>{(RESULT[e.result] ?? { label: e.result }).label}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {moreError && <p role="alert">{moreError}</p>}
      {next && (
        <Button onClick={() => void loadMore()} disabled={loadingMore}>
          {loadingMore ? '불러오는 중' : '더 보기'}
        </Button>
      )}
    </div>
  )
}

/** 이름이 있으면 이름 + 작은 ID, 없으면 ID만 */
function Named({ name, id }: { name?: string; id: string }) {
  if (!name) return <code>{id}</code>
  return (
    <>
      {name} <code className="audit__id">{id}</code>
    </>
  )
}
