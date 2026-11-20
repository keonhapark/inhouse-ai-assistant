import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 포트는 docs/ports.md(PORT_BASE + 0, gateway는 + 10)를 따릅니다. `source scripts/env.sh <세션>` 뒤에 실행합니다.
const webPort = Number(process.env.PORT_WEB ?? 8600)
const gatewayUrl = process.env.GATEWAY_URL ?? `http://localhost:${process.env.PORT_GATEWAY ?? 8610}`

export default defineConfig({
  plugins: [react()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: {
      '/api': { target: gatewayUrl, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
