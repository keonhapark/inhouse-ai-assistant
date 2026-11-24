import { useState } from 'react'
import { api, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { formatDateTime } from '../inbox/labels'
import type { Range } from './AdminPage'
import { formatUsd, useLoad, usePaged } from './load'
import { entityName, segments } from './redact'

type Record_ = Schemas['EgressRecord']

export function EgressPanel({ range }: { range: Range }) {
  const [agentId, setAgentId] = useState('')
  const agents = useLoad('registry', () => api.GET('/agent-registry'), '에이전트 목록을 불러오지 못했습니다.')
  const { first, items, next, loadMore, loadingMore, moreError } = usePaged<Record_>(
    `${range.since}|${range.until}|${agentId}`,
    (cursor) => api.GET('/ops/egress', { params: { query: { ...range, agentId: agentId || undefined, cursor, limit: 20 } } }),
    '외부 전송 기록을 불러오지 못했습니다.',
  )

  return (
    <div className="egress">
      <p className="muted">
        외부 모델로 실제 보낸 요청입니다. 가림 전 원문은 저장하지 않으며, 표시한 자리는 보내기 전에 가린 곳입니다.
      </p>
      <label className="admin__field">
        <span className="muted">에이전트</span>
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">전체</option>
          {agents.status === 'ok' &&
            agents.data.items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
        </select>
      </label>
      {agents.status === 'error' && <p className="muted">{agents.message}</p>}
      {first.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {first.status === 'error' && <p role="alert">{first.message}</p>}
      {first.status === 'ok' && items.length === 0 && <p className="muted">이 기간에 외부로 보낸 요청이 없습니다.</p>}
      <ul className="egress__list">
        {items.map((r) => (
          <EgressItem key={r.recordId} record={r} />
        ))}
      </ul>
      {moreError && <p role="alert">{moreError}</p>}
      {next && (
        <Button onClick={() => void loadMore()} disabled={loadingMore}>
          {loadingMore ? '불러오는 중' : '더 보기'}
        </Button>
      )}
    </div>
  )
}

function EgressItem({ record: r }: { record: Record_ }) {
  const kinds = [...new Set(r.redactions.map((x) => entityName(x.entity)))]
  return (
    <li className="egress__item">
      <details>
        <summary>
          <span className="egress__when">{formatDateTime(r.at)}</span>
          <strong>{r.agentName ?? r.agentId ?? '에이전트 없음'}</strong>
          <code className="muted">{r.model}</code>
          {r.redactions.length > 0 ? <Badge tone="warning">가림 {r.redactions.length}곳: {kinds.join(', ')}</Badge> : <Badge>가림 없음</Badge>}
          <span className="muted egress__cost">
            {r.usage ? `${(r.usage.promptTokens ?? 0) + (r.usage.completionTokens ?? 0)}토큰 · ` : ''}
            {r.costUsd == null ? '비용 정보 없음' : formatUsd(r.costUsd)}
          </span>
        </summary>
        <ol className="egress__messages">
          {r.messages.map((m, i) => (
            <li key={i}>
              <span className="muted egress__role">{m.role}</span>
              <p>
                {m.content === '' && <span className="muted">(본문 없음: 도구 호출)</span>}
                {segments(m.content, r.redactions, i).map((s, j) =>
                  s.redaction ? (
                    <mark key={j} className="redacted" title={`가림: ${entityName(s.redaction.entity)}`}>
                      {s.text}
                    </mark>
                  ) : (
                    <span key={j}>{s.text}</span>
                  ),
                )}
              </p>
            </li>
          ))}
        </ol>
      </details>
    </li>
  )
}
