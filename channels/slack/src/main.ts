import { Bridge } from './bridge.js'
import { loadConfig } from './config.js'
import { httpGateway } from './gateway.js'
import { createApp, slackPort, wire } from './slack-app.js'

const config = loadConfig()
const app = createApp(config.appToken, config.botToken)
const me = await app.client.auth.test()
const bridge = new Bridge({
  botUserId: me.user_id,
  gateway: httpGateway({ baseUrl: config.gatewayUrl, bridgeSecret: config.bridgeSecret }),
  slack: slackPort(app),
  webUrl: config.webUrl,
  // 오류 객체만 남기고 토큰·본문은 넣지 않습니다.
  log: (msg, err) => app.logger.warn(msg, err instanceof Error ? err.message : ''),
})
wire(app, bridge)

await app.start()
app.logger.info(`슬랙 브리지가 시작했습니다. gateway ${config.gatewayUrl}`)
setInterval(() => void bridge.pollNotifications(), config.notifyIntervalMs).unref()
