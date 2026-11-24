import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

function renderChat(token = 'mock.emp-1001') {
  tokenStore.set(token)
  render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

async function say(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(await screen.findByLabelText('메시지'), `${text}{Enter}`)
}

describe('직원 채팅', () => {
  it('회의실 예약: 실행 취소할 수 있는 쓰기라 카드 없이 실행하고 실행 취소를 붙입니다', async () => {
    const user = renderChat()
    await say(user, '내일 오후 회의실 잡아 줘')

    const action = await screen.findByRole('region', { name: '완료한 일' })
    expect(within(action).getByText('3층 소회의실을 내일 14:00–15:00에 예약했습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /실행 전 확인/ })).toBeNull()
    expect(await screen.findByText(/필요 없으면 실행 취소를 누르세요/)).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toBeEnabled()

    await user.click(within(action).getByRole('button', { name: '실행 취소' }))
    expect(await within(action).findByText('취소됨')).toBeInTheDocument()
    expect(within(action).queryByRole('button', { name: '실행 취소' })).toBeNull()
  })

  it('결재 회수: 실행 취소할 수 없어 실행 전 확인을 받고, 완료 뒤 실행 취소는 없습니다', async () => {
    const user = renderChat()
    await say(user, '휴가 결재 회수해 줘')

    const card = await screen.findByRole('region', { name: '실행 전 확인: 결재 회수' })
    expect(within(card).getByText('실행하면 취소할 수 없습니다.')).toBeInTheDocument()
    expect(within(card).getByText('휴가 결재 APR-0042(11/24 오후 반차)를 회수합니다.')).toBeInTheDocument()
    expect(screen.getByText('위 확인 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다.')).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toBeDisabled()

    await user.click(within(card).getByRole('button', { name: '결재 회수' }))
    const action = await screen.findByRole('region', { name: '완료한 일' })
    expect(card).not.toBeInTheDocument()
    expect(within(action).queryByRole('button', { name: '실행 취소' })).toBeNull()
    expect(screen.getByLabelText('메시지')).toBeEnabled()
  })

  it('취소하면 실행하지 않습니다', async () => {
    const user = renderChat()
    await say(user, '결재 회수')
    const card = await screen.findByRole('region', { name: '실행 전 확인: 결재 회수' })
    await user.click(within(card).getByRole('button', { name: '취소' }))
    expect(await within(card).findByText('실행 안 함')).toBeInTheDocument()
    expect(await screen.findByText('회수하지 않았습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '완료한 일' })).toBeNull()
  })

  it('규정 답에는 답 머리(담당 AI · 사내 처리)와 근거 규정을 붙이고, 원문 대조 안 된 인용을 표시합니다', async () => {
    const user = renderChat()
    await say(user, '연차 규정 알려 줘')
    expect(await screen.findByText(/입사 1년이 지나면 연차 15일/)).toBeInTheDocument()
    expect(screen.getByText('사내 처리')).toBeInTheDocument()
    await user.click(screen.getByText('근거 규정 2건'))
    expect(screen.getAllByText('취업규칙')).toHaveLength(2)
    expect(screen.getByText('원문 대조 안 됨')).toBeInTheDocument()
  })

  it('답의 마크다운(굵게·목록·코드)을 글자 대신 서식으로 그립니다', async () => {
    const user = renderChat()
    await say(user, '출장 숙박비 한도가 얼마야?')
    const strong = await screen.findByText('서울·광역시', { selector: 'strong' })
    const list = strong.closest('ul')!
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('숙박 영수증', { selector: 'code' })).toBeInTheDocument()
    expect(screen.queryByText(/\*\*/)).toBeNull()
  })

  it('정책이 막으면 처리할 수 없는 요청과 이유를 보여 줍니다', async () => {
    const user = renderChat()
    await say(user, '팀원 급여 알려 줘')
    expect(await screen.findByText('이 에이전트는 다른 직원의 급여 정보를 볼 수 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('처리할 수 없는 요청')).toBeInTheDocument()
  })

  it('담당 AI를 직접 고르면 그 에이전트로 대화를 엽니다', async () => {
    const user = renderChat()
    await screen.findByLabelText('메시지')
    await user.click(screen.getByRole('button', { name: '담당 AI: 자동 선택' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /인사 담당 AI/ }))
    expect(screen.getByRole('button', { name: '담당 AI: 인사 담당 AI' })).toBeInTheDocument()
    await say(user, '연차 며칠 남았어?')
    expect(await screen.findByText(/입사 1년이 지나면/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^담당 AI:/ })).toBeNull()
    expect(screen.getByText('인사 담당 AI', { selector: '.toolbar__sub' })).toBeInTheDocument()
  })

  it('대화 목록에서 고르면 지난 대화를 복원합니다', async () => {
    const user = renderChat()
    await say(user, '연차 규정')
    await screen.findByText('사내 처리')
    await user.click(screen.getByRole('button', { name: '새 대화' }))
    expect(screen.queryByText('사내 처리')).toBeNull()

    const list = screen.getByRole('navigation', { name: '대화 목록' })
    await user.click(within(list).getByRole('button', { name: /연차 규정/ }))
    expect(await screen.findByText('사내 처리')).toBeInTheDocument()
    expect(screen.getByText('연차 규정', { selector: '.msg--user' })).toBeInTheDocument()
    // 같은 말로 시작한 대화도 에이전트·시각으로 구별합니다(#556)
    const row = within(list).getByRole('button', { name: /연차 규정/ })
    expect(row).toHaveTextContent(/인사 담당 AI/)
    expect(within(row).getByText(/^오늘 \d{2}:\d{2}$/)).toBeInTheDocument()
  })

  it('화면에 main과 h1이 있고, 새 대화의 제목은 "새 대화"입니다', async () => {
    renderChat()
    expect(await screen.findByRole('main', { name: '새 대화' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '새 대화' })).toBeInTheDocument()
  })

  it('에이전트가 쓴 기능은 "처리 과정"으로 접어 두고, 펼치면 표시 이름만 보입니다', async () => {
    const user = renderChat()
    await say(user, '내일 오후 회의실 잡아 줘')
    const steps = await screen.findByText('처리 과정 2단계')
    expect(steps.closest('details')).not.toHaveAttribute('open')
    await user.click(steps)
    expect(screen.getByText('빈 회의실 검색')).toBeVisible()
    expect(screen.queryByText(/room_reserve/)).toBeNull()
  })

  it('답 머리(담당 AI · 사내 처리)는 한 턴에 한 번만 붙입니다', async () => {
    const user = renderChat()
    await say(user, '연차 규정 알려 줘')
    expect(await screen.findByText('사내 처리')).toBeInTheDocument()
    expect(screen.getAllByText('인사 담당 AI', { selector: '.msg__who b' })).toHaveLength(1)
    await say(user, '휴가 규정도 알려 줘')
    await vi.waitFor(() => expect(screen.getAllByText('인사 담당 AI', { selector: '.msg__who b' })).toHaveLength(2))
    expect(screen.getAllByText('사내 처리')).toHaveLength(2)
  })

  it('알림: 결재 차례인 문서가 있으면 종에 새 알림 수를 붙이고, 고르면 결재 화면으로 갑니다', async () => {
    const user = renderChat('mock.emp-2001')
    const bell = await screen.findByRole('button', { name: /^알림, 새 알림 \d+건$/ })
    await user.click(bell)
    const items = await screen.findAllByRole('menuitem', { name: /결재 차례입니다/ })
    await user.click(items[0])
    expect(await screen.findByRole('heading', { level: 1, name: '결재' })).toBeInTheDocument()
  })

  it('서버 오류면 problem title과 다시 시도를 보여 줍니다', async () => {
    let calls = 0
    server.use(
      http.post('*/api/conversations/:id/messages', () => {
        calls++
        return calls === 1
          ? HttpResponse.json(
              { type: 'urn:problem:upstream', title: '모델 서버가 응답하지 않습니다.', status: 503 },
              { status: 503, headers: { 'Content-Type': 'application/problem+json' } },
            )
          : undefined
      }),
    )
    const user = renderChat()
    await say(user, '안녕')
    expect(await screen.findByText('모델 서버가 응답하지 않습니다.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText(/맡을 부서를 찾지 못했습니다/)).toBeInTheDocument()
  })
  it('스트림이 done 없이 닫히면 끊겼다고 알리고 다시 시도는 주지 않습니다', async () => {
    server.use(
      http.post(
        '*/api/conversations/:id/messages',
        () =>
          new HttpResponse('event: delta\ndata: {"type":"delta","conversationId":"x","seq":0,"text":"반쯤"}\n\n', {
            headers: { 'Content-Type': 'text/event-stream' },
          }),
      ),
    )
    const user = renderChat()
    await say(user, '안녕')
    expect(await screen.findByText('응답이 중간에 끊겼습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.getByLabelText('메시지')).toBeEnabled()
  })

  it('4xx로 거절된 메시지는 다시 시도를 주지 않습니다', async () => {
    server.use(
      http.post('*/api/conversations/:id/messages', () =>
        HttpResponse.json(
          { type: 'urn:problem:forbidden', title: '이 에이전트를 부를 수 없습니다.', status: 403 },
          { status: 403, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    const user = renderChat()
    await say(user, '안녕')
    expect(await screen.findByText('이 에이전트를 부를 수 없습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
  })

  it('실행 결정이 409로 거절되면 카드를 닫고 입력을 풉니다', async () => {
    const user = renderChat()
    await say(user, '결재 회수')
    const card = await screen.findByRole('region', { name: '실행 전 확인: 결재 회수' })
    server.use(
      http.post('*/api/execution-approvals/:id', () =>
        HttpResponse.json(
          { type: 'urn:problem:invalid-state', title: '이미 결정한 실행 승인입니다.', status: 409 },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    await user.click(within(card).getByRole('button', { name: '결재 회수' }))
    expect(await screen.findByText('이미 결정한 실행 승인입니다.')).toBeInTheDocument()
    expect(within(card).getByText('진행 불가')).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toBeEnabled()
  })

  it('대화를 만드는 동안 다시 보내도 대화는 하나만 생깁니다', async () => {
    let created = 0
    // 생성 응답을 늦춰 두 번째 Enter가 생성 중에 눌리게 합니다. undefined를 돌려주면 기본 모의 처리로 넘어갑니다.
    server.use(
      http.post('*/api/conversations', async () => {
        await delay(100)
        return undefined
      }),
    )
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/conversations') created++
    })
    const user = renderChat()
    const input = await screen.findByLabelText('메시지')
    await user.type(input, '연차{Enter}')
    await user.type(input, '{Enter}')
    await screen.findByText('사내 처리')
    expect(created).toBe(1)
    server.events.removeAllListeners()
  })
})
