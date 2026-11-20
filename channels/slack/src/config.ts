/** 환경 변수(저장소 .env). 토큰과 비밀값은 로그에 남기지 않습니다. */
export type Config = {
  appToken: string
  botToken: string
  gatewayUrl: string
  bridgeSecret: string
  webUrl: string
  notifyIntervalMs: number
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const missing = ['SLACK_APP_TOKEN', 'SLACK_BOT_TOKEN', 'SLACK_BRIDGE_SECRET'].filter((k) => !env[k])
  if (missing.length) throw new Error(`환경 변수가 없습니다: ${missing.join(', ')}(.env에 넣습니다)`)
  return {
    appToken: env.SLACK_APP_TOKEN!,
    botToken: env.SLACK_BOT_TOKEN!,
    bridgeSecret: env.SLACK_BRIDGE_SECRET!,
    gatewayUrl: env.GATEWAY_URL ?? `http://localhost:${env.PORT_GATEWAY ?? '8010'}/api`,
    webUrl: env.WEB_URL ?? `http://localhost:${env.PORT_WEB ?? '8000'}`,
    notifyIntervalMs: Number(env.SLACK_NOTIFY_INTERVAL_MS ?? 60_000),
  }
}
