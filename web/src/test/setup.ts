import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { resetMockChat } from '../mocks/chat'
import { resetMockInbox } from '../mocks/inbox'
import { resetLookups } from '../display/useLookups'
import { server } from '../mocks/node'

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
