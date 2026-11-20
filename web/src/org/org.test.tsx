import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

function renderAt(path: string) {
  tokenStore.set('mock.emp-1001')
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const problemJson = (status: number, title: string) =>
  HttpResponse.json({ type: 'urn:problem:x', title, status }, { status, headers: { 'Content-Type': 'application/problem+json' } })

describe('조직도', () => {
  it('맨 위 부서를 먼저 열고, 부서장을 맨 앞에 보여 줍니다', async () => {
    renderAt('/org')
    const detail = await screen.findByRole('region', { name: '대표이사실 상세' })
    expect(await within(detail).findByText('문성호')).toBeInTheDocument()
    expect(within(detail).getByText('부서장')).toBeInTheDocument()
    expect(within(detail).getByText('대표이사')).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: '경영지원본부' })).toBeInTheDocument()
  })

  it('나무에서 팀을 고르면 상위 경로, 구성원, 담당 에이전트를 보여 줍니다', async () => {
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '인사팀' }))

    const detail = await screen.findByRole('region', { name: '인사팀 상세' })
    const rows = await within(detail).findAllByRole('row')
    expect(rows[1]).toHaveTextContent('서도윤부서장')
    expect(rows).toHaveLength(4)
    expect(within(detail).getByRole('list', { name: '상위 부서' })).toHaveTextContent('대표이사실경영지원본부')
    expect(within(detail).getByRole('link', { name: '인사' })).toHaveAttribute('href', '/agents#agent-hr')
    expect(within(tree).getByRole('button', { name: '인사팀' })).toHaveAttribute('aria-current', 'true')
  })

  it('구성원이 없는 부서는 안내 문장을 보여 줍니다', async () => {
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '영업팀' }))
    expect(await screen.findByText('이 부서에 바로 속한 구성원이 없습니다. 하위 부서를 골라 보세요.')).toBeInTheDocument()
    expect(screen.getByText('이 부서가 맡은 에이전트가 없습니다.')).toBeInTheDocument()
  })

  it('하위 부서 버튼으로 고르면 새 부서 제목에 포커스를 두고 주소에 남깁니다', async () => {
    const user = renderAt('/org')
    const detail = await screen.findByRole('region', { name: '대표이사실 상세' })
    await user.click(within(detail).getByRole('button', { name: '경영지원본부' }))
    const heading = await screen.findByRole('heading', { level: 2, name: /경영지원본부/ })
    expect(heading).toHaveFocus()
    expect(await screen.findByText('임채원')).toBeInTheDocument()
  })

  it('주소의 ?unit=으로 그 부서를 엽니다', async () => {
    renderAt('/org?unit=finance')
    const detail = await screen.findByRole('region', { name: '재무팀 상세' })
    expect(await within(detail).findByText('윤서진')).toBeInTheDocument()
  })

  it('앞 부서의 늦은 응답이 지금 부서의 구성원을 덮지 않습니다', async () => {
    server.use(
      http.get('*/api/employees', async ({ request }) => {
        if (new URL(request.url).searchParams.get('unitId') === 'ceo-office') {
          await delay(150)
          return HttpResponse.json({ items: [{ id: 'late', name: '늦은응답', unitId: 'ceo-office', unitName: '대표이사실', grade: 'ceo' }] })
        }
        return undefined
      }),
    )
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '인사팀' }))
    expect(await screen.findByText('서도윤')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 200))
    expect(screen.queryByText('늦은응답')).toBeNull()
  })

  it('구성원을 못 받으면 상세에 problem title을 보여 줍니다', async () => {
    server.use(http.get('*/api/employees', () => problemJson(503, 'erp 직원 조회가 실패했습니다.')))
    renderAt('/org')
    const detail = await screen.findByRole('region', { name: '대표이사실 상세' })
    expect(await within(detail).findByRole('alert')).toHaveTextContent('erp 직원 조회가 실패했습니다.')
  })

  it('등록부를 못 받으면 "맡은 에이전트 없음" 대신 실패를 알립니다', async () => {
    server.use(http.get('*/api/agent-registry', () => problemJson(500, '팩을 읽지 못했습니다.')))
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '인사팀' }))
    expect(await screen.findByText('팩을 읽지 못했습니다.')).toBeInTheDocument()
    expect(screen.queryByText('이 부서가 맡은 에이전트가 없습니다.')).toBeNull()
  })

  it('부서 목록을 못 받으면 problem title을 보여 줍니다', async () => {
    server.use(http.get('*/api/org/units', () => problemJson(503, 'erp가 응답하지 않습니다.')))
    renderAt('/org')
    expect(await screen.findByRole('alert')).toHaveTextContent('erp가 응답하지 않습니다.')
  })
})

describe('에이전트 등록부', () => {
  it('에이전트마다 담당 부서, 위험 등급별 실행, 도구를 보여 줍니다', async () => {
    renderAt('/agents')
    const hr = await screen.findByRole('region', { name: '인사' })
    expect(within(hr).getByText('로컬 모델만')).toBeInTheDocument()
    expect(within(hr).getByText('인사팀')).toBeInTheDocument()
    expect(within(hr).getByText('인사 정보는 외부 LLM으로 보내지 않습니다.')).toBeInTheDocument()
    expect(within(hr).getByText('실행 전 확인')).toBeInTheDocument()
    expect(within(hr).getByText(/범위가 넓을 때 실행 전 확인/)).toBeInTheDocument()
    expect(within(hr).getByText('도구 11개')).toBeInTheDocument()

    const assistant = screen.getByRole('region', { name: '전사 비서' })
    expect(within(assistant).getByText('기본 에이전트')).toBeInTheDocument()
    expect(within(assistant).getByText('외부 모델 허용')).toBeInTheDocument()
    expect(within(assistant).getByText('허용 안 함')).toBeInTheDocument()
    expect(within(assistant).getByText('room_reserve')).toBeInTheDocument()
    expect(screen.getAllByRole('region')).toHaveLength(4)

    const finance = screen.getByRole('region', { name: '재무' })
    expect(within(finance).getByText(/amount가 1,000,000보다 클 때 실행 전 확인/)).toBeInTheDocument()
  })

  it('#agent-<id>로 들어오면 그 카드 제목에 포커스를 둡니다', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    renderAt('/agents#agent-finance')
    const title = await screen.findByRole('heading', { level: 2, name: '재무' })
    await vi.waitFor(() => expect(title).toHaveFocus())
    expect(scroll).toHaveBeenCalled()
    delete (Element.prototype as Partial<Element>).scrollIntoView
  })

  it('불러오지 못하면 problem title을 보여 줍니다', async () => {
    server.use(http.get('*/api/agent-registry', () => problemJson(500, '팩을 읽지 못했습니다.')))
    renderAt('/agents')
    expect(await screen.findByRole('alert')).toHaveTextContent('팩을 읽지 못했습니다.')
  })
})
