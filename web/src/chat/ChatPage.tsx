import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { decideApproval, postMessage, undoAction, type StreamResult } from './api'
import { formatBytes, IMAGE_TYPES, MAX_IMAGES, pickImages, type PickedImage } from './attachments'
import { ActionCard, AssistantMessage, PreviewCard, ToolCall } from './parts'
import { emptyThread, pendingApproval, threadReducer, type ChatEvent } from './thread'
import './chat.css'

type Summary = Schemas['ConversationSummary']
type AgentInfo = Schemas['AgentInfo']

const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
const ROUTE_METHOD = { llm: '자동 선택', keyword: '자동 선택(낱말)', fallback: '맞는 부서 없음', explicit: '직접 선택' } as const

export function ChatPage() {
  const [convs, setConvs] = useState<Summary[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentChoice, setAgentChoice] = useState('')
  const [selected, setSelected] = useState<Summary | null>(null)
  const [thread, dispatch] = useReducer(threadReducer, emptyThread)
  const [draft, setDraft] = useState('')
  // 보내기 전 붙인 사진과 붙이지 못한 이유
  const [images, setImages] = useState<PickedImage[]>([])
  const [attachErrors, setAttachErrors] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  // 대화를 빠르게 바꿔 누르면 늦게 온 앞 응답이 화면을 덮지 않게 마지막으로 연 id만 반영합니다.
  const opening = useRef<string | null>(null)
  // 대화를 열거나 새로 시작할 때마다 늘립니다. 대화 생성을 기다리는 사이 바뀌었으면 보내지 않습니다.
  const epoch = useRef(0)
  // 사용자가 위로 올려 읽는 중이면 새 조각이 와도 끌어내리지 않습니다.
  const stick = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // 목록 새로 고침이 실패해도 대화는 이어 갑니다. 다음 새로 고침에서 맞춰집니다.
  const refreshList = useCallback(async () => {
    try {
      const { data } = await api.GET('/conversations')
      if (data) setConvs(data.items)
    } catch {
      /* 다음 새로 고침에서 다시 받습니다 */
    }
  }, [])

  useEffect(() => {
    api.GET('/conversations').then(
      ({ data, error }) => (data ? setConvs(data.items) : setNotice(problemTitle(error, '대화 목록을 불러오지 못했습니다.'))),
      () => setNotice(NETWORK),
    )
    api.GET('/agents').then(
      ({ data }) => data && setAgents(data.items.filter((a) => a.callable !== false)),
      () => setNotice(NETWORK),
    )
    return () => abort.current?.abort()
  }, [])

  useLayoutEffect(() => {
    const el = logRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [thread.items])

  function startStream(): AbortSignal {
    abort.current?.abort()
    abort.current = new AbortController()
    dispatch({ type: 'stream-start' })
    return abort.current.signal
  }

  const onEvent = (event: ChatEvent) => dispatch({ type: 'event', event })

  async function finishStream(result: StreamResult) {
    dispatch({ type: 'stream-end' })
    if (!result.ok) dispatch({ type: 'local-error', message: result.message, retryable: result.retryable })
    await refreshList()
  }

  async function open(c: Summary) {
    abort.current?.abort()
    epoch.current++
    stick.current = true
    setNotice(null)
    setSelected(c)
    dispatch({ type: 'reset' })
    opening.current = c.conversationId
    let res
    try {
      res = await api.GET('/conversations/{conversationId}', { params: { path: { conversationId: c.conversationId } } })
    } catch {
      if (opening.current === c.conversationId) setNotice(NETWORK)
      return
    }
    if (opening.current !== c.conversationId) return
    const { data, error } = res
    if (data) {
      setSelected(data)
      dispatch({ type: 'reset', events: data.events })
    } else {
      setNotice(problemTitle(error, '대화를 불러오지 못했습니다.'))
    }
  }

  function newConversation() {
    abort.current?.abort()
    epoch.current++
    stick.current = true
    opening.current = null
    setSelected(null)
    setNotice(null)
    dispatch({ type: 'reset' })
  }

  /** 사진만 보낼 때 메시지 본문(계약상 content는 필수입니다) */
  const IMAGE_ONLY = '사진을 첨부했습니다.'

  async function send(text: string, imgs: { name: string; dataUrl: string }[] = []) {
    const content = text.trim() || (imgs.length ? IMAGE_ONLY : '')
    if (!content) return
    setNotice(null)
    let conv = selected
    if (!conv) {
      const started = epoch.current
      setCreating(true)
      let res
      try {
        res = await api.POST('/conversations', { body: agentChoice ? { agentId: agentChoice } : {} })
      } catch {
        res = null
      } finally {
        setCreating(false)
      }
      if (epoch.current !== started) return
      if (!res?.data) {
        setNotice(res ? problemTitle(res.error, '대화를 시작하지 못했습니다.') : NETWORK)
        return
      }
      conv = res.data
      setSelected(res.data)
    }
    stick.current = true
    setDraft('')
    setImages([])
    setAttachErrors([])
    dispatch({ type: 'user', text: content, images: imgs.map(({ name, dataUrl }) => ({ name, dataUrl })) })
    const signal = startStream()
    await finishStream(await postMessage(conv.conversationId, content, onEvent, signal, imgs))
  }

  async function decide(approvalId: string, decision: 'approve' | 'reject') {
    const signal = startStream()
    const result = await decideApproval(approvalId, decision, onEvent, signal)
    // 거절된 결정(이미 결정됨·만료·권한 없음)은 다시 눌러도 같으므로 카드를 닫고 입력을 풉니다.
    if (!result.ok && result.status >= 400 && result.status < 500) {
      dispatch({ type: 'approval-closed', approvalId, reason: 'failed' })
    }
    await finishStream(result)
  }

  const onExpire = useCallback((approvalId: string) => dispatch({ type: 'approval-closed', approvalId, reason: 'expired' }), [])

  async function undo(actionId: string, key: string) {
    const r = await undoAction(actionId, key)
    if (r.ok) dispatch({ type: 'undone', actionId })
    return r
  }

  const waiting = pendingApproval(thread)
  const lastUser = [...thread.items].reverse().find((i) => i.kind === 'user')
  const agentName = thread.route?.agentName ?? selected?.agentName
  const canSend = !thread.streaming && !waiting && !creating

  // 실행 승인을 기다리느라 꺼졌던 입력창이 다시 켜지면 포커스를 돌려줍니다.
  const wasWaiting = useRef(false)
  useEffect(() => {
    if (wasWaiting.current && !waiting && !thread.streaming) inputRef.current?.focus()
    wasWaiting.current = !!waiting || (wasWaiting.current && thread.streaming)
  }, [waiting, thread.streaming])

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (canSend) void send(draft, images)
  }

  async function onPick(files: FileList | null) {
    if (!files?.length) return
    const { images: picked, errors } = await pickImages(Array.from(files), images.length)
    setImages((cur) => [...cur, ...picked].slice(0, MAX_IMAGES))
    setAttachErrors(errors)
    // 같은 파일을 지웠다가 다시 고를 수 있게 비웁니다.
    if (fileRef.current) fileRef.current.value = ''
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (canSend) void send(draft, images)
    }
  }

  return (
    <div className="chat">
      <nav className="chat__list" aria-label="대화 목록">
        <Button variant="primary" onClick={newConversation}>
          새 대화
        </Button>
        {convs.length === 0 ? (
          <p className="muted">아직 대화가 없습니다.</p>
        ) : (
          <ul>
            {convs.map((c) => (
              <li key={c.conversationId}>
                <button
                  type="button"
                  className="chat__item"
                  aria-current={selected?.conversationId === c.conversationId ? 'true' : undefined}
                  onClick={() => void open(c)}
                >
                  <span className="chat__item-title">{c.title ?? '새 대화'}</span>
                  <span className="muted">
                    {c.agentName ?? '에이전트 미정'}
                    {c.status === 'awaiting_approval' && ' · 승인 대기'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>

      <section className="chat__main" aria-label="대화">
        <div className="chat__head">
          {selected ? (
            <span className="row">
              <strong>{agentName ?? '에이전트 고르는 중'}</strong>
              {thread.route?.method && <Badge>{ROUTE_METHOD[thread.route.method]}</Badge>}
              {thread.route?.reason && <span className="muted">{thread.route.reason}</span>}
            </span>
          ) : (
            <label className="chat__agent">
              부서 에이전트
              <select value={agentChoice} onChange={(e) => setAgentChoice(e.target.value)}>
                <option value="">자동 선택</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {a.modelPolicy === 'local_only' ? ' (로컬 모델만)' : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div
          className="chat__log"
          ref={logRef}
          role="log"
          aria-live="polite"
          aria-busy={thread.streaming}
          onScroll={(e) => {
            const el = e.currentTarget
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          }}
        >
          {thread.items.length === 0 && (
            <p className="muted chat__empty">무엇을 도와드릴까요? 회의실 예약, 연차 규정처럼 물어보면 맞는 부서 에이전트가 답합니다.</p>
          )}
          {thread.items.map((it) => {
            switch (it.kind) {
              case 'user':
                return (
                  <div key={it.key} className="msg msg--user">
                    <span className="visually-hidden">나: </span>
                    {it.text}
                    {!!it.images?.length && (
                      <ul className="msg__images" aria-label={`첨부한 사진 ${it.images.length}장`}>
                        {it.images.map((img, i) => (
                          <li key={i}>
                            <img src={img.dataUrl} alt={img.name} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              case 'assistant':
                return <AssistantMessage key={it.key} item={it} />
              case 'tool':
                return <ToolCall key={it.key} item={it} />
              case 'approval':
                return (
                  <PreviewCard
                    key={it.key}
                    agentName={agentName}
                    approval={it.approval}
                    fromImage={it.fromImage}
                    decision={it.decision}
                    closed={it.closed}
                    busy={thread.streaming}
                    onDecide={(d) => void decide(it.approval.approvalId, d)}
                    onExpire={() => onExpire(it.approval.approvalId)}
                  />
                )
              case 'action':
                return <ActionCard key={it.key} item={it} onUndo={undo} />
              case 'blocked':
                return (
                  <div key={it.key} className="notice notice--blocked" role="status">
                    <Badge tone="danger">차단</Badge>
                    <span>{it.reason}</span>
                  </div>
                )
              case 'error':
                return (
                  <div key={it.key} className="notice notice--error" role="alert">
                    <span>{it.message}</span>
                    {it.retryable && lastUser?.kind === 'user' && canSend && (
                      <Button onClick={() => void send(lastUser.text, lastUser.images)}>다시 보내기</Button>
                    )}
                  </div>
                )
            }
          })}
        </div>

        <form className="chat__composer" onSubmit={onSubmit}>
          {notice && (
            <p role="alert" className="alert">
              {notice}
            </p>
          )}
          {waiting && <p className="muted">미리보기 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다.</p>}
          {attachErrors.map((m, i) => (
            <p key={i} role="alert" className="alert">
              {m}
            </p>
          ))}
          {images.length > 0 && (
            <ul className="attach" aria-label="보낼 사진">
              {images.map((img) => (
                <li key={img.id} className="attach__item">
                  <img src={img.dataUrl} alt="" />
                  <span className="attach__name">
                    {img.name} <span className="muted">{formatBytes(img.bytes)}</span>
                  </span>
                  <button
                    type="button"
                    className="attach__remove"
                    aria-label={`${img.name} 빼기`}
                    onClick={() => setImages((cur) => cur.filter((x) => x.id !== img.id))}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="chat__input">
            <label className="visually-hidden" htmlFor="chat-input">
              메시지
            </label>
            <textarea
              id="chat-input"
              ref={inputRef}
              rows={2}
              maxLength={4000}
              value={draft}
              placeholder="메시지를 입력합니다. Enter로 보내고 Shift+Enter로 줄을 바꿉니다."
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!!waiting}
            />
            <input
              ref={fileRef}
              id="chat-file"
              type="file"
              accept={IMAGE_TYPES.join(',')}
              multiple
              className="visually-hidden"
              tabIndex={-1}
              onChange={(e) => void onPick(e.target.files)}
            />
            <Button
              onClick={() => fileRef.current?.click()}
              disabled={!!waiting || images.length >= MAX_IMAGES}
              aria-describedby="chat-file-hint"
            >
              사진 첨부
            </Button>
            <span id="chat-file-hint" className="visually-hidden">
              JPEG·PNG, {MAX_IMAGES}장까지, 한 장 5MB까지
            </span>
            <Button type="submit" variant="primary" disabled={!canSend || (!draft.trim() && images.length === 0)}>
              보내기
            </Button>
          </div>
        </form>
      </section>
    </div>
  )
}
