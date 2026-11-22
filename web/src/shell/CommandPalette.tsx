import * as Dialog from '@radix-ui/react-dialog'
import { Command } from 'cmdk'
import { FileCheck2, Monitor, Moon, SquarePen, Sun } from 'lucide-react'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { Schemas } from '../api/client'
import { isPaletteKey, NEW_CHAT } from './events'
import { navFor } from './nav'
import { THEMES, useTheme, type Theme } from './theme'

const THEME_ICON: Record<Theme, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }

type Props = { me: Schemas['Employee']; open: boolean; onOpenChange(open: boolean): void }

/**
 * 명령 팔레트(Ctrl K, ux/design-system.md 3.1). 화면 이동, 새 대화, 결재 대기 열기, 테마 바꾸기.
 * 동작은 cmdk(키보드 위아래·Enter·찾기), 대화상자(초점 가둠·Esc)는 Radix Dialog입니다.
 */
export function CommandPalette({ me, open, onOpenChange }: Props) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [theme, setTheme] = useTheme()

  // Ctrl K(맥은 ⌘ K)로 열고 닫습니다
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isPaletteKey(e)) {
        e.preventDefault()
        onOpenChange(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  const run = (f: () => void) => () => {
    onOpenChange(false)
    f()
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="palette__scrim" />
        <Dialog.Content className="palette" aria-describedby={undefined}>
          <Dialog.Title className="visually-hidden">찾기·이동</Dialog.Title>
          <Command label="찾기·이동" loop>
            <Command.Input className="palette__input" placeholder="화면이나 할 일 이름" />
            <Command.List className="palette__list">
              <Command.Empty className="palette__empty">맞는 항목이 없습니다.</Command.Empty>
              <Command.Group heading="할 일">
                <Command.Item onSelect={run(() => (pathname === '/' ? window.dispatchEvent(new Event(NEW_CHAT)) : navigate('/')))}>
                  <SquarePen aria-hidden />새 대화
                </Command.Item>
                <Command.Item onSelect={run(() => navigate('/approvals'))}>
                  <FileCheck2 aria-hidden />
                  결재 대기 열기
                </Command.Item>
              </Command.Group>
              <Command.Group heading="화면 이동">
                {navFor(me).flatMap((g) =>
                  g.items.map((it) => (
                    <Command.Item key={it.to} value={`${g.label} ${it.label}`} onSelect={run(() => navigate(it.to))}>
                      <it.icon aria-hidden />
                      {it.label}
                      <span className="palette__hint">{g.label}</span>
                    </Command.Item>
                  )),
                )}
              </Command.Group>
              <Command.Group heading="테마">
                {THEMES.map((t) => {
                  const Icon = THEME_ICON[t.id]
                  return (
                    <Command.Item key={t.id} value={`테마 ${t.label}`} onSelect={run(() => setTheme(t.id))}>
                      <Icon aria-hidden />
                      테마: {t.label}
                      {theme === t.id && <span className="palette__hint">지금 테마</span>}
                    </Command.Item>
                  )
                })}
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
