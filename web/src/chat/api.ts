import { api, problemTitle } from '../api/client'
import { readSse } from './sse'
import type { ChatEvent } from './thread'

/**
 * 실패하면 status(HTTP, 연결 실패는 0)와 같은 요청을 다시 보내도 되는지를 함께 돌려줍니다.
 * 4xx는 요청 자체가 거절된 것이라 다시 보내지 않습니다.
 */
export type StreamResult = { ok: true } | { ok: false; message: string; status: number; retryable: boolean }

const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
const CUT = '응답이 중간에 끊겼습니다.'

type StreamResponse = { data?: ReadableStream<Uint8Array> | null; error?: unknown; response: Response }

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

async function pump(call: () => Promise<StreamResponse>, onEvent: (e: ChatEvent) => void): Promise<StreamResult> {
  let res: StreamResponse
  try {
    res = await call()
  } catch (e) {
    if (isAbort(e)) return { ok: true }
    return { ok: false, message: NETWORK, status: 0, retryable: true }
  }
  const { status } = res.response
  if (!res.response.ok || !res.data) {
    return { ok: false, message: problemTitle(res.error), status, retryable: status >= 500 }
  }
  const stream = res.data
  // 계약상 마지막 이벤트는 항상 done입니다. done 없이 닫히면 답이 잘린 것으로 봅니다.
  let sawDone = false
  try {
    for await (const msg of readSse(stream)) {
      let event: ChatEvent
      try {
        event = JSON.parse(msg.data) as ChatEvent
      } catch {
        return { ok: false, message: '서버 응답을 읽지 못했습니다.', status, retryable: false }
      }
      onEvent(event)
      if (event.type === 'done') {
        sawDone = true
        break
      }
    }
  } catch (e) {
    if (isAbort(e)) return { ok: true }
    return { ok: false, message: CUT, status, retryable: false }
  } finally {
    // 중간에 나왔으면 연결을 닫아 서버 쪽 실행도 멈추게 합니다.
    stream.cancel().catch(() => {})
  }
  return sawDone ? { ok: true } : { ok: false, message: CUT, status, retryable: false }
}

export function postMessage(
  conversationId: string,
  content: string,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
  images: { dataUrl: string }[] = [],
) {
  return pump(
    () =>
      api.POST('/conversations/{conversationId}/messages', {
        params: { path: { conversationId } },
        body: images.length ? { content, attachments: images.map((i) => ({ kind: 'image' as const, dataUrl: i.dataUrl })) } : { content },
        parseAs: 'stream',
        signal,
      }),
    onEvent,
  )
}

export function decideApproval(
  approvalId: string,
  decision: 'approve' | 'reject',
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
) {
  return pump(
    () =>
      api.POST('/execution-approvals/{approvalId}', {
        params: { path: { approvalId } },
        body: { decision },
        parseAs: 'stream',
        signal,
      }),
    onEvent,
  )
}

export type UndoResult = { ok: true } | { ok: false; message: string }

export async function undoAction(actionId: string, idempotencyKey: string): Promise<UndoResult> {
  try {
    const { response, error } = await api.POST('/actions/{actionId}/undo', {
      params: { path: { actionId }, header: { 'Idempotency-Key': idempotencyKey } },
    })
    return response.ok ? { ok: true } : { ok: false, message: problemTitle(error, '되돌리지 못했습니다.') }
  } catch {
    return { ok: false, message: NETWORK }
  }
}

/** 되돌리기 Idempotency-Key. crypto.randomUUID는 https에서만 있어 getRandomValues로 만듭니다. */
export function newIdempotencyKey(prefix: string): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}
