import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

function renderAt(path: string, employeeId = 'emp-1001') {
  tokenStore.set(`mock.${employeeId}`)
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
    const members = within(detail).getByRole('region', { name: '구성원' })
    const rows = await within(members).findAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('서도윤부서장')
    expect(rows).toHaveLength(3)
    expect(within(members).getByText('3명')).toBeInTheDocument()
    expect(within(detail).getByRole('list', { name: '상위 부서' })).toHaveTextContent('대표이사실경영지원본부')
    expect(within(detail).getByRole('link', { name: '인사 담당 AI' })).toHaveAttribute('href', '/agents#agent-hr')
    expect(within(tree).getByRole('button', { name: '인사팀' })).toHaveAttribute('aria-current', 'true')
  })

  it('구성원이 없는 부서는 안내 문장을 보여 줍니다', async () => {
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '영업팀' }))
    expect(await screen.findByText('이 부서에 바로 속한 구성원이 없습니다. 하위 부서를 골라 보세요.')).toBeInTheDocument()
    expect(screen.getByText('이 부서가 맡은 AI 에이전트가 없습니다.')).toBeInTheDocument()
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

  it('AI 에이전트를 못 받으면 "맡은 AI 에이전트 없음" 대신 실패를 알립니다', async () => {
    server.use(http.get('*/api/agent-registry', () => problemJson(500, '팩을 읽지 못했습니다.')))
    const user = renderAt('/org')
    const tree = await screen.findByRole('navigation', { name: '부서' })
    await user.click(await within(tree).findByRole('button', { name: '인사팀' }))
    expect(await screen.findByText('팩을 읽지 못했습니다.')).toBeInTheDocument()
    expect(screen.queryByText('이 부서가 맡은 AI 에이전트가 없습니다.')).toBeNull()
  })

  it('부서 목록을 못 받으면 problem title을 보여 줍니다', async () => {
    server.use(http.get('*/api/org/units', () => problemJson(503, 'erp가 응답하지 않습니다.')))
    renderAt('/org')
    expect(await screen.findByRole('alert')).toHaveTextContent('erp가 응답하지 않습니다.')
  })
})

describe('사람 찾기', () => {
  it('이름 일부로 찾고, 고르면 그 사람의 부서를 열어 행을 표시합니다', async () => {
    const user = renderAt('/org')
    await screen.findByRole('region', { name: '대표이사실 상세' })
    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '서진')
    const found = await screen.findByRole('region', { name: '찾은 사람' })
    // 찾는 동안에는 부서 나무 대신 결과를 보입니다
    expect(screen.queryByRole('navigation', { name: '부서' })).toBeNull()
    const hit = await within(found).findByRole('button', { name: '윤서진' })
    expect(hit).toHaveAccessibleDescription('팀장 · 재무팀')
    await user.click(hit)

    const detail = await screen.findByRole('region', { name: '재무팀 상세' })
    expect(within(detail).getByRole('heading', { level: 2, name: /재무팀/ })).toHaveFocus()
    const row = (await within(detail).findByText('윤서진')).closest('.group__row')
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(hit).toHaveAttribute('aria-current', 'true')
  })

  it('맞는 사람이 없으면 알리고, Esc로 지우면 부서 나무로 돌아갑니다', async () => {
    const user = renderAt('/org')
    const box = await screen.findByRole('searchbox', { name: '사람 찾기' })
    await user.type(box, '없는사람')
    // 늘 있는 알림 영역이 0건 문장을 읽습니다
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('이름에 “없는사람”이 들어간 사람이 없습니다.'))
    await user.keyboard('{Escape}')
    expect(box).toHaveValue('')
    expect(await screen.findByRole('navigation', { name: '부서' })).toBeInTheDocument()
  })

  it('앞 낱말의 늦은 결과가 지금 결과를 덮지 않습니다', async () => {
    server.use(
      http.get('*/api/employees', async ({ request }) => {
        if (new URL(request.url).searchParams.get('q') === '서') {
          await delay(400)
          return HttpResponse.json({ items: [{ id: 'late', name: '늦은응답', unitId: 'hr', unitName: '인사팀', grade: 'staff' }] })
        }
        return undefined
      }),
    )
    const user = renderAt('/org')
    const box = await screen.findByRole('searchbox', { name: '사람 찾기' })
    await user.type(box, '서')
    // 첫 요청이 나간 뒤 낱말을 바꿉니다
    await delay(300)
    await user.type(box, '도')
    expect(await screen.findByRole('button', { name: '서도윤' })).toBeInTheDocument()
    await delay(400)
    expect(screen.queryByText('늦은응답')).toBeNull()
  })

  it('글자를 멈춘 뒤 한 번만 찾습니다', async () => {
    const asked: string[] = []
    server.use(
      http.get('*/api/employees', ({ request }) => {
        const q = new URL(request.url).searchParams.get('q')
        if (q) asked.push(q)
        return undefined
      }),
    )
    const user = renderAt('/org')
    await user.type(await screen.findByRole('searchbox', { name: '사람 찾기' }), '윤서진')
    expect(await screen.findByRole('button', { name: '윤서진' })).toBeInTheDocument()
    expect(asked).toEqual(['윤서진'])
  })

  it('주소의 ?person=으로 들어오면 그 행을 표시하고, 같은 부서의 다른 사람을 고르면 표시를 옮깁니다', async () => {
    const user = renderAt('/org?unit=finance&person=emp-2003')
    const detail = await screen.findByRole('region', { name: '재무팀 상세' })
    const row = (name: string) => within(detail).getByText(name).closest('.group__row')
    await within(detail).findByText('오민재')
    expect(row('오민재')).toHaveAttribute('aria-current', 'true')
    expect(row('윤서진')).not.toHaveAttribute('aria-current')

    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '윤서진')
    await user.click(await screen.findByRole('button', { name: '윤서진' }))
    await vi.waitFor(() => expect(row('윤서진')).toHaveAttribute('aria-current', 'true'))
    expect(row('오민재')).not.toHaveAttribute('aria-current')
  })

  it('조직도에서 팔레트의 "사람 찾기"를 골라도 보던 부서를 그대로 둡니다', async () => {
    const user = renderAt('/org?unit=finance')
    await screen.findByRole('region', { name: '재무팀 상세' })
    await user.keyboard('{Control>}k{/Control}')
    await user.click(within(await screen.findByRole('dialog')).getByRole('option', { name: '사람 찾기' }))
    await vi.waitFor(() => expect(screen.getByRole('searchbox', { name: '사람 찾기' })).toHaveFocus())
    expect(screen.getByRole('region', { name: '재무팀 상세' })).toBeInTheDocument()
  })

  it('명령 팔레트의 "사람 찾기"로 들어오면 찾기 칸에 초점을 둡니다', async () => {
    const user = renderAt('/')
    await screen.findByRole('navigation', { name: '주 메뉴' })
    await user.keyboard('{Control>}k{/Control}')
    await user.click(within(await screen.findByRole('dialog')).getByRole('option', { name: '사람 찾기' }))
    await vi.waitFor(() => expect(screen.getByRole('searchbox', { name: '사람 찾기' })).toHaveFocus())
  })
})

describe('AI 에이전트', () => {
  it('담당 AI마다 담당 부서, 처리 방식, 할 수 있는 일과 실행 방식을 보여 줍니다', async () => {
    renderAt('/agents')
    const hr = await screen.findByRole('region', { name: '인사 담당 AI' })
    expect(within(hr).getByText('사내 처리')).toBeInTheDocument()
    expect(within(hr).getByText('인사팀')).toBeInTheDocument()
    expect(within(hr).getByText('인사 정보는 외부 LLM으로 보내지 않습니다.')).toBeInTheDocument()
    const tools = within(hr).getByRole('region', { name: '할 수 있는 일' })
    expect(within(tools).getByText('11가지')).toBeInTheDocument()
    // 실행 취소할 수 없는 일은 실행 전 확인, 넓은 범위의 대결 지정은 예외로 실행 전 확인
    const revoke = within(tools).getByText('대결 해제').closest('li') as HTMLElement
    expect(revoke).toHaveTextContent('실행 취소 불가')
    expect(revoke).toHaveTextContent('실행 전 확인')
    const register = within(tools).getByText('대결 지정').closest('li') as HTMLElement
    expect(register).toHaveTextContent('범위가 넓을 때 실행 전 확인')

    const assistant = screen.getByRole('region', { name: '전사 비서' })
    expect(within(assistant).getByText('맞는 담당 AI가 없으면 전사 비서가 답합니다.')).toBeInTheDocument()
    expect(within(assistant).getByText('외부 AI 사용')).toBeInTheDocument()
    const reserve = within(assistant).getByText('회의실 예약').closest('li') as HTMLElement
    // 직원에게는 도구 코드 이름을 보이지 않습니다
    expect(reserve).not.toHaveTextContent('room_reserve')
    expect(reserve).toHaveTextContent('바로 실행')
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(4)

    const finance = screen.getByRole('region', { name: '재무 담당 AI' })
    expect(within(finance).getByText('금액이 1,000,000원보다 클 때 실행 전 확인')).toBeInTheDocument()
  })

  it('감사 권한자에게는 도구 코드 이름을 작게 붙입니다', async () => {
    renderAt('/agents', 'emp-2008')
    const assistant = await screen.findByRole('region', { name: '전사 비서' })
    const reserve = within(assistant).getByText('회의실 예약').closest('li') as HTMLElement
    expect(within(reserve).getByText('room_reserve').tagName).toBe('CODE')
    const hr = screen.getByRole('region', { name: '인사 담당 AI' })
    expect(within(hr).getByText('대결 해제').closest('li')).toHaveTextContent('delegation_revoke')
  })

  it('허용하지 않는 등급의 일은 "하지 않음"으로 보이고 예외를 붙이지 않습니다', async () => {
    server.use(
      http.get('*/api/agent-registry', () =>
        HttpResponse.json({
          items: [
            {
              id: 'x',
              name: '총무',
              version: '0.1.0',
              stage: 1,
              ownerUnitId: 'general-affairs',
              description: '시험용',
              tools: [{ name: 'approval_withdraw', risk: 'irreversible' }],
              allowedRisk: ['read'],
              modelPolicy: { mode: 'external_allowed' },
              riskPolicy: { read: 'auto', reversibleWrite: 'auto_with_undo', irreversible: 'confirm', overrides: [{ tool: 'approval_withdraw', when: 'always', action: 'confirm' }] },
              callable: false,
            },
          ],
        }),
      ),
    )
    renderAt('/agents')
    const x = await screen.findByRole('region', { name: '총무 담당 AI' })
    expect(within(x).getByText('사용할 수 없음')).toBeInTheDocument()
    const row = within(x).getByText('결재 회수').closest('li') as HTMLElement
    expect(within(row).getByText('하지 않음')).toBeInTheDocument()
    expect(row).not.toHaveTextContent('항상')
  })

  it('할 수 있는 일이 없으면 빈 목록 대신 알립니다', async () => {
    server.use(
      http.get('*/api/agent-registry', () =>
        HttpResponse.json({
          items: [
            {
              id: 'x',
              name: '총무',
              version: '0.1.0',
              stage: 1,
              ownerUnitId: 'general-affairs',
              description: '시험용',
              tools: [],
              allowedRisk: ['read'],
              modelPolicy: { mode: 'external_allowed' },
              riskPolicy: { read: 'auto', reversibleWrite: 'auto_with_undo', irreversible: 'confirm' },
            },
          ],
        }),
      ),
    )
    renderAt('/agents')
    const x = await screen.findByRole('region', { name: '총무 담당 AI' })
    expect(within(x).getByText('할 수 있는 일이 없습니다.')).toBeInTheDocument()
    expect(within(x).queryByText('0가지')).toBeNull()
  })

  it('#agent-<id>로 들어오면 그 에이전트 제목에 포커스를 둡니다', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    renderAt('/agents#agent-finance')
    const title = await screen.findByRole('heading', { level: 2, name: '재무 담당 AI' })
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
