import * as Menu from '@radix-ui/react-dropdown-menu'
import { ArrowUp, Check, ChevronDown, Paperclip, Sparkles, SquarePen, TriangleAlert, X } from 'lucide-react'
import { useCallback, useEffect, useEffectEvent, useLayoutEffect, useReducer, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Button } from '../components/Button'
import { conversationRow } from '../display/conversation'
import { agentLabel } from '../display/names'
import { NEW_CHAT } from '../shell/events'
import { Toolbar } from '../shell/Toolbar'
import { decideApproval, postMessage, undoAction, type StreamResult } from './api'
import { ACCEPT, formatBytes, MAX_IMAGES, pickImages, release, toDataUrl, type PickedImage } from './attachments'
import { ActionCard, AssistantMessage, PreviewCard, ToolSteps, type AnswerHead } from './parts'
import { emptyThread, pendingApproval, threadReducer, type ChatEvent, type ThreadItem } from './thread'
import './chat.css'

type Summary = Schemas['ConversationSummary']
type AgentInfo = Schemas['AgentInfo']

const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'

type ToolItem = Extract<ThreadItem, { kind: 'tool' }>
/** 화면에 그릴 줄: 이어서 온 도구 줄은 "처리 과정" 하나로 묶고, 한 턴의 첫 답에는 답 머리를 붙입니다 */
type Row = Exclude<ThreadItem, ToolItem> | { kind: 'tools'; key: string; calls: ToolItem['call'][] }

type Photo = { url: string; name: string }

function rowsOf(items: ThreadItem[]): { rows: Row[]; heads: Map<string, 'local' | 'external' | undefined>; photos: Map<string, Photo> } {
  const rows: Row[] = []
  const heads = new Map<string, 'local' | 'external' | undefined>()
  // 확인 시트 옆에 둘 사진: 그 카드 앞에서 마지막으로 보낸 사진(이 화면에서 보낸 것만 있음)
  const photos = new Map<string, Photo>()
  let lastPhoto: Photo | undefined
  let turnHead: string | null = null
  for (const it of items) {
    if (it.kind === 'user') {
      turnHead = null
      if (it.images?.length || it.attachmentCount) lastPhoto = it.images?.[0]
    }
    if (it.kind === 'approval' && lastPhoto) photos.set(it.key, lastPhoto)
    // 승인한 확인 시트는 뒤따르는 완료한 일 행으로 바뀝니다(명세 3.6). 완료한 일이 오면 시트를 뺍니다
    if (it.kind === 'action') {
      const sheet = rows.findLastIndex((x) => x.kind === 'approval' || x.kind === 'user')
      if (sheet >= 0) {
        const x = rows[sheet]
        if (x.kind === 'approval' && x.decision === 'approve') rows.splice(sheet, 1)
      }
    }
    if (it.kind === 'tool') {
      const last = rows[rows.length - 1]
      if (last?.kind === 'tools') last.calls.push(it.call)
      else rows.push({ kind: 'tools', key: it.key, calls: [it.call] })
      continue
    }
    if (it.kind === 'assistant') {
      if (turnHead === null) {
        turnHead = it.key
        heads.set(it.key, undefined)
      }
      // 사내 처리 여부는 턴에 한 번만 보입니다. 모델 정보는 답이 끝나야 오므로 턴의 어느 답에서든 가져옵니다
      if (it.model?.location && !heads.get(turnHead)) heads.set(turnHead, it.model.location)
    }
    rows.push(it)
  }
  return { rows, heads, photos }
}

export function ChatPage() {
  const [convs, setConvs] = useState<Summary[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentChoice, setAgentChoice] = useState('')
  const [selected, setSelected] = useState<Summary | null>(null)
  const [thread, dispatch] = useReducer(threadReducer, emptyThread)
  const [draft, setDraft] = useState('')
  // 보내기 전 붙인 사진과 붙이지 못한 이유
  const [images, setImagesState] = useState<PickedImage[]>([])
  const [attachErrors, setAttachErrors] = useState<string[]>([])
  // 사진을 읽는 동안에는 보내기와 첨부를 막습니다(읽기 전에 보내면 사진이 다음 메시지로 딸려 감).
  const [reading, setReading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const attachRef = useRef<HTMLButtonElement>(null)
  const attachListRef = useRef<HTMLUListElement>(null)
  // 연달아 고를 때 남은 칸을 옛 값으로 세지 않도록 지금 붙인 사진을 ref로도 둡니다.
  const imagesRef = useRef<PickedImage[]>([])
  const setImages = (next: PickedImage[]) => {
    imagesRef.current = next
    setImagesState(next)
  }
  // 이 화면에서 보낸 사진의 object URL(말풍선 표시용). 대화를 바꾸면 풉니다.
  const sentUrls = useRef<{ url: string }[]>([])
  // 마지막으로 보낸 사진(다시 보내기용). 화면에서 보낸 메시지에만 있습니다.
  const lastSent = useRef<PickedImage[]>([])
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
    clearAttachments()
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

  /** 대화를 바꿀 때 붙여 둔 사진·오류를 비우고 보낸 사진의 object URL을 풉니다(다른 대화로 사진이 딸려 가지 않게). */
  function clearAttachments() {
    release(imagesRef.current)
    setImages([])
    setAttachErrors([])
    release(sentUrls.current)
    sentUrls.current = []
    lastSent.current = []
  }

  function newConversation() {
    clearAttachments()
    abort.current?.abort()
    epoch.current++
    stick.current = true
    opening.current = null
    setSelected(null)
    setNotice(null)
    dispatch({ type: 'reset' })
  }

  // 명령 팔레트의 "새 대화"(이 화면에 있을 때)
  const onNewChat = useEffectEvent(newConversation)
  useEffect(() => {
    const on = () => onNewChat()
    window.addEventListener(NEW_CHAT, on)
    return () => window.removeEventListener(NEW_CHAT, on)
  }, [])

  /** 사진만 보낼 때 메시지 본문(계약상 content는 필수입니다) */
  const IMAGE_ONLY = '사진을 첨부했습니다.'

  async function send(text: string, imgs: PickedImage[] = []) {
    const content = text.trim() || (imgs.length ? IMAGE_ONLY : '')
    if (!content) return
    let dataUrls: { dataUrl: string }[]
    try {
      dataUrls = await Promise.all(imgs.map(async (i) => ({ dataUrl: await toDataUrl(i) })))
    } catch {
      setAttachErrors(['사진을 읽지 못해 보내지 않았습니다. 사진을 빼고 다시 첨부하세요.'])
      return
    }
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
    sentUrls.current.push(...imgs)
    lastSent.current = imgs
    dispatch({ type: 'user', text: content, images: imgs.map(({ name, url }) => ({ name, url })) })
    const signal = startStream()
    const result = await postMessage(conv.conversationId, content, onEvent, signal, dataUrls)
    // 사진이 거절됐으면(크기·형식·장수) 입력하던 글과 사진을 되돌려 고쳐 보내게 합니다.
    if (!result.ok && [413, 415, 422].includes(result.status) && imgs.length && imagesRef.current.length === 0) {
      setDraft((cur) => cur || (content === IMAGE_ONLY ? '' : content))
      setImages(imgs)
    }
    await finishStream(result)
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
  const canSend = !thread.streaming && !waiting && !creating && !reading
  // 사진 목록을 바꿀 수 있는 때(보내는 중·대화를 만드는 중·승인 대기에는 막음)
  const canAttach = !thread.streaming && !waiting && !creating && !reading

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
    if (!files?.length || reading) return
    const list = Array.from(files)
    // 같은 파일을 지웠다가 다시 고를 수 있게 비웁니다.
    if (fileRef.current) fileRef.current.value = ''
    const started = epoch.current
    setReading(true)
    try {
      const { images: picked, errors } = await pickImages(list, imagesRef.current.length)
      // 읽는 사이 대화를 바꿨으면 버립니다.
      if (epoch.current !== started) return release(picked)
      setImages([...imagesRef.current, ...picked].slice(0, MAX_IMAGES))
      setAttachErrors(errors)
    } finally {
      setReading(false)
    }
  }

  function removeImage(id: string, index: number) {
    const gone = imagesRef.current.find((x) => x.id === id)
    if (gone) release([gone])
    const next = imagesRef.current.filter((x) => x.id !== id)
    setImages(next)
    setAttachErrors([])
    // 누른 버튼이 사라지므로 다음(없으면 앞) 빼기 버튼, 사진이 없으면 첨부 버튼으로 포커스를 옮깁니다.
    requestAnimationFrame(() => {
      const buttons = attachListRef.current?.querySelectorAll<HTMLButtonElement>('button')
      const target = buttons?.[Math.min(index, (buttons?.length ?? 1) - 1)]
      ;(target ?? attachRef.current ?? inputRef.current)?.focus()
    })
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (canSend) void send(draft, images)
    }
  }

  const current = selected ? (convs.find((c) => c.conversationId === selected.conversationId) ?? selected) : null
  const title = current?.title ?? '새 대화'
  const agent = agentName ? agentLabel(agentName) : undefined
  const chosen = agents.find((a) => a.id === agentChoice)
  const { rows, heads, photos } = rowsOf(thread.items)
  const route = thread.route
  const routeNote =
    route?.method === 'fallback'
      ? `맞는 담당 AI가 없어 ${agent ?? '기본 담당 AI'}가 답합니다.`
      : route?.method && route.method !== 'explicit'
        ? route.reason
        : null

  return (
    <div className="chat">
      <nav className="convs" aria-label="대화 목록">
        <div className="convs__head">
          <h2>대화</h2>
          <button type="button" className="icon-btn" aria-label="새 대화" onClick={newConversation}>
            <SquarePen aria-hidden />
          </button>
        </div>
        {convs.length === 0 ? (
          <p className="convs__empty">아직 대화가 없습니다. 무엇을 할지 적어 보세요.</p>
        ) : (
          <ul>
            {convs.map((c) => {
              const r = conversationRow(c)
              return (
                <li key={c.conversationId}>
                  <button
                    type="button"
                    className="conv"
                    aria-current={selected?.conversationId === c.conversationId ? 'true' : undefined}
                    onClick={() => void open(c)}
                  >
                    <span className="conv__title">{c.title ?? '새 대화'}</span>
                    <span className="conv__when">{r.when}</span>
                    <span className="conv__sub">
                      {r.agent}
                      {r.status && <span className={`status status--${r.status.tone}`}>{r.status.label}</span>}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </nav>

      <main className="chat__main" aria-labelledby="chat-title">
        <Toolbar title={title} titleId="chat-title" sub={selected ? (agent ?? '담당 AI 정하는 중') : undefined}>
          {selected && routeNote && (
            <details key={selected.conversationId} className="route">
              <summary>자동 선택</summary>
              <p>{routeNote}</p>
            </details>
          )}
        </Toolbar>

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
          <div className="col">
            {thread.items.length === 0 && <p className="chat__empty">무엇을 할지 적어 보세요. 회의실 예약, 경비 정산, 규정 질문을 맞는 담당 AI가 맡습니다.</p>}
            {rows.map((it) => {
              switch (it.kind) {
                case 'user':
                  return (
                    <div key={it.key} className="msg msg--user">
                      <span className="visually-hidden">나: </span>
                      {it.text}
                      {it.images?.length ? (
                        <ul className="msg__images" aria-label={`첨부한 사진 ${it.images.length}장`}>
                          {it.images.map((img, i) => (
                            <li key={i}>
                              <img src={img.url} alt={img.name} />
                            </li>
                          ))}
                        </ul>
                      ) : (it.attachmentCount ?? 0) > 0 ? (
                        <small className="msg__attached">
                          <Paperclip aria-hidden />
                          사진 {it.attachmentCount}장 첨부 · 사진은 기록에 남기지 않습니다
                        </small>
                      ) : null}
                    </div>
                  )
                case 'assistant': {
                  const head: AnswerHead | undefined = heads.has(it.key) ? { agent: agent ?? '담당 AI', location: heads.get(it.key) } : undefined
                  return <AssistantMessage key={it.key} item={it} head={head} />
                }
                case 'tools':
                  return <ToolSteps key={it.key} calls={it.calls} />
                case 'approval':
                  return (
                    <PreviewCard
                      key={it.key}
                      approval={it.approval}
                      fromImage={it.fromImage}
                      photo={photos.get(it.key)}
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
                      <TriangleAlert aria-hidden />
                      <div>
                        <b>처리할 수 없는 요청</b>
                        <p>{it.reason}</p>
                      </div>
                    </div>
                  )
                case 'error':
                  return (
                    <div key={it.key} className="notice notice--error" role="alert">
                      <TriangleAlert aria-hidden />
                      <span>{it.message}</span>
                      {it.retryable &&
                        lastUser?.kind === 'user' &&
                        canSend &&
                        // 복원한 기록의 사진은 본문이 없어 다시 보낼 수 없습니다.
                        ((lastUser.attachmentCount ?? 0) > 0 && !lastUser.images?.length ? (
                          <span className="muted">사진을 다시 첨부해 보내 주세요.</span>
                        ) : (
                          <Button onClick={() => void send(lastUser.text, lastUser.images?.length ? lastSent.current : [])}>다시 시도</Button>
                        ))}
                    </div>
                  )
              }
            })}
          </div>
        </div>

        <div className="col chat__bottom">
          {notice && (
            <p role="alert" className="alert">
              {notice}
            </p>
          )}
          {waiting && <p className="chat__hint">위 확인 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다.</p>}
          <div role="status" aria-live="polite" className="attach__errors">
            {attachErrors.map((m) => (
              <p key={m} className="alert">
                {m}
              </p>
            ))}
          </div>
          <form className="composer" onSubmit={onSubmit}>
            {images.length > 0 && (
              <ul className="attach" aria-label="보낼 사진" ref={attachListRef}>
                {images.map((img, i) => (
                  <li key={img.id} className="attach__item">
                    <img src={img.url} alt="" />
                    <span className="attach__name">
                      {img.name} <span className="muted">{formatBytes(img.bytes)}</span>
                    </span>
                    <button
                      type="button"
                      className="attach__remove"
                      aria-label={`${img.name} 빼기`}
                      disabled={!canAttach}
                      onClick={() => removeImage(img.id, i)}
                    >
                      <X aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <label className="visually-hidden" htmlFor="chat-input">
              메시지
            </label>
            <textarea
              id="chat-input"
              ref={inputRef}
              rows={2}
              maxLength={4000}
              value={draft}
              placeholder="예: 다음 주 화요일 오후에 6명 들어갈 회의실 잡아 줘"
              aria-describedby="chat-input-hint"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!!waiting}
            />
            <span id="chat-input-hint" className="visually-hidden">
              Enter로 보내고 Shift+Enter로 줄을 바꿉니다.
            </span>
            <div className="composer__bar">
              <input ref={fileRef} id="chat-file" type="file" accept={ACCEPT} multiple hidden onChange={(e) => void onPick(e.target.files)} />
              <button
                ref={attachRef}
                type="button"
                className="chip"
                onClick={() => fileRef.current?.click()}
                disabled={!canAttach || images.length >= MAX_IMAGES}
                aria-describedby="chat-file-hint"
              >
                <Paperclip aria-hidden />
                {reading ? '사진 읽는 중' : '사진 첨부'}
              </button>
              <span id="chat-file-hint" className="visually-hidden">
                JPEG·PNG, {MAX_IMAGES}장까지, 한 장 5MB까지
              </span>
              {!selected && (
                <Menu.Root>
                  <Menu.Trigger className="chip" aria-label={`담당 AI: ${chosen ? agentLabel(chosen.name) : '자동 선택'}`}>
                    <Sparkles aria-hidden />
                    {chosen ? agentLabel(chosen.name) : '자동 선택'}
                    <ChevronDown aria-hidden />
                  </Menu.Trigger>
                  <Menu.Portal>
                    <Menu.Content className="menu" side="top" align="start" sideOffset={6}>
                      <Menu.Label className="menu__label">담당 AI</Menu.Label>
                      <Menu.RadioGroup value={agentChoice} onValueChange={setAgentChoice}>
                        {[{ id: '', label: '자동 선택', local: false }, ...agents.map((a) => ({ id: a.id, label: agentLabel(a.name), local: a.modelPolicy === 'local_only' }))].map(
                          (o) => (
                            <Menu.RadioItem key={o.id || 'auto'} value={o.id} className="menu__item">
                              <Menu.ItemIndicator className="menu__check">
                                <Check aria-hidden />
                              </Menu.ItemIndicator>
                              {o.label}
                              {o.local && <span className="menu__hint">사내 처리만</span>}
                            </Menu.RadioItem>
                          ),
                        )}
                      </Menu.RadioGroup>
                    </Menu.Content>
                  </Menu.Portal>
                </Menu.Root>
              )}
              <span className="composer__spacer" />
              <button type="submit" className="send" aria-label="보내기" disabled={!canSend || (!draft.trim() && images.length === 0)}>
                <ArrowUp aria-hidden />
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  )
}
