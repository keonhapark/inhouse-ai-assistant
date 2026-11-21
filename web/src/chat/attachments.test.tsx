import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'
import { MAX_BYTES, pickImages } from './attachments'

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

const png = (name = 'receipt.png', bytes = 1024) => new File([new Uint8Array(bytes)], name, { type: 'image/png' })
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
    const card = await screen.findByRole('region', { name: '실행 미리보기: 경비 정산' })
    expect(within(card).getByText('이미지에서 읽은 값(확인 필요)')).toBeInTheDocument()
    expect(within(card).getByText(/사진과 맞는지 확인한 뒤 실행해 주세요/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '첨부한 사진 1장' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'receipt.png' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '보낼 사진' })).toBeNull()

    const body = bodies[0] as { content: string; attachments: { kind: string; dataUrl: string }[] }
    expect(body.content).toBe('사진을 첨부했습니다.')
    expect(body.attachments).toHaveLength(1)
    expect(body.attachments[0].kind).toBe('image')
    expect(body.attachments[0].dataUrl).toMatch(/^data:image\/png;base64,/)

    await user.click(within(card).getByRole('button', { name: '실행' }))
    expect(await screen.findByRole('region', { name: '실행한 일' })).toBeInTheDocument()
  })

  it('사진 없이 보낸 턴의 카드에는 확인 필요 표시가 없습니다', async () => {
    const user = renderChat()
    await user.type(await screen.findByLabelText('메시지'), '결재 회수{Enter}')
    const card = await screen.findByRole('region', { name: '실행 미리보기: 결재 회수' })
    expect(within(card).queryByText('이미지에서 읽은 값(확인 필요)')).toBeNull()
  })

  it('형식이 다르거나 5MB를 넘거나 3장을 넘으면 붙이지 않고 이유를 알립니다', async () => {
    renderChat()
    await screen.findByLabelText('메시지')
    const gif = new File([new Uint8Array(10)], 'x.gif', { type: 'image/gif' })
    const big = png('big.png', MAX_BYTES + 1)
    fireEvent.change(fileInput(), { target: { files: [gif, big, png('1.png'), png('2.png'), png('3.png'), png('4.png')] } })
    const alerts = await screen.findAllByRole('alert')
    const text = alerts.map((a) => a.textContent).join('\n')
    expect(text).toContain('x.gif: JPEG·PNG 사진만 붙일 수 있습니다.')
    expect(text).toContain('big.png: 5MB보다 큰 사진은 붙일 수 없습니다.')
    expect(text).toContain('사진은 한 번에 3장까지 붙일 수 있습니다.')
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

describe('pickImages', () => {
  it('이미 붙인 수를 세어 3장까지만 받습니다', async () => {
    const { images, errors } = await pickImages([png('a.png'), png('b.png')], 2)
    expect(images.map((i) => i.name)).toEqual(['a.png'])
    expect(errors).toEqual(['사진은 한 번에 3장까지 붙일 수 있습니다.'])
  })
})
