import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

// 서도윤(emp-2001, 인사팀장)으로 로그인합니다. 모의 데이터는 src/mocks/inbox.ts입니다.
function renderInbox() {
  tokenStore.set('mock.emp-2001')
  render(
    <MemoryRouter initialEntries={['/inbox']}>
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
  await user.click(await screen.findByRole('button', { name: title }))
  return screen.findByRole('region', { name: `결재 문서: ${title}` })
}

describe('팀장 승인함', () => {
  it('내 차례 문서를 열어 결재선을 보고 승인하면 처리함으로 옮겨 갑니다', async () => {
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(doc).getByText('한지우')).toBeInTheDocument()
    const line = within(doc).getByRole('list')
    expect(within(line).getByText('서도윤')).toBeInTheDocument()
    expect(within(line).getByText('결재 차례')).toBeInTheDocument()

    await user.type(within(doc).getByLabelText(/의견/), '잘 다녀오세요')
    await user.click(within(doc).getByRole('button', { name: '승인' }))
    expect(await screen.findByRole('status')).toHaveTextContent('연차 휴가 신청(11/27~11/28)을 승인했습니다.')
    expect(await screen.findByText('이 함에는 결재 문서가 없습니다.')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '처리함' }))
    const done = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(done).getByText('“잘 다녀오세요”')).toBeInTheDocument()
    expect(within(done).queryByRole('button', { name: '승인' })).toBeNull()
  })

  it('대결 탭은 원 결재자 배지를 달고, 대신 결재한다고 알립니다', async () => {
    const user = renderInbox()
    await user.click(await screen.findByRole('tab', { name: '대결' }))
    expect(await screen.findByText('대결: 윤서진')).toBeInTheDocument()
    const doc = await openDoc(user, '11월 출장 경비 정산')
    expect(within(doc).getByText(/윤서진님 대신 결재합니다/)).toBeInTheDocument()
    expect(within(doc).getByText('320,000원')).toBeInTheDocument()
    await user.click(within(doc).getByRole('button', { name: '반려' }))
    expect(await screen.findByRole('status')).toHaveTextContent('반려했습니다')
  })

  it('버전이 어긋나 409가 오면 problem title을 보여 주고 문서를 다시 불러옵니다', async () => {
    server.use(http.post('*/api/inbox/:id/approve', () => problemJson(409, 'version-conflict', '다른 사람이 먼저 바꿨습니다.')))
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    await user.click(within(doc).getByRole('button', { name: '승인' }))
    expect(await within(doc).findByRole('alert')).toHaveTextContent('다른 사람이 먼저 바꿨습니다.')
    expect(screen.getByRole('region', { name: '결재 문서: 연차 휴가 신청(11/27~11/28)' })).toBeInTheDocument()
  })

  it('올린 것 탭의 문서는 결재 버튼이 없습니다', async () => {
    const user = renderInbox()
    await user.click(await screen.findByRole('tab', { name: '올린 것' }))
    const doc = await openDoc(user, '교육용 노트북 2대 구매')
    expect(within(doc).getByText('임채원')).toBeInTheDocument()
    expect(within(doc).queryByRole('button', { name: '승인' })).toBeNull()
  })

  it('화살표 키로 탭을 옮깁니다', async () => {
    const user = renderInbox()
    const first = await screen.findByRole('tab', { name: '내 차례' })
    first.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: '대결' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '대결' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: '올린 것' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('대결 설정', () => {
  it('받은 위임은 보이지만 해지할 수 없습니다', async () => {
    renderInbox()
    const panel = await screen.findByRole('complementary', { name: '대결 설정' })
    expect(await within(panel).findByText('윤서진 → 서도윤')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /해지$/ })).toBeNull()
  })

  it('대리인을 찾아 미리보기 뒤 등록하고, 해지합니다', async () => {
    const user = renderInbox()
    const panel = await screen.findByRole('complementary', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '교육 참석')
    await user.click(within(panel).getByRole('button', { name: '미리보기' }))

    const preview = await within(panel).findByRole('region', { name: '위임 미리보기' })
    expect(within(preview).getByText('한지우에게 결재를 위임합니다.')).toBeInTheDocument()
    expect(within(preview).getByText('모든 양식')).toBeInTheDocument()
    await user.click(within(preview).getByRole('button', { name: '등록' }))

    expect(await within(panel).findByRole('status')).toHaveTextContent('한지우에게 결재를 위임합니다.')
    expect(await within(panel).findByText('서도윤 → 한지우')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: '한지우에게 맡긴 위임 해지' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('해지했습니다')
    expect(within(panel).queryByRole('button', { name: '한지우에게 맡긴 위임 해지' })).toBeNull()
  })

  it('양식을 골라 범위를 좁힙니다', async () => {
    const user = renderInbox()
    const panel = await screen.findByRole('complementary', { name: '대결 설정' })
    await user.click(within(panel).getByRole('checkbox', { name: '모든 양식' }))
    await user.click(await within(panel).findByRole('checkbox', { name: '휴가 신청' }))
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '박하')
    await user.click(await within(panel).findByRole('radio', { name: /박하늘/ }))
    await user.type(within(panel).getByLabelText('사유'), '휴가')
    await user.click(within(panel).getByRole('button', { name: '미리보기' }))
    const preview = await within(panel).findByRole('region', { name: '위임 미리보기' })
    expect(within(preview).getByText('leave')).toBeInTheDocument()
  })

  it('서버가 거절하면 problem title을 그대로 보여 줍니다', async () => {
    server.use(http.post('*/api/delegations', () => problemJson(422, 'delegation-out-of-period', '위임 기간이 올바르지 않습니다.')))
    const user = renderInbox()
    const panel = await screen.findByRole('complementary', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '출장')
    await user.click(within(panel).getByRole('button', { name: '미리보기' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('위임 기간이 올바르지 않습니다.')
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
    const approve = within(doc).getByRole('button', { name: '승인' })
    await user.click(approve)
    await within(doc).findByRole('alert')
    await user.click(approve)
    await user.type(within(doc).getByLabelText(/의견/), '확인')
    await user.click(approve)
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
    await user.click(within(doc).getByRole('button', { name: '승인' }))
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
    await user.click(await screen.findByRole('tab', { name: '올린 것' }))
    expect(await screen.findByRole('button', { name: '교육용 노트북 2대 구매' })).toBeInTheDocument()
    await delay(250)
    expect(screen.getByRole('button', { name: '교육용 노트북 2대 구매' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '연차 휴가 신청(11/27~11/28)' })).toBeNull()
  })

  it('문서를 열면 제목으로, 닫으면 그 행 버튼으로 초점이 옮겨 갑니다', async () => {
    const user = renderInbox()
    const doc = await openDoc(user, '연차 휴가 신청(11/27~11/28)')
    expect(within(doc).getByRole('heading', { name: '연차 휴가 신청(11/27~11/28)' })).toHaveFocus()
    await user.click(within(doc).getByRole('button', { name: '닫기' }))
    expect(screen.getByRole('button', { name: '연차 휴가 신청(11/27~11/28)' })).toHaveFocus()
  })

  it('미리보기 뒤 입력을 바꾸면 미리보기와 등록 버튼을 지웁니다', async () => {
    const user = renderInbox()
    const panel = await screen.findByRole('complementary', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '출장')
    await user.click(within(panel).getByRole('button', { name: '미리보기' }))
    await within(panel).findByRole('region', { name: '위임 미리보기' })
    await user.type(within(panel).getByLabelText('사유'), ' 연장')
    expect(within(panel).queryByRole('region', { name: '위임 미리보기' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: '등록' })).toBeNull()
  })
})
