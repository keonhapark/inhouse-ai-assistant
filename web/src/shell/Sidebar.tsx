import * as Menu from '@radix-ui/react-dropdown-menu'
import { Check, LogOut, PanelLeft, Search, Sparkles } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import type { Schemas } from '../api/client'
import { gradeName } from '../display/names'
import { navFor } from './nav'
import { usePendingCount } from './pending'
import { THEMES, useTheme, type Theme } from './theme'

type Props = {
  me: Schemas['Employee']
  collapsed: boolean
  onToggle(): void
  onOpenPalette(): void
  onLogout(): void
}

/** 이니셜: 이름의 마지막 두 글자(한국 이름은 성을 빼고 부르는 관례) */
const initials = (name: string) => (name.length > 2 ? name.slice(-2) : name)

/** 왼쪽 탐색 막대(ux/design-system.md 3.1): 브랜드 → 찾기·이동 → 메뉴 묶음 → 사용자 메뉴 */
export function Sidebar({ me, collapsed, onToggle, onOpenPalette, onLogout }: Props) {
  const pending = usePendingCount()
  const [theme, setTheme] = useTheme()
  return (
    <nav className="sidebar" aria-label="주 메뉴" data-collapsed={collapsed || undefined}>
      <div className="sidebar__brand">
        <span className="sidebar__logo" aria-hidden>
          <Sparkles />
        </span>
        <span className="sidebar__label">사내 AI 비서</span>
        <button type="button" className="icon-btn sidebar__toggle" aria-label="탐색 막대 접기" aria-pressed={collapsed} onClick={onToggle}>
          <PanelLeft aria-hidden />
        </button>
      </div>

      {/* 이름은 보이는 글자 그대로("찾기·이동 Ctrl K", WCAG 2.5.3). 접혀도 라벨은 시각적으로만 숨어 이름에 남습니다 */}
      <button type="button" className="sidebar__search" onClick={onOpenPalette} aria-keyshortcuts="Control+K Meta+K" title={collapsed ? '찾기·이동' : undefined}>
        <Search aria-hidden />
        <span className="sidebar__label">찾기·이동</span>{' '}
        <kbd className="sidebar__label">Ctrl K</kbd>
      </button>

      {navFor(me).map((g) => (
        <div key={g.id} className="sidebar__group" role="group" aria-labelledby={`nav-${g.id}`}>
          <span id={`nav-${g.id}`} className="sidebar__heading sidebar__label">
            {g.label}
          </span>
          <ul>
            {g.items.map((it) => (
              <li key={it.to}>
                <NavLink to={it.to} end={it.end} className="sidebar__item" title={collapsed ? it.label : undefined}>
                  <it.icon aria-hidden />
                  <span className="sidebar__label">{it.label}</span>
                  {it.to === '/approvals' && pending ? (
                    <>
                      <span className="sidebar__count" aria-hidden>
                        {pending}
                      </span>
                      <span className="visually-hidden">, 결재할 문서 {pending}건</span>
                    </>
                  ) : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}

      <Menu.Root>
        {/* 이름은 보이는 글자(이름·부서·직급) 그대로입니다. 메뉴 단추라는 것은 aria-haspopup으로 읽힙니다 */}
        <Menu.Trigger className="sidebar__me">
          <span className="avatar" aria-hidden>
            {initials(me.name)}
          </span>
          <span className="sidebar__label sidebar__who">
            <span>{me.name}</span>{' '}
            <span className="sidebar__unit">
              {me.unitName} {gradeName(me.grade)}
            </span>
          </span>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="menu" side="top" align="start" sideOffset={6}>
            <Menu.Label className="menu__label">테마</Menu.Label>
            <Menu.RadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
              {THEMES.map((t) => (
                <Menu.RadioItem key={t.id} value={t.id} className="menu__item">
                  <Menu.ItemIndicator className="menu__check">
                    <Check aria-hidden />
                  </Menu.ItemIndicator>
                  {t.label}
                </Menu.RadioItem>
              ))}
            </Menu.RadioGroup>
            <Menu.Separator className="menu__sep" />
            <Menu.Item className="menu__item" onSelect={onLogout}>
              <LogOut aria-hidden />
              로그아웃
            </Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
    </nav>
  )
}
