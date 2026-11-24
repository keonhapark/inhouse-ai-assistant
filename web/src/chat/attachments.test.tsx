import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'
import { MAX_BYTES, pickImages, toDataUrl } from './attachments'

function renderChat() {
  tokenStore.set('mock.emp-1001')
  render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
const JPEG = [0xff, 0xd8, 0xff, 0xe0]
function file(name: string, head: number[], bytes = 1024, type = 'image/png') {
  const b = new Uint8Array(Math.max(bytes, head.length))
  b.set(head)
  return new File([b], name, { type })
}
const png = (name = 'receipt.png', bytes = 1024) => file(name, PNG, bytes)
const fileInput = () => document.getElementById('chat-file') as HTMLInputElement

describe('채팅 사진 첨부', () => {
  it('사진을 붙이고 빼고, 사진만 보내면 미리보기 카드에 "이미지에서 읽은 값(확인 필요)"을 붙입니다', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post('*/api/conversations/:id/messages', async ({ request }) => {
        bodies.push(await request.clone().json())
        return undefined
      }),
    )
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.upload(fileInput(), [png('a.png'), png('receipt.png')])
    const list = await screen.findByRole('list', { name: '보낼 사진' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    await user.click(within(list).getByRole('button', { name: 'a.png 빼기' }))
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: '보내기' }))
    const card = await screen.findByRole('region', { name: '실행 전 확인: 경비 정산 상신' })
    expect(within(card).getByText('사진에서 읽은 값')).toBeInTheDocument()
    expect(within(card).getByText(/영수증과 맞는지 확인해 주세요/)).toBeInTheDocument()
    // 양식 필드 이름·원 단위·결재선(이름·직급·부서)만 보이고, API 원래 값은 "자세히" 안에 있습니다(#556)
    expect(await within(card).findByText('가맹점')).toBeInTheDocument()
    // 금액은 값 행에서 빼 맨 위에 크게 둡니다(명세 3.6). 사진은 값 옆에 둡니다
    expect(within(card).getByText('42,000원').closest('.sheet__amount')).not.toBeNull()
    expect(within(card).queryByText('금액')).toBeNull()
    expect(within(card).getByRole('img', { name: '첨부한 사진: receipt.png' })).toBeInTheDocument()
    expect(within(card).getByText('2026. 11. 20.(금)')).toBeInTheDocument()
    expect((await within(card).findByText('서도윤 팀장(인사팀)')).parentElement).toHaveTextContent('서도윤 팀장(인사팀) 결재 대기')
    expect(within(card).queryByText('requesterId', { selector: '.rows dt' })).toBeNull()
    expect(within(card).getByText('자세히').closest('details')).toHaveTextContent('requesterId')
    expect(screen.getByRole('list', { name: '첨부한 사진 1장' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'receipt.png' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '보낼 사진' })).toBeNull()

    const body = bodies[0] as { content: string; attachments: { kind: string; dataUrl: string }[] }
    expect(body.content).toBe('사진을 첨부했습니다.')
    expect(body.attachments).toHaveLength(1)
    expect(body.attachments[0].kind).toBe('image')
    expect(body.attachments[0].dataUrl).toMatch(/^data:image\/png;base64,/)

    await user.click(within(card).getByRole('button', { name: '경비 정산 상신' }))
    const done = await screen.findByRole('region', { name: '완료한 일' })
    // 결재 문서를 만든 일은 결재 문서 보기(기안함)와 실행 취소를 붙입니다
    expect(within(done).getByRole('link', { name: '결재 문서 보기' })).toHaveAttribute('href', '/approvals?box=outbox')
    expect(within(done).getByRole('button', { name: '실행 취소' })).toBeInTheDocument()
    // 승인한 시트는 완료한 일 행으로 바뀝니다(같은 상태를 두 번 보이지 않음)
    expect(card).not.toBeInTheDocument()
  })

  it('사진 없이 보낸 턴의 카드에는 확인 필요 표시가 없습니다', async () => {
    const user = renderChat()
    await user.type(await screen.findByLabelText('메시지'), '결재 회수{Enter}')
    const card = await screen.findByRole('region', { name: '실행 전 확인: 결재 회수' })
    expect(within(card).queryByText('사진에서 읽은 값')).toBeNull()
  })

  it('형식이 다르거나 5MB를 넘거나 3장을 넘으면 붙이지 않고 이유를 알립니다', async () => {
    renderChat()
    await screen.findByLabelText('메시지')
    const gif = file('x.gif', [0x47, 0x49, 0x46, 0x38], 10, 'image/gif')
    const big = png('big.png', MAX_BYTES + 1)
    fireEvent.change(fileInput(), { target: { files: [gif, big, png('1.png'), png('2.png'), png('3.png'), png('4.png')] } })
    await screen.findByText(/x\.gif:/)
    const text = document.querySelector('.attach__errors')!.textContent!
    expect(text).toContain('x.gif: JPEG·PNG 사진만 붙일 수 있습니다.')
    expect(text).toContain('big.png: 5MB보다 큰 사진은 붙일 수 없습니다.')
    expect(text).toContain('1장은 붙이지 않았습니다. 사진은 한 번에 3장까지 붙일 수 있습니다.')
    expect(within(screen.getByRole('list', { name: '보낼 사진' })).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '사진 첨부' })).toBeDisabled()
  })

  it('gateway가 413으로 거절하면 problem title을 보여 줍니다', async () => {
    server.use(
      http.post('*/api/conversations/:id/messages', () =>
        HttpResponse.json({ type: 'urn:problem:payload-too-large', title: '이미지 한 장은 5MB까지입니다.', status: 413 }, { status: 413, headers: { 'Content-Type': 'application/problem+json' } }),
      ),
    )
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.upload(fileInput(), png())
    await user.click(screen.getByRole('button', { name: '보내기' }))
    expect(await screen.findByText('이미지 한 장은 5MB까지입니다.')).toBeInTheDocument()
  })
})

describe('채팅 사진 첨부(기록·추정·되돌리기)', () => {
  const approval = (fromAttachments?: boolean) => ({
    type: 'approval_required', conversationId: 'c1', seq: 2,
    approval: { approvalId: 'ap-x', tool: 'expense_request', toolLabel: '경비 정산 상신', risk: 'reversible_write',
      expiresAt: '2999-01-01T00:00:00Z', ...(fromAttachments === undefined ? {} : { fromAttachments }),
      preview: { dryRun: true, operation: 'x', summary: '경비 정산', changes: [], undoable: true } },
  })

  it('지난 대화를 열면 사진 수만 보이고, gateway의 fromAttachments로 확인 필요를 붙입니다', async () => {
    const summary = { conversationId: 'c1', agentId: 'finance', agentName: '재무', title: '영수증', status: 'awaiting_approval', createdAt: '2026-11-21T10:00:00Z', updatedAt: '2026-11-21T10:00:00Z' }
    server.use(
      http.get('*/api/conversations', () => HttpResponse.json({ items: [summary] })),
      http.get('*/api/conversations/c1', () =>
        HttpResponse.json({ ...summary, events: [
          { type: 'user_message', content: '영수증', at: '2026-11-21T10:00:00Z', attachments: [{ kind: 'image', mediaType: 'image/png', bytes: 1000, sha256: '0'.repeat(64) }] },
          approval(true),
        ] }),
      ),
    )
    const user = renderChat()
    const list = await screen.findByRole('navigation', { name: '대화 목록' })
    await user.click(await within(list).findByRole('button', { name: /영수증/ }))
    expect(await screen.findByText('사진 1장 첨부 · 사진은 기록에 남기지 않습니다')).toBeInTheDocument()
    const card = screen.getByRole('region', { name: '실행 전 확인: 경비 정산 상신' })
    expect(within(card).getByText('사진에서 읽은 값')).toBeInTheDocument()
  })

  it.each([undefined, false])('fromAttachments가 %s여도 마지막 카드 뒤에 사진을 보낸 적이 있으면 확인 필요를 붙입니다(되묻고 글로 답한 턴)', async (fromAttachments) => {
    let n = 0
    server.use(
      http.post('*/api/conversations/:id/messages', () => {
        n++
        const events = n === 1
          ? [{ type: 'message', conversationId: 'c', seq: 0, text: '분류가 식대 맞나요?' }, { type: 'done', conversationId: 'c', seq: 1 }]
          : [approval(fromAttachments), { type: 'done', conversationId: 'c', seq: 3 }]
        return new HttpResponse(events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
      }),
    )
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.upload(fileInput(), png())
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findByText('분류가 식대 맞나요?')
    await user.type(screen.getByLabelText('메시지'), '네{Enter}')
    const card = await screen.findByRole('region', { name: '실행 전 확인: 경비 정산 상신' })
    expect(within(card).getByText('사진에서 읽은 값')).toBeInTheDocument()
  })

  it('사진이 거절되면(413) 입력하던 글과 사진을 되돌리고, 사진 없이 보낼 때는 attachments를 싣지 않습니다', async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post('*/api/conversations/:id/messages', async ({ request }) => {
        const body = (await request.clone().json()) as Record<string, unknown>
        bodies.push(body)
        if (body.attachments) {
          return HttpResponse.json({ type: 'urn:problem:payload-too-large', title: '이미지 한 장은 5MB까지입니다.', status: 413 }, { status: 413, headers: { 'Content-Type': 'application/problem+json' } })
        }
        return undefined
      }),
    )
    const user = renderChat()
    await user.type(await screen.findByLabelText('메시지'), '영수증 올려 줘')
    await user.upload(fileInput(), png('r.png'))
    await user.click(screen.getByRole('button', { name: '보내기' }))
    expect(await screen.findByText('이미지 한 장은 5MB까지입니다.')).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toHaveValue('영수증 올려 줘')
    expect(within(screen.getByRole('list', { name: '보낼 사진' })).getAllByRole('listitem')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'r.png 빼기' }))
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findAllByText('영수증 올려 줘')
    expect(bodies.at(-1)).not.toHaveProperty('attachments')
  })

  it('빼기를 누르면 다음 빼기 버튼, 없으면 사진 첨부 버튼으로 포커스가 갑니다', async () => {
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.upload(fileInput(), [png('a.png'), png('b.png')])
    await user.click(await screen.findByRole('button', { name: 'a.png 빼기' }))
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'b.png 빼기' })).toHaveFocus())
    await user.click(screen.getByRole('button', { name: 'b.png 빼기' }))
    await vi.waitFor(() => expect(screen.getByRole('button', { name: '사진 첨부' })).toHaveFocus())
  })

  it('스트림이 끊겨 다시 보내면 사진도 다시 실립니다', async () => {
    let n = 0
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post('*/api/conversations/:id/messages', async ({ request }) => {
        bodies.push((await request.clone().json()) as Record<string, unknown>)
        n++
        return n === 1
          ? HttpResponse.json({ type: 'urn:problem:upstream', title: '모델 서버가 응답하지 않습니다.', status: 503 }, { status: 503, headers: { 'Content-Type': 'application/problem+json' } })
          : undefined
      }),
    )
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.upload(fileInput(), png())
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await user.click(await screen.findByRole('button', { name: '다시 시도' }))
    await screen.findByRole('region', { name: '실행 전 확인: 경비 정산 상신' })
    expect((bodies[1].attachments as unknown[]).length).toBe(1)
  })
})

describe('pickImages', () => {
  it('이미 붙인 수를 세어 3장까지만 받고, 뺀 장수를 알립니다', async () => {
    const { images, errors } = await pickImages([png('a.png'), png('b.png')], 2)
    expect(images.map((i) => i.name)).toEqual(['a.png'])
    expect(errors).toEqual(['1장은 붙이지 않았습니다. 사진은 한 번에 3장까지 붙일 수 있습니다.'])
  })

  it('형식은 파일 앞 바이트로 봅니다(MIME이 비거나 image/jpg여도 JPEG면 받고, HEIC는 따로 안내)', async () => {
    const { images, errors } = await pickImages(
      [file('a.jpg', JPEG, 100, ''), file('b.jpeg', JPEG, 100, 'image/jpg'), file('c.heic', [0, 0, 0, 0x18, ...'ftypheic'.split('').map((c) => c.charCodeAt(0))], 100, 'image/heic'), file('d.png', [1, 2, 3, 4], 100)],
      0,
    )
    expect(images.map((i) => [i.name, i.mediaType])).toEqual([
      ['a.jpg', 'image/jpeg'],
      ['b.jpeg', 'image/jpeg'],
    ])
    expect(errors[0]).toContain('c.heic: HEIC 사진은 붙일 수 없습니다.')
    expect(errors[1]).toBe('d.png: JPEG·PNG 사진만 붙일 수 있습니다.')
  })

  it('보낼 때 만드는 data URL의 머리는 바이트로 본 형식입니다', async () => {
    const { images } = await pickImages([file('x.jpg', JPEG, 100, 'image/jpg')], 0)
    expect(await toDataUrl(images[0])).toMatch(/^data:image\/jpeg;base64,\/9j\//)
  })
})
