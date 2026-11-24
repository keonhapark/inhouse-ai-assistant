import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { koDate } from '../display/dates'
import { DateField, DateTimeField } from './DatePicker'

// 고른 값은 <output>(암묵 역할 status)에 보입니다
function Date1({ initial = '2026-11-23', max }: { initial?: string; max?: string }) {
  const [v, setV] = useState(initial)
  return (
    <>
      <DateField label="시작" value={v} max={max} onChange={setV} />
      <output>{v}</output>
    </>
  )
}

function DateTime1({ initial = '' }: { initial?: string }) {
  const [v, setV] = useState(initial)
  return (
    <>
      <DateTimeField label="끝" value={v} defaultTime="18:00" onChange={setV} />
      <output>{v}</output>
    </>
  )
}

describe('날짜 고르개', () => {
  it('한국식으로 보이고(요일 포함), 라벨과 값이 단추 이름으로 읽힙니다', () => {
    render(<Date1 />)
    expect(koDate('2026-11-23')).toBe('2026년 11월 23일(월)')
    expect(screen.getByRole('button', { name: '시작 2026년 11월 23일(월)' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '시작' })).toBeInTheDocument()
  })

  it('열면 고른 날에 초점을 두고, 화살표·PageDown·Home으로 옮겨 Enter로 고릅니다', async () => {
    const user = userEvent.setup()
    render(<Date1 />)
    await user.click(screen.getByRole('button', { name: /^시작/ }))
    const dialog = await screen.findByRole('dialog', { name: '시작 날짜 고르기' })
    expect(within(dialog).getByRole('heading', { name: '2026년 11월' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '2026년 11월 23일(월), 선택됨' })).toHaveFocus())
    await user.keyboard('{ArrowRight}{ArrowDown}')
    expect(screen.getByRole('button', { name: '2026년 12월 1일(화)' })).toHaveFocus()
    expect(within(dialog).getByRole('heading', { name: '2026년 12월' })).toBeInTheDocument()
    await user.keyboard('{PageDown}{Home}')
    // 2027년 1월 1일(금)이 든 주의 일요일
    expect(screen.getByRole('button', { name: '2026년 12월 27일(일)' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent('2026-12-27')
    expect(screen.queryByRole('dialog')).toBeNull()
    // 닫히면 초점이 단추로 돌아옵니다
    expect(screen.getByRole('button', { name: /^시작 2026년 12월 27일/ })).toHaveFocus()
  })

  it('max보다 뒤의 날은 고를 수 없습니다', async () => {
    const user = userEvent.setup()
    render(<Date1 max="2026-11-23" />)
    await user.click(screen.getByRole('button', { name: /^시작/ }))
    await screen.findByRole('dialog')
    const late = screen.getByRole('button', { name: '2026년 11월 24일(화)' })
    expect(late).toHaveAttribute('aria-disabled', 'true')
    await user.click(late)
    expect(screen.getByRole('status')).toHaveTextContent('2026-11-23')
  })

  it('날짜와 시각: 날짜를 고르기 전에는 시각이 막혀 있고, 고르면 기본 시각을 붙이며 24시간제로 바꿉니다', async () => {
    const user = userEvent.setup()
    render(<DateTime1 />)
    expect(screen.getByRole('button', { name: '끝 날짜 고르기' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '끝 시' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /^끝/ }))
    await screen.findByRole('dialog')
    await user.keyboard('{Enter}')
    expect(screen.getByRole('status').textContent).toMatch(/^\d{4}-\d{2}-\d{2}T18:00$/)
    await user.selectOptions(screen.getByRole('combobox', { name: '끝 시' }), '21')
    await user.selectOptions(screen.getByRole('combobox', { name: '끝 분' }), '30')
    expect(screen.getByRole('status').textContent).toMatch(/T21:30$/)
  })

  it('범위 밖 날은 키보드 Enter로도 고르지 못하고, 값이 없으면 범위 안 가장 가까운 날을 엽니다', async () => {
    const user = userEvent.setup()
    render(<Date1 initial="" max="2020-01-15" />)
    await user.click(screen.getByRole('button', { name: '시작 날짜 고르기' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '2020년 1월 15일(수)' })).toHaveFocus())
    await user.keyboard('{ArrowRight}{Enter}')
    expect(screen.getByRole('button', { name: '2020년 1월 16일(목)' })).toHaveFocus()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/^$/)
  })

  it('달 넘김 단추는 초점을 그대로 두고, Esc로 닫으면 단추로 초점이 돌아옵니다', async () => {
    const user = userEvent.setup()
    render(<Date1 />)
    await user.click(screen.getByRole('button', { name: /^시작/ }))
    const dialog = await screen.findByRole('dialog')
    const next = within(dialog).getByRole('button', { name: '다음 달' })
    await user.click(next)
    await user.click(next)
    expect(next).toHaveFocus()
    expect(within(dialog).getByRole('heading', { name: '2027년 1월' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: /^시작/ })).toHaveFocus()
  })

  it('disabled면 날짜 단추와 시·분이 모두 막힙니다', () => {
    render(<DateTimeField label="끝" value="2026-11-23T09:00" disabled onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /^끝/ })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '끝 시' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '끝 분' })).toBeDisabled()
  })

  it('10분 단위가 아닌 예전 값의 분도 그대로 고를 수 있습니다', () => {
    render(<DateTime1 initial="2026-11-23T09:05" />)
    expect(screen.getByRole('combobox', { name: '끝 분' })).toHaveValue('05')
  })
})

