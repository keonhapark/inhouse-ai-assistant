import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function fillAndSubmit(employeeNo: string, password: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('사번'), employeeNo)
  await user.type(screen.getByLabelText('비밀번호'), password)
  await user.click(screen.getByRole('button', { name: '로그인' }))
  return user
}

describe('로그인', () => {
  it('로그인하지 않았으면 로그인 화면으로 보냅니다', async () => {
    renderApp('/')
    expect(await screen.findByRole('heading', { name: '사내 AI 비서' })).toBeInTheDocument()
  })

  it('틀린 비밀번호면 problem+json의 title을 보여 주고 토큰을 저장하지 않습니다', async () => {
    renderApp('/login')
    await fillAndSubmit('E1001', 'wrong')
    expect(await screen.findByRole('alert')).toHaveTextContent('사번 또는 비밀번호가 맞지 않습니다.')
    expect(tokenStore.get()).toBeNull()
  })

  it('맞으면 토큰을 저장하고 홈으로 갑니다. 로그아웃하면 토큰을 지웁니다', async () => {
    renderApp('/')
    const user = await fillAndSubmit('E1001', 'demo')
    expect(await screen.findByRole('heading', { name: '한지우님, 안녕하세요' })).toBeInTheDocument()
    expect(tokenStore.get()).toBe('mock.emp-1001')

    await user.click(screen.getByRole('button', { name: '로그아웃' }))
    expect(await screen.findByLabelText('사번')).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })

  it('서버에 닿지 않으면 연결 오류 문장을 보여 줍니다', async () => {
    server.use(http.post('*/api/auth/login', () => HttpResponse.error()))
    renderApp('/login')
    await fillAndSubmit('E1001', 'demo')
    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결하지 못했습니다')
  })
})

describe('저장된 토큰', () => {
  it('유효하면 /me로 세션을 되살립니다', async () => {
    tokenStore.set('mock.emp-2001')
    renderApp('/')
    expect(await screen.findByRole('heading', { name: '서도윤님, 안녕하세요' })).toBeInTheDocument()
  })

  it('401이면 토큰을 지우고 로그인 화면으로 보냅니다', async () => {
    tokenStore.set('expired')
    renderApp('/')
    expect(await screen.findByLabelText('사번')).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })
})
