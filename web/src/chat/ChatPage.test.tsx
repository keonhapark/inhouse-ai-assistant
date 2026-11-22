import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

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

async function say(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(await screen.findByLabelText('메시지'), `${text}{Enter}`)
}

describe('직원 채팅', () => {
  it('회의실 예약: 되돌릴 수 있는 쓰기라 카드 없이 실행하고 되돌리기를 붙입니다', async () => {
    const user = renderChat()
    await say(user, '내일 오후 회의실 잡아 줘')

    const action = await screen.findByRole('region', { name: '실행한 일' })
    expect(within(action).getByText('3층 소회의실을 내일 14:00–15:00에 예약했습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /실행 미리보기/ })).toBeNull()
    expect(await screen.findByText(/필요 없으면 되돌리기를 누르면 됩니다/)).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toBeEnabled()

    await user.click(within(action).getByRole('button', { name: '되돌리기' }))
    expect(await within(action).findByText('되돌림')).toBeInTheDocument()
    expect(within(action).queryByRole('button', { name: '되돌리기' })).toBeNull()
  })

  it('결재 회수: 되돌릴 수 없어 미리보기 카드로 확인받고, 실행 뒤 되돌리기는 없습니다', async () => {
    const user = renderChat()
    await say(user, '휴가 결재 회수해 줘')

    const card = await screen.findByRole('region', { name: '실행 미리보기: 결재 회수' })
    expect(within(card).getByText('되돌릴 수 없음')).toBeInTheDocument()
    expect(within(card).getByText('실행하면 되돌릴 수 없습니다.')).toBeInTheDocument()
    expect(within(card).getByText('휴가 결재 APR-0042(11/24 오후 반차)를 회수합니다.')).toBeInTheDocument()
    expect(screen.getByText('미리보기 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다.')).toBeInTheDocument()
    expect(screen.getByLabelText('메시지')).toBeDisabled()
    expect(within(card).getByText('인사')).toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: '실행' }))
    const action = await screen.findByRole('region', { name: '실행한 일' })
    expect(within(card).getByText('실행함')).toBeInTheDocument()
    expect(within(action).queryByRole('button', { name: '되돌리기' })).toBeNull()
    expect(screen.getByLabelText('메시지')).toBeEnabled()
  })

  it('취소하면 실행하지 않습니다', async () => {
    const user = renderChat()
    await say(user, '결재 회수')
    const card = await screen.findByRole('region', { name: '실행 미리보기: 결재 회수' })
    await user.click(within(card).getByRole('button', { name: '취소' }))
    expect(await within(card).findByText('취소함')).toBeInTheDocument()
    expect(await screen.findByText('회수하지 않았습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '실행한 일' })).toBeNull()
  })

  it('규정 답에는 로컬 처리 배지와 근거를 붙이고, 확인 안 된 인용을 표시합니다', async () => {
    const user = renderChat()
    await say(user, '연차 규정 알려 줘')
    expect(await screen.findByText(/입사 1년이 지나면 연차 15일/)).toBeInTheDocument()
    expect(screen.getByText('로컬에서 처리')).toBeInTheDocument()
    await user.click(screen.getByText('근거 2건'))
    expect(screen.getAllByText('취업규칙')).toHaveLength(2)
    expect(screen.getByText('인용 확인 안 됨')).toBeInTheDocument()
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

  it('장치가 막으면 이유를 보여 줍니다', async () => {
    const user = renderChat()
    await say(user, '팀원 급여 알려 줘')
    expect(await screen.findByText('이 에이전트는 다른 직원의 급여 정보를 볼 수 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('차단')).toBeInTheDocument()
  })

  it('에이전트를 직접 고르면 그 에이전트로 대화를 엽니다', async () => {
    const user = renderChat()
    await screen.findByRole('option', { name: '인사 (로컬 모델만)' })
    await user.selectOptions(screen.getByLabelText('부서 에이전트'), 'hr')
    await say(user, '연차 며칠 남았어?')
    expect(await screen.findByText(/입사 1년이 지나면/)).toBeInTheDocument()
    expect(screen.queryByLabelText('부서 에이전트')).toBeNull()
    expect(screen.getAllByText('인사').length).toBeGreaterThan(0)
  })

  it('대화 목록에서 고르면 지난 대화를 복원합니다', async () => {
    const user = renderChat()
    await say(user, '연차 규정')
    await screen.findByText('로컬에서 처리')
    await user.click(screen.getByRole('button', { name: '새 대화' }))
    expect(screen.queryByText('로컬에서 처리')).toBeNull()

    const list = screen.getByRole('navigation', { name: '대화 목록' })
    await user.click(within(list).getByRole('button', { name: /연차 규정/ }))
    expect(await screen.findByText('로컬에서 처리')).toBeInTheDocument()
    expect(screen.getByText('연차 규정', { selector: '.msg--user' })).toBeInTheDocument()
  })

  it('서버 오류면 problem title과 다시 보내기를 보여 줍니다', async () => {
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
    await user.click(screen.getByRole('button', { name: '다시 보내기' }))
    expect(await screen.findByText(/맡을 부서를 찾지 못했습니다/)).toBeInTheDocument()
  })
  it('스트림이 done 없이 닫히면 끊겼다고 알리고 다시 보내기는 주지 않습니다', async () => {
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
    expect(screen.queryByRole('button', { name: '다시 보내기' })).toBeNull()
    expect(screen.getByLabelText('메시지')).toBeEnabled()
  })

  it('4xx로 거절된 메시지는 다시 보내기를 주지 않습니다', async () => {
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
    expect(screen.queryByRole('button', { name: '다시 보내기' })).toBeNull()
  })

  it('실행 결정이 409로 거절되면 카드를 닫고 입력을 풉니다', async () => {
    const user = renderChat()
    await say(user, '결재 회수')
    const card = await screen.findByRole('region', { name: '실행 미리보기: 결재 회수' })
    server.use(
      http.post('*/api/execution-approvals/:id', () =>
        HttpResponse.json(
          { type: 'urn:problem:invalid-state', title: '이미 결정한 실행 승인입니다.', status: 409 },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    await user.click(within(card).getByRole('button', { name: '실행' }))
    expect(await screen.findByText('이미 결정한 실행 승인입니다.')).toBeInTheDocument()
    expect(within(card).getByText('더 결정할 수 없음')).toBeInTheDocument()
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
    await screen.findByText('로컬에서 처리')
    expect(created).toBe(1)
    server.events.removeAllListeners()
  })
})
