import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

// 서도윤(emp-2001, 인사팀장)으로 로그인합니다. 모의 데이터는 src/mocks/inbox.ts입니다.
function renderInbox(path = '/inbox') {
  tokenStore.set('mock.emp-2001')
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const problemJson = (status: number, code: string, title: string) =>
  HttpResponse.json({ type: `urn:problem:${code}`, title, status }, { status, headers: { 'Content-Type': 'application/problem+json' } })

async function openDoc(user: ReturnType<typeof userEvent.setup>, title: string) {
  // 행 단추의 이름은 보이는 글자 전부(제목 → 양식·기안자 → 상태·언제)라 제목으로 시작하는지만 봅니다
  await user.click(await screen.findByRole('button', { name: (n) => n.startsWith(`${title} `) }))
  return screen.findByRole('region', { name: `결재 문서: ${title}` })
}

/** 승인 버튼을 누르고 확인 팝오버에서 다시 승인합니다(명세 3.7) */
async function approve(user: ReturnType<typeof userEvent.setup>, doc: HTMLElement) {
  await user.click(within(doc).getByRole('button', { name: '승인' }))
  const pop = await screen.findByRole('dialog', { name: /승인할까요/ })
  await user.click(within(pop).getByRole('button', { name: '승인' }))
}

describe('팀장 승인함', () => {
  it('주소의 ?box=로 처음 열 칸을 고릅니다(채팅의 결재 문서 보기)', async () => {
    renderInbox('/approvals?box=outbox')
    expect(await screen.findByRole('tab', { name: '기안함' })).toHaveAttribute('aria-selected', 'true')
  })

  it('결재 대기 문서를 열어 결재선을 보고, 확인 팝오버를 거쳐 승인하면 결재 완료로 옮겨 갑니다', async () => {
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(doc).getAllByText('한지우').length).toBeGreaterThan(0)
    // 양식 스키마의 title·x-labels로 필드를 보여 줍니다.
    expect(within(doc).getByText('종류')).toBeInTheDocument()
    expect(within(doc).getByText('연차')).toBeInTheDocument()
    expect(within(doc).getByText('2026. 11. 27.(금)')).toBeInTheDocument()
    const line = within(doc).getByRole('list', { name: '결재선' })
    expect(within(line).getByText('서도윤')).toBeInTheDocument()
    expect(within(line).getByText('결재 대기')).toBeInTheDocument()

    await user.type(within(doc).getByLabelText(/의견/), '잘 다녀오세요')
    await user.click(within(doc).getByRole('button', { name: '승인' }))
    const pop = await screen.findByRole('dialog', { name: '휴가 신청을 승인할까요?' })
    expect(within(pop).getByText('승인하면 결재가 끝나고, 승인은 취소할 수 없습니다.')).toBeInTheDocument()
    // 초점은 팝오버 안 첫 버튼(취소)에 둡니다
    await vi.waitFor(() => expect(within(pop).getByRole('button', { name: '취소' })).toHaveFocus())
    await user.click(within(pop).getByRole('button', { name: '승인' }))
    expect(await screen.findByRole('status')).toHaveTextContent('연차 휴가 신청(11/27~11/28)을 승인했습니다.')
    // 결재한 뒤에는 목록의 다음 문서가 열리고 그 제목으로 초점이 갑니다
    const next = await screen.findByRole('region', { name: '결재 문서: 팀 점심 식대' })
    expect(within(next).getByRole('heading', { name: '팀 점심 식대' })).toHaveFocus()
    expect(within(next).getByText('42,000원')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '결재 완료' }))
    const done = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(done).getByText('“잘 다녀오세요”')).toBeInTheDocument()
    expect(within(done).queryByRole('button', { name: '승인' })).toBeNull()
  })

  it('대결 대기는 원 결재자를 적고 대신 결재한다고 알리며, 반려는 반려 사유가 있어야 합니다', async () => {
    const user = renderInbox()
    await user.click(await screen.findByRole('tab', { name: /^대결 대기/ }))
    expect(await screen.findByText(/윤서진 대신/)).toBeInTheDocument()
    const doc = await openDoc(user, '11월 출장 경비 정산')
    expect(within(doc).getByText(/윤서진님 대신 결재합니다/)).toBeInTheDocument()
    expect(within(doc).getByText('320,000원')).toBeInTheDocument()
    expect(within(doc).getByRole('button', { name: '반려' })).toBeDisabled()
    await user.type(within(doc).getByLabelText(/의견/), '영수증을 다시 붙여 주세요')
    await user.click(within(doc).getByRole('button', { name: '반려' }))
    expect(await screen.findByRole('status')).toHaveTextContent('반려했습니다')
  })

  it('버전이 어긋나 409가 오면 problem title을 보여 주고 문서를 다시 불러옵니다', async () => {
    server.use(http.post('*/api/inbox/:id/approve', () => problemJson(409, 'version-conflict', '다른 사람이 먼저 바꿨습니다.')))
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    await approve(user, doc)
    expect(await within(doc).findByRole('alert')).toHaveTextContent('다른 사람이 먼저 바꿨습니다.')
    expect(screen.getByRole('region', { name: '결재 문서: 연차 휴가 신청(11/27~11/28)' })).toBeInTheDocument()
    // 실패하면 초점이 사라지지 않고 승인 버튼으로 돌아옵니다
    await vi.waitFor(() => expect(within(doc).getByRole('button', { name: '승인' })).toHaveFocus())
  })

  it('기안함의 문서는 결재 버튼이 없습니다', async () => {
    const user = renderInbox()
    await user.click(await screen.findByRole('tab', { name: '기안함' }))
    const doc = await openDoc(user, '교육용 노트북 2대 구매')
    expect(within(doc).getByText('임채원')).toBeInTheDocument()
    expect(within(doc).queryByRole('button', { name: '승인' })).toBeNull()
  })

  it('화살표 키로 탭을 옮깁니다', async () => {
    const user = renderInbox()
    const first = await screen.findByRole('tab', { name: /^결재 대기/ })
    first.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: /^대결 대기/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /^대결 대기/ })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: '기안함' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('리뷰에서 고친 것', () => {
  it('같은 결정·의견을 다시 보낼 때만 같은 멱등 키를 씁니다', async () => {
    const keys: string[] = []
    server.use(
      http.post('*/api/inbox/:id/approve', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key') ?? '')
        return problemJson(503, 'unavailable', '잠시 뒤 다시 시도해 주세요.')
      }),
    )
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    await approve(user, doc)
    await within(doc).findByRole('alert')
    await approve(user, doc)
    await user.type(within(doc).getByLabelText(/의견/), '확인')
    await approve(user, doc)
    await within(doc).findByRole('alert')
    expect(keys).toHaveLength(3)
    expect(keys[1]).toBe(keys[0])
    expect(keys[2]).not.toBe(keys[0])
  })

  it('409 뒤 다시 불러오기도 실패하면 그 사실을 함께 알립니다', async () => {
    server.use(
      http.post('*/api/inbox/:id/approve', () => problemJson(409, 'version-conflict', '다른 사람이 먼저 바꿨습니다.')),
      http.get('*/api/inbox/:id', () => HttpResponse.error()),
    )
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    await approve(user, doc)
    expect(await within(doc).findByRole('alert')).toHaveTextContent('다른 사람이 먼저 바꿨습니다. 새 내용을 불러오지 못했습니다.')
  })

  it('늦게 온 첫 목록 응답이 바꾼 탭의 목록을 덮지 않습니다', async () => {
    let first = true
    server.use(
      http.get('*/api/inbox', async ({ request }) => {
        if (first && new URL(request.url).searchParams.get('box') === 'inbox') {
          first = false
          await delay(150)
        }
        return undefined
      }),
    )
    const user = renderInbox()
    await user.click(await screen.findByRole('tab', { name: '기안함' }))
    // 행 이름은 보이는 글자 전부: 제목 → 양식·기안자 → 금액·언제
    expect(await screen.findByRole('button', { name: /^교육용 노트북 2대 구매 구매 요청 · \S+ .*원/ })).toBeInTheDocument()
    await delay(250)
    expect(screen.getByRole('button', { name: /^교육용 노트북 2대 구매 / })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^연차 휴가 신청\(11\/27~11\/28\) / })).toBeNull()
  })

  it('문서를 열면 제목으로, 닫으면 그 행 버튼으로 초점이 옮겨 갑니다', async () => {
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(doc).getByRole('heading', { name: '연차 휴가 신청(11/27~11/28)' })).toHaveFocus()
    await user.click(within(doc).getByRole('button', { name: '닫기' }))
    expect(screen.getByRole('button', { name: /^연차 휴가 신청\(11\/27~11\/28\) / })).toHaveFocus()
  })
})
