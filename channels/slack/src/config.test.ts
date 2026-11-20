import { describe, expect, it } from 'vitest'
import { loadConfig } from './config.js'

describe('loadConfig', () => {
  const base = { SLACK_APP_TOKEN: 'a', SLACK_BOT_TOKEN: 'b', SLACK_BRIDGE_SECRET: 'c' }
  it('필수 값이 없으면 이름만 알리고 값은 드러내지 않습니다', () => {
    expect(() => loadConfig({ SLACK_APP_TOKEN: 'secret-value' })).toThrow('SLACK_BOT_TOKEN, SLACK_BRIDGE_SECRET')
    expect(() => loadConfig({ SLACK_APP_TOKEN: 'secret-value' })).not.toThrow(/secret-value/)
  })
  it('포트로 기본 주소를 만들고, 알림 주기는 10초 이상 숫자만 받습니다', () => {
    const c = loadConfig({ ...base, PORT_GATEWAY: '8610', PORT_WEB: '8600', SLACK_NOTIFY_INTERVAL_MS: 'abc' })
    expect(c.gatewayUrl).toBe('http://localhost:8610/api')
    expect(c.webUrl).toBe('http://localhost:8600')
    expect(c.notifyIntervalMs).toBe(60_000)
    expect(loadConfig({ ...base, SLACK_NOTIFY_INTERVAL_MS: '0' }).notifyIntervalMs).toBe(10_000)
  })
})
