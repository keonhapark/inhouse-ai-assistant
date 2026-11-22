import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

// 서도윤(emp-2001, 인사팀장)으로 로그인합니다. 모의 데이터는 src/mocks/inbox.ts입니다.
function renderDelegations() {
  tokenStore.set('mock.emp-2001')
  render(
    <MemoryRouter initialEntries={['/delegations']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const problemJson = (status: number, code: string, title: string) =>
  HttpResponse.json({ type: `urn:problem:${code}`, title, status }, { status, headers: { 'Content-Type': 'application/problem+json' } })

describe('대결 설정', () => {
  it('받은 대결은 보이지만 해제할 수 없습니다', async () => {
    renderDelegations()
    const panel = await screen.findByRole('region', { name: '대결 설정' })
    expect(await within(panel).findByText('윤서진 → 서도윤')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /해제$/ })).toBeNull()
  })

  it('대결자를 찾아 내용을 확인한 뒤 지정하고, 해제합니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('region', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '교육 참석')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))

    const preview = await within(panel).findByRole('region', { name: '대결 지정 확인' })
    expect(within(preview).getByText('한지우를 대결자로 지정합니다.')).toBeInTheDocument()
    expect(within(preview).getByText('모든 양식')).toBeInTheDocument()
    await user.click(within(preview).getByRole('button', { name: '대결 지정' }))

    expect(await within(panel).findByRole('status')).toHaveTextContent('한지우를 대결자로 지정합니다.')
    expect(await within(panel).findByText('서도윤 → 한지우')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: '한지우 대결 해제' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('해제했습니다')
    expect(within(panel).queryByRole('button', { name: '한지우 대결 해제' })).toBeNull()
  })

  it('양식을 골라 범위를 좁힙니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('region', { name: '대결 설정' })
    await user.click(within(panel).getByRole('checkbox', { name: '모든 양식' }))
    await user.click(await within(panel).findByRole('checkbox', { name: '휴가 신청' }))
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '박하')
    await user.click(await within(panel).findByRole('radio', { name: /박하늘/ }))
    await user.type(within(panel).getByLabelText('사유'), '휴가')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    const preview = await within(panel).findByRole('region', { name: '대결 지정 확인' })
    expect(within(preview).getByText('leave')).toBeInTheDocument()
  })

  it('서버가 거절하면 problem title을 그대로 보여 줍니다', async () => {
    server.use(http.post('*/api/delegations', () => problemJson(422, 'delegation-out-of-period', '위임 기간이 올바르지 않습니다.')))
    const user = renderDelegations()
    const panel = await screen.findByRole('region', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '출장')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('위임 기간이 올바르지 않습니다.')
  })
  it('내용 확인 뒤 입력을 바꾸면 확인 카드와 대결 지정 버튼을 지웁니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('region', { name: '대결 설정' })
    await user.type(within(panel).getByLabelText('이름으로 찾기'), '한지')
    await user.click(await within(panel).findByRole('radio', { name: /한지우/ }))
    await user.type(within(panel).getByLabelText('사유'), '출장')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    await within(panel).findByRole('region', { name: '대결 지정 확인' })
    await user.type(within(panel).getByLabelText('사유'), ' 연장')
    expect(within(panel).queryByRole('region', { name: '대결 지정 확인' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: '대결 지정' })).toBeNull()
  })
})
