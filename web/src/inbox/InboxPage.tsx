import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { api, problemTitle } from '../api/client'
import { Badge } from '../components/Badge'
import { DelegationPanel } from './DelegationPanel'
import { DocDetail } from './DocDetail'
import { BOXES, DOC_STATUS, formatAmount, formatDateTime, type Box } from './labels'
import { toInboxItem, type InboxItem } from './types'
import './inbox.css'


type ListState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; items: InboxItem[] }

export function InboxPage() {
  const [box, setBox] = useState<Box>('inbox')
  const [list, setList] = useState<ListState>({ status: 'loading' })
  const [open, setOpen] = useState<InboxItem | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const panelRef = useRef<HTMLDivElement>(null)
  // 응답이 늦게 와도 지금 보고 있는 탭만 반영하도록 마지막 요청 번호와 현재 탭을 ref로 둡니다.
  const request = useRef(0)
  const boxRef = useRef<Box>('inbox')

  const load = useCallback(async (b: Box) => {
    const id = ++request.current
    try {
      const { data, error } = await api.GET('/inbox', { params: { query: { box: b } } })
      if (id !== request.current) return
      setList(data ? { status: 'ok', items: data.items.map(toInboxItem) } : { status: 'error', message: problemTitle(error, '결재함을 불러오지 못했습니다.') })
    } catch {
      if (id === request.current) setList({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' })
    }
  }, [])

  useEffect(() => {
    let alive = true
    const id = ++request.current
    api.GET('/inbox', { params: { query: { box: 'inbox' } } }).then(
      ({ data, error }) =>
        alive &&
        id === request.current &&
        setList(data ? { status: 'ok', items: data.items.map(toInboxItem) } : { status: 'error', message: problemTitle(error, '결재함을 불러오지 못했습니다.') }),
      () => alive && id === request.current && setList({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' }),
    )
    return () => {
      alive = false
    }
  }, [])

  function selectBox(b: Box) {
    if (b === box) return
    setBox(b)
    boxRef.current = b
    setOpen(null)
    setNotice(null)
    setList({ status: 'loading' })
    void load(b)
  }

  // WAI-ARIA 탭 패턴: 왼쪽·오른쪽 화살표, Home·End로 탭을 옮깁니다.
  function onTabKey(e: KeyboardEvent, i: number) {
    const last = BOXES.length - 1
    const next = e.key === 'ArrowRight' ? (i === last ? 0 : i + 1) : e.key === 'ArrowLeft' ? (i === 0 ? last : i - 1) : e.key === 'Home' ? 0 : e.key === 'End' ? last : -1
    if (next < 0) return
    e.preventDefault()
    tabRefs.current[next]?.focus()
    selectBox(BOXES[next].box)
  }

  /** 열린 문서를 다시 불러옵니다. 그사이 탭이나 문서가 바뀌었으면 반영하지 않습니다. 실패하면 false */
  async function reloadOpen(): Promise<boolean> {
    if (!open) return true
    const docId = open.id
    const b = boxRef.current
    try {
      const { data } = await api.GET('/inbox/{documentId}', { params: { path: { documentId: docId } } })
      if (boxRef.current === b) {
        if (data) setOpen((cur) => (cur?.id === docId ? toInboxItem(data) : cur))
        await load(b)
      }
      return !!data
    } catch {
      return false
    }
  }

  async function onDecided(message: string) {
    setOpen(null)
    setNotice(message)
    // 처리한 행은 목록에서 빠지므로 초점을 결재함 영역으로 옮깁니다.
    panelRef.current?.focus()
    await load(boxRef.current)
  }

  function closeDoc(id: string) {
    setOpen(null)
    document.getElementById(`doc-open-${id}`)?.focus()
  }

  const canDecide = box === 'inbox' || box === 'delegated'

  return (
    <div className="inbox">
      <main className="inbox__main">
        <h1>승인함</h1>
        <div role="tablist" aria-label="결재함" className="tabs">
          {BOXES.map((b, i) => (
            <button
              key={b.box}
              ref={(el) => {
                tabRefs.current[i] = el
              }}
              role="tab"
              id={`tab-${b.box}`}
              aria-selected={box === b.box}
              aria-controls="inbox-panel"
              tabIndex={box === b.box ? 0 : -1}
              className="tabs__tab"
              onClick={() => selectBox(b.box)}
              onKeyDown={(e) => onTabKey(e, i)}
            >
              {b.label}
            </button>
          ))}
        </div>

        <div role="tabpanel" id="inbox-panel" aria-labelledby={`tab-${box}`} className="inbox__panel" tabIndex={0} ref={panelRef}>
          {notice && (
            <p role="status" className="notice-ok">
              {notice}
            </p>
          )}
          {list.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
          {list.status === 'error' && (
            <p role="alert" className="alert">
              {list.message}
            </p>
          )}
          {list.status === 'ok' && list.items.length === 0 && <p className="muted">이 함에는 결재 문서가 없습니다.</p>}
          {list.status === 'ok' && list.items.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">양식</th>
                  <th scope="col">제목</th>
                  <th scope="col">요청자</th>
                  <th scope="col" className="num">
                    금액
                  </th>
                  <th scope="col">상신</th>
                  <th scope="col">상태</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((d) => {
                  const st = DOC_STATUS[d.status]
                  return (
                    <tr key={d.id} aria-current={open?.id === d.id ? 'true' : undefined}>
                      <td>{d.formName}</td>
                      <td>
                        <button type="button" id={`doc-open-${d.id}`} className="link" onClick={() => setOpen(d)}>
                          {d.title}
                        </button>
                        {d.viaDelegation && <Badge tone="warning">대결: {d.viaDelegation.originalApproverName}</Badge>}
                      </td>
                      <td>{d.requesterName}</td>
                      <td className="num mono">{formatAmount(d.amount)}</td>
                      <td className="mono">{formatDateTime(d.createdAt)}</td>
                      <td>
                        <Badge tone={st.tone}>{st.label}</Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {open && (
            <DocDetail
              key={open.id}
              doc={open}
              canDecide={canDecide}
              onDecided={(m) => void onDecided(m)}
              onReload={reloadOpen}
              onClose={() => closeDoc(open.id)}
            />
          )}
        </div>
      </main>
      <DelegationPanel />
    </div>
  )
}
