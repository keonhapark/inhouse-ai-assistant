import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'

function renderApp(path: string, token?: string) {
  if (token) tokenStore.set(token)
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const nav = () => screen.findByRole('navigation', { name: '주 메뉴' })

afterEach(() => {
  delete document.documentElement.dataset.theme
  localStorage.clear()
})

describe('왼쪽 탐색 막대', () => {
  it('업무·회사 묶음과 결재할 문서 건수를 보이고, 운영 묶음은 감사 조회 역할만 봅니다', async () => {
    renderApp('/', 'mock.emp-2001')
    const n = await nav()
    expect(within(n).getByRole('group', { name: '업무' })).toBeInTheDocument()
    expect(within(n).getByRole('link', { name: 'AI 비서' })).toHaveAttribute('aria-current', 'page')
    // 건수는 숫자로 보이고, 화면 낭독기에는 "결재, 결재할 문서 n건"으로 읽힙니다
    expect(await within(n).findByRole('link', { name: /^결재, 결재할 문서 \d+건$/ })).toBeInTheDocument()
    expect(within(n).queryByRole('group', { name: '운영' })).toBeNull()
    // 대결 설정은 결재에서 떼어 업무 묶음에 둡니다
    expect(within(within(n).getByRole('group', { name: '업무' })).getByRole('link', { name: '대결 설정' })).toHaveAttribute('href', '/delegations')
  })

  it('감사 조회 역할은 운영 묶음의 메뉴 넷을 봅니다', async () => {
    renderApp('/ops/audit', 'mock.emp-2008')
    const ops = within(await nav()).getByRole('group', { name: '운영' })
    expect(within(ops).getAllByRole('link').map((a) => a.textContent)).toEqual(['운영 지표', '외부 전송 기록', '감사 로그', '평가 보고서'])
    expect(within(ops).getByRole('link', { name: '감사 로그' })).toHaveAttribute('aria-current', 'page')
  })

  it('접기 단추로 아이콘만 남기고, 다시 누르면 펼칩니다. 접혀도 메뉴 이름은 읽힙니다', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    const n = await nav()
    const toggle = within(n).getByRole('button', { name: '탐색 막대 접기' })
    await user.click(toggle)
    expect(n).toHaveAttribute('data-collapsed', 'true')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(within(n).getByRole('link', { name: '조직도' })).toBeInTheDocument()
    expect(within(n).getByRole('button', { name: '찾기·이동' })).toBeInTheDocument()
    await user.click(toggle)
    expect(n).not.toHaveAttribute('data-collapsed')
  })

  it('사용자 메뉴에서 테마를 바꿉니다(시스템이면 data-theme를 지움)', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    await user.click(within(await nav()).getByRole('button', { name: '한지우 사용자 메뉴' }))
    await user.click(await screen.findByRole('menuitemradio', { name: '어두움' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    await user.click(screen.getByRole('button', { name: '한지우 사용자 메뉴' }))
    await user.click(await screen.findByRole('menuitemradio', { name: '시스템' }))
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })
})

describe('명령 팔레트', () => {
  it('Ctrl K로 열어 화면 이름을 찾고 Enter로 옮깁니다', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    await nav()
    await user.keyboard('{Control>}k{/Control}')
    const dialog = await screen.findByRole('dialog', { name: '찾기·이동' })
    await user.type(within(dialog).getByRole('combobox'), '조직도')
    await user.keyboard('{Enter}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(within(await nav()).getByRole('link', { name: '조직도' })).toHaveAttribute('aria-current', 'page')
  })

  it('"찾기·이동"으로 열고 테마를 바꾸며, Esc로 닫습니다', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    await user.click(within(await nav()).getByRole('button', { name: '찾기·이동' }))
    const dialog = await screen.findByRole('dialog', { name: '찾기·이동' })
    await user.click(within(dialog).getByRole('option', { name: /테마: 어두움/ }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    await user.click(within(await nav()).getByRole('button', { name: '찾기·이동' }))
    await screen.findByRole('dialog')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('"새 대화"를 고르면 보던 대화를 닫고 빈 대화로 시작합니다', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    await user.type(await screen.findByLabelText('메시지'), '연차 규정 알려 줘{Enter}')
    expect(await screen.findByText(/입사 1년이 지나면 연차 15일/)).toBeInTheDocument()
    await user.keyboard('{Control>}k{/Control}')
    await user.click(within(await screen.findByRole('dialog')).getByRole('option', { name: '새 대화' }))
    expect(await screen.findByText(/무엇을 할지 적어 보세요/)).toBeInTheDocument()
    expect(screen.queryByText(/입사 1년이 지나면 연차 15일/)).toBeNull()
  })

  it('감사 조회 역할이 아니면 운영 화면이 목록에 없습니다', async () => {
    const user = renderApp('/', 'mock.emp-1001')
    await nav()
    await act(async () => user.keyboard('{Control>}k{/Control}'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('option', { name: /감사 로그/ })).toBeNull()
    expect(within(dialog).getByRole('option', { name: /AI 에이전트/ })).toBeInTheDocument()
  })
})

describe('역할별 첫 화면', () => {
  async function loginAs(no: string) {
    const user = renderApp('/login')
    await user.type(await screen.findByLabelText('사번'), no)
    await user.type(screen.getByLabelText('비밀번호'), 'demo')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    return nav()
  }

  it('감사 조회 역할은 운영 지표로 들어갑니다', async () => {
    const n = await loginAs('E2008')
    expect(await within(n).findByRole('link', { name: '운영 지표' })).toHaveAttribute('aria-current', 'page')
  })

  it('결재할 문서가 있으면 결재로 들어갑니다', async () => {
    const n = await loginAs('E2001')
    await waitFor(() => expect(within(n).getByRole('link', { name: /^결재(,|$)/ })).toHaveAttribute('aria-current', 'page'))
  })

  it('로그인하지 않고 첫 주소(/)로 들어와도 로그인 뒤 역할별 첫 화면으로 갑니다', async () => {
    const user = renderApp('/')
    await user.type(await screen.findByLabelText('사번'), 'E2008')
    await user.type(screen.getByLabelText('비밀번호'), 'demo')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    const n = await nav()
    await waitFor(() => expect(within(n).getByRole('link', { name: '운영 지표' })).toHaveAttribute('aria-current', 'page'))
  })

  it('그 밖에는 AI 비서로 들어갑니다', async () => {
    const n = await loginAs('E1001')
    expect(within(n).getByRole('link', { name: 'AI 비서' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('운영 화면 권한', () => {
  it.each(['/ops/audit', '/ops/eval'])('감사 조회 역할이 아니면 %s 주소로 들어와도 AI 비서로 보냅니다', async (path) => {
    renderApp(path, 'mock.emp-1001')
    const n = await nav()
    await waitFor(() => expect(within(n).getByRole('link', { name: 'AI 비서' })).toHaveAttribute('aria-current', 'page'))
  })
})

describe('예전 주소', () => {
  it.each([
    ['/inbox', /^결재(,|$)/, 'mock.emp-2001'],
    ['/admin', '운영 지표', 'mock.emp-2008'],
    ['/eval', '평가 보고서', 'mock.emp-2008'],
  ])('%s는 새 주소로 옮깁니다', async (path, name, token) => {
    renderApp(path, token)
    const n = await nav()
    await waitFor(() => expect(within(n).getByRole('link', { name })).toHaveAttribute('aria-current', 'page'))
  })
})
