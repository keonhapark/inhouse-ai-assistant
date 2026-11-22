import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { CommandPalette } from '../shell/CommandPalette'
import { Sidebar } from '../shell/Sidebar'
import '../shell/shell.css'
import './pages.css'

const COLLAPSE_KEY = 'inhouse-ai.sidebar-collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

/** 앱 셸(ux/design-system.md 3.1): 왼쪽 탐색 막대 + 화면. 명령 팔레트는 Ctrl K나 "찾기·이동"으로 엽니다 */
export function AppShell() {
  const { state, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [palette, setPalette] = useState(false)
  if (state.status !== 'signed-in') return null
  const me = state.employee

  function toggle() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
      } catch {
        // 저장하지 못해도 이번 화면에는 적용됩니다
      }
      return !c
    })
  }

  return (
    <div className="shell" data-collapsed={collapsed || undefined}>
      <Sidebar me={me} collapsed={collapsed} onToggle={toggle} onOpenPalette={() => setPalette(true)} onLogout={logout} />
      <div className="shell__main">
        <Outlet />
      </div>
      <CommandPalette me={me} open={palette} onOpenChange={setPalette} />
    </div>
  )
}
