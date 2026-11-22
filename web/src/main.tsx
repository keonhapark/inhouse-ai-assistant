import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './styles/tokens.css'
import './styles/base.css'
import './components/components.css'
import { App } from './App'
import { AuthProvider } from './auth/AuthContext'
import { applyTheme, readTheme } from './shell/theme'

// 저장해 둔 테마를 첫 그림 전에 적용합니다
applyTheme(readTheme())

async function start() {
  // `npm run dev:mock`이면 gateway 계약 모의 서버(MSW)로 /api를 받습니다.
  if (import.meta.env.MODE === 'mock') {
    const { worker } = await import('./mocks/browser')
    await worker.start({ onUnhandledFrame: 'bypass' })
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  )
}

void start()
