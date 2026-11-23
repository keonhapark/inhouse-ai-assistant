import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { resetMockChat } from '../mocks/chat'
import { resetMockInbox } from '../mocks/inbox'
import { resetLookups } from '../display/useLookups'
import { server } from '../mocks/node'

// 전체 시험을 한꺼번에 돌리면 일꾼끼리 CPU를 나눠 첫 화면이 1초(기본값)를 넘길 때가 있어 findBy·waitFor를 3초까지 기다립니다
configure({ asyncUtilTimeout: 3000 })

// jsdom에 없는 브라우저 API(명령 팔레트 cmdk가 씀)
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoopResizeObserver as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= function () {}

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetMockChat()
  resetMockInbox()
  resetLookups()
  sessionStorage.clear()
})
afterAll(() => server.close())
