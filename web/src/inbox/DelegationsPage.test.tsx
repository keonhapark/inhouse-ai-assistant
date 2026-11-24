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

/** 대결자를 찾아 고르고, 고른 양식(기본)으로 휴가 신청을 고른 뒤 사유를 적습니다 */
async function fill(user: ReturnType<typeof userEvent.setup>, panel: HTMLElement, who: string, reason: string, pickLeave = true) {
  await user.type(within(panel).getByLabelText('이름 검색'), who.slice(0, 2))
  await user.click(await within(panel).findByRole('radio', { name: new RegExp(who) }))
  if (pickLeave) await user.click(await within(panel).findByRole('checkbox', { name: '휴가 신청' }))
  await user.type(within(panel).getByLabelText('사유'), reason)
}

describe('대결 설정', () => {
  it('맡은 대결은 "○○ 님 대신 결재"로 따로 보이고 해제할 수 없습니다', async () => {
    renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    const taken = await within(panel).findByRole('region', { name: '맡은 대결' })
    expect(within(taken).getByText('윤서진 님 대신 결재')).toBeInTheDocument()
    expect(within(taken).getAllByRole('listitem').length).toBeGreaterThan(0)
    expect(taken).toHaveTextContent(`${within(taken).getAllByRole('listitem').length}건`)
    expect(taken.querySelectorAll('.status').length).toBe(within(taken).getAllByRole('listitem').length)
    expect(within(taken).getAllByText(/^(대결 중|예정|종료|해제)$/).length).toBeGreaterThan(0)
    expect(within(panel).getByRole('region', { name: '맡긴 대결' })).toHaveTextContent('맡긴 대결이 없습니다.')
    expect(within(panel).queryByRole('button', { name: /해제$/ })).toBeNull()
  })

  it('양식 범위는 "고른 양식만"이 기본이고, 양식을 고르기 전에는 내용 확인을 누를 수 없습니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    expect(within(panel).getByRole('radio', { name: '고른 양식만' })).toBeChecked()
    expect(within(panel).getByRole('radio', { name: '모든 양식' })).not.toBeChecked()
    await fill(user, panel, '한지우', '교육 참석', false)
    expect(within(panel).getByText('대신 결재할 양식을 하나 이상 고르세요.')).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: '내용 확인' })).toBeDisabled()
    await user.click(await within(panel).findByRole('checkbox', { name: '휴가 신청' }))
    expect(within(panel).getByRole('button', { name: '내용 확인' })).toBeEnabled()
  })

  it('대결자를 찾아 내용을 확인한 뒤 지정하고, 해제합니다. 확인 시트는 표시 이름과 경고를 보여 줍니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    await fill(user, panel, '한지우', '교육 참석')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))

    const preview = await within(panel).findByRole('region', { name: '대결 지정 확인' })
    expect(within(preview).getByText('한지우를 대결자로 지정합니다.')).toBeInTheDocument()
    // 필드는 표시 이름(대결자·범위), 양식은 양식 이름으로 보입니다
    expect(within(preview).getByText('대결자')).toBeInTheDocument()
    // 직원·양식 사전을 받은 뒤 이름으로 바뀝니다
    expect(await within(preview).findByText('휴가 신청, 금액 한도 없음')).toBeInTheDocument()
    expect(within(preview).getByText('한지우 팀원(인사팀)')).toBeInTheDocument()
    // 값 행에는 옛 말(대리인·금액한도)과 양식 ID가 없습니다(API 원래 값은 "자세히" 안에만 있음)
    expect(preview.querySelector('.sheet__values')).not.toHaveTextContent(/대리인|금액한도|leave/)
    // 금액 한도 없음 경고는 있고, 모든 양식 경고는 없습니다
    expect(within(preview).getByText('금액 한도가 없어 금액과 상관없이 대신 결재하게 됩니다.')).toBeInTheDocument()
    expect(preview).not.toHaveTextContent('모든 양식을 대신 결재하게 됩니다.')
    // 한지우가 올린 문서가 내 결재 차례에 있으면 알립니다
    expect(await within(preview).findByText(/^한지우 님이 올린 문서 \d+건이 지금 내 결재 차례입니다/)).toBeInTheDocument()
    await user.click(within(preview).getByRole('button', { name: '대결 지정' }))

    expect(await within(panel).findByRole('status')).toHaveTextContent('한지우를 대결자로 지정합니다.')
    const given = within(panel).getByRole('region', { name: '맡긴 대결' })
    expect(await within(given).findByText('한지우 님에게 맡김')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: '한지우 님 대결 해제' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('해제했습니다')
    expect(within(panel).queryByRole('button', { name: '한지우 님 대결 해제' })).toBeNull()
  })

  it('모든 양식과 금액 한도를 고르면 모든 양식만 경고하고, 대결자 본인 문서가 없으면 그 경고는 없습니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    await user.click(within(panel).getByRole('radio', { name: '모든 양식' }))
    expect(within(panel).queryByRole('checkbox', { name: '휴가 신청' })).toBeNull()
    await fill(user, panel, '권나래', '휴가', false)
    await user.type(within(panel).getByLabelText('금액 한도(원)'), '500000')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    const preview = await within(panel).findByRole('region', { name: '대결 지정 확인' })
    expect(await within(preview).findByText('모든 양식, 500,000원 이하')).toBeInTheDocument()
    expect(within(preview).getByText('모든 양식을 대신 결재하게 됩니다. 필요한 양식만 고르는 편이 안전합니다.')).toBeInTheDocument()
    expect(preview).not.toHaveTextContent('금액 한도가 없어')
    expect(preview).not.toHaveTextContent('님이 올린 문서')
  })

  it('서버가 거절하면 problem title을 그대로 보여 줍니다', async () => {
    server.use(http.post('*/api/delegations', () => problemJson(422, 'delegation-out-of-period', '위임 기간이 올바르지 않습니다.')))
    const user = renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    await fill(user, panel, '한지우', '출장')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('위임 기간이 올바르지 않습니다.')
  })
  it('내용 확인 뒤 입력을 바꾸면 확인 카드와 대결 지정 버튼을 지웁니다', async () => {
    const user = renderDelegations()
    const panel = await screen.findByRole('main', { name: '대결 설정' })
    await fill(user, panel, '한지우', '출장')
    await user.click(within(panel).getByRole('button', { name: '내용 확인' }))
    await within(panel).findByRole('region', { name: '대결 지정 확인' })
    await user.type(within(panel).getByLabelText('사유'), ' 연장')
    expect(within(panel).queryByRole('region', { name: '대결 지정 확인' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: '대결 지정' })).toBeNull()
  })
})
