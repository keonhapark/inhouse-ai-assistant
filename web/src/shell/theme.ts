import { useCallback, useEffect, useState } from 'react'

/** 테마: 밝음·어두움·시스템(OS 설정). 시스템이면 data-theme를 지워 prefers-color-scheme를 따릅니다(tokens.css) */
export type Theme = 'light' | 'dark' | 'system'
export const THEMES: { id: Theme; label: string }[] = [
  { id: 'light', label: '밝음' },
  { id: 'dark', label: '어두움' },
  { id: 'system', label: '시스템' },
]

const KEY = 'inhouse-ai.theme'

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(t: Theme) {
  const root = document.documentElement
  if (t === 'system') delete root.dataset.theme
  else root.dataset.theme = t
  try {
    if (t === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, t)
  } catch {
    // 저장하지 못해도 이번 화면에는 적용됩니다
  }
}

/** 고른 테마와 바꾸는 함수. 여러 곳(사용자 메뉴, 명령 팔레트)이 같은 값을 보게 문서 이벤트로 알립니다 */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme)
  useEffect(() => {
    const on = () => setThemeState(readTheme())
    window.addEventListener('inhouse-ai:theme', on)
    return () => window.removeEventListener('inhouse-ai:theme', on)
  }, [])
  const setTheme = useCallback((t: Theme) => {
    applyTheme(t)
    setThemeState(t)
    window.dispatchEvent(new Event('inhouse-ai:theme'))
  }, [])
  return [theme, setTheme]
}
