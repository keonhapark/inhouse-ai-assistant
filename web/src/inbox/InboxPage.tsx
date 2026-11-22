import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarDays, FileText, Package, Receipt, type LucideIcon } from 'lucide-react'
import { api, problemTitle, type Schemas } from '../api/client'
import { formatWhen, formatWon } from '../display/format'
import { notifyInboxChanged } from '../shell/pending'
import { Toolbar } from '../shell/Toolbar'
import { DocDetail } from './DocDetail'
import { BOXES, DOC_STATUS, type Box } from './labels'
import { toInboxItem, type InboxItem } from './types'
import './inbox.css'

const FORM_ICON: Record<string, LucideIcon> = { leave: CalendarDays, expense: Receipt, purchase: Package }
const TONE_DOT = { accent: 'blue', success: 'green', danger: 'red', neutral: 'gray', warning: 'orange', local: 'blue' } as const
const EMPTY: Record<Box, string> = {
  inbox: '결재할 문서가 없습니다.',
  delegated: '대신 결재할 문서가 없습니다.',
  done: '결재한 문서가 없습니다.',
  outbox: '상신한 문서가 없습니다.',
}


type ListState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; items: InboxItem[] }

/** 주소의 ?box=로 처음 열 칸을 고릅니다(채팅의 "결재 문서 보기"는 기안함으로 엽니다) */
const boxFrom = (v: string | null): Box => BOXES.find((b) => b.box === v)?.box ?? 'inbox'

export function InboxPage() {
  const [params] = useSearchParams()
  const [initialBox] = useState(() => boxFrom(params.get('box')))
  const [box, setBox] = useState<Box>(initialBox)
  const [list, setList] = useState<ListState>({ status: 'loading' })
  const [open, setOpen] = useState<InboxItem | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [counts, setCounts] = useState<Partial<Record<Box, number>>>({})
  // 양식은 문서 필드 이름·순서를 보이는 데 씁니다.
  const [forms, setForms] = useState<Schemas['ApprovalForm'][]>([])
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const panelRef = useRef<HTMLDivElement>(null)
  // 응답이 늦게 와도 지금 보고 있는 탭만 반영하도록 마지막 요청 번호와 현재 탭을 ref로 둡니다.
  const request = useRef(0)
  const boxRef = useRef<Box>(initialBox)

  /** 칸의 목록을 다시 불러옵니다. 그사이 칸을 바꿨으면 반영하지 않고 null */
  const load = useCallback(async (b: Box): Promise<InboxItem[] | null> => {
    const id = ++request.current
    try {
      const { data, error } = await api.GET('/inbox', { params: { query: { box: b } } })
      if (id !== request.current) return null
      const items = data ? data.items.map(toInboxItem) : null
      setList(items ? { status: 'ok', items } : { status: 'error', message: problemTitle(error, '결재함을 불러오지 못했습니다.') })
      if (items && (b === 'inbox' || b === 'delegated')) setCounts((c) => ({ ...c, [b]: items.length }))
      return items
    } catch {
      if (id === request.current) setList({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' })
      return null
    }
  }, [])

  /** 세그먼트의 건수(결재 대기·대결 대기). 못 세면 숫자를 보이지 않습니다 */
  const countBoxes = useCallback(async () => {
    for (const b of ['inbox', 'delegated'] as const) {
      try {
        const { data } = await api.GET('/inbox', { params: { query: { box: b } } })
        if (data) setCounts((c) => ({ ...c, [b]: data.items.length }))
      } catch {
        /* 건수만 빠집니다 */
      }
    }
  }, [])

  useEffect(() => {
    let alive = true
    const id = ++request.current
    for (const b of ['inbox', 'delegated'] as const) {
      api.GET('/inbox', { params: { query: { box: b } } }).then(
        ({ data }) => alive && data && setCounts((c) => ({ ...c, [b]: data.items.length })),
        () => {
          /* 건수만 빠집니다 */
        },
      )
    }
    api.GET('/inbox', { params: { query: { box: initialBox } } }).then(
      ({ data, error }) =>
        alive &&
        id === request.current &&
        setList(data ? { status: 'ok', items: data.items.map(toInboxItem) } : { status: 'error', message: problemTitle(error, '결재함을 불러오지 못했습니다.') }),
      () => alive && id === request.current && setList({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' }),
    )
    api.GET('/approval-forms').then(
      ({ data }) => {
        if (alive && data) setForms(data.items)
      },
      () => {
        /* 양식이 없으면 필드 이름 대신 키를 보입니다 */
      },
    )
    return () => {
      alive = false
    }
  }, [initialBox])

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

  /** 결재한 뒤에는 목록에서 다음 문서를 엽니다(명세 3.7). 남은 문서가 없으면 결재함 영역으로 초점을 옮깁니다 */
  async function onDecided(message: string) {
    notifyInboxChanged()
    setOpen(null)
    setNotice(message)
    const items = await load(boxRef.current)
    void countBoxes()
    if (items?.length) setOpen(items[0])
    else panelRef.current?.focus()
  }

  function closeDoc(id: string) {
    setOpen(null)
    document.getElementById(`doc-open-${id}`)?.focus()
  }

  const canDecide = box === 'inbox' || box === 'delegated'

  return (
    <main className="inbox" aria-labelledby="inbox-title">
      <Toolbar title="결재" titleId="inbox-title">
        <div role="tablist" aria-label="결재함" className="seg">
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
              className="seg__item"
              onClick={() => selectBox(b.box)}
              onKeyDown={(e) => onTabKey(e, i)}
            >
              {b.label}
              {counts[b.box] ? (
                <>
                  <span className="seg__n" aria-hidden>
                    {counts[b.box]}
                  </span>
                  <span className="visually-hidden">, {counts[b.box]}건</span>
                </>
              ) : null}
            </button>
          ))}
        </div>
      </Toolbar>

      <div className="inbox__body" data-open={open ? '' : undefined}>
        <div role="tabpanel" id="inbox-panel" aria-labelledby={`tab-${box}`} className="inbox__list" tabIndex={-1} ref={panelRef}>
          {notice && (
            <p role="status" className="inbox__notice">
              {notice}
            </p>
          )}
          {list.status === 'loading' && <p className="inbox__empty">불러오는 중입니다.</p>}
          {list.status === 'error' && (
            <p role="alert" className="alert">
              {list.message}
            </p>
          )}
          {list.status === 'ok' && list.items.length === 0 && <p className="inbox__empty">{EMPTY[box]}</p>}
          {list.status === 'ok' && list.items.length > 0 && (
            <ul className="doc-rows">
              {list.items.map((d) => {
                const Icon = FORM_ICON[d.formId] ?? FileText
                const st = DOC_STATUS[d.status]
                const settled = d.status !== 'in_progress'
                return (
                  <li key={d.id}>
                    <button
                      type="button"
                      id={`doc-open-${d.id}`}
                      className="doc-row"
                      aria-current={open?.id === d.id ? 'true' : undefined}
                      aria-labelledby={`doc-t-${d.id}`}
                      aria-describedby={`doc-s-${d.id} doc-e-${d.id}`}
                      onClick={() => setOpen(d)}
                    >
                      <span className="doc-row__ico" aria-hidden>
                        <Icon />
                      </span>
                      <span className="doc-row__main">
                        <span id={`doc-t-${d.id}`} className="doc-row__title">
                          {d.title}
                        </span>
                        <span id={`doc-s-${d.id}`} className="doc-row__sub">
                          {[d.formName, d.requesterName, d.viaDelegation && `${d.viaDelegation.originalApproverName} 대신`, settled && d.amount != null && formatWon(d.amount)]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <span id={`doc-e-${d.id}`} className="doc-row__end">
                        {settled ? (
                          <span className={`status status--${TONE_DOT[st.tone]}`}>{st.label}</span>
                        ) : (
                          d.amount != null && <span className="doc-row__amt">{formatWon(d.amount)}</span>
                        )}
                        <small>{formatWhen(d.createdAt)}</small>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        {open ? (
          <DocDetail
            key={open.id}
            doc={open}
            form={forms.find((f) => f.id === open.formId)}
            canDecide={canDecide}
            onDecided={(m) => void onDecided(m)}
            onReload={reloadOpen}
            onClose={() => closeDoc(open.id)}
          />
        ) : (
          <div className="detail detail--empty">
            <p>왼쪽 목록에서 문서를 고르세요.</p>
          </div>
        )}
      </div>
    </main>
  )
}
