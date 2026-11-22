// web을 모의 데이터 모드(msw)로 빌드해 정적 서버로 띄웁니다.
// vite 개발 서버보다 메모리를 적게 써서 WSL 여유가 적을 때도 돌릴 수 있습니다.
import { execFileSync } from 'node:child_process'
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = fileURLToPath(new URL('.', import.meta.url))
export const WEB_DIR = resolve(here, '../../web')
export const DIST = resolve(here, '../.cache/web-mock')

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.ico': 'image/x-icon',
}

/** web/ 의 마지막 커밋과 작업 트리 변경을 합친 표지입니다. 이것이 바뀌면 다시 빌드합니다. */
export function webVersion() {
  const git = (...a) => execFileSync('git', a, { cwd: WEB_DIR, encoding: 'utf8' }).trim()
  const head = git('log', '-1', '--format=%h', '--', '.')
  const dirty = git('status', '--porcelain', '--', '.') ? '+dirty' : ''
  return head + dirty
}

/**
 * web/node_modules가 있어야 합니다(`npm --prefix ../web ci`).
 * 재설계 뒤에 옛 빌드를 재지 않도록, 빌드한 web 버전이 지금과 다르면 다시 빌드합니다.
 */
export function buildMockWeb({ force = false } = {}) {
  const version = webVersion()
  const stamp = join(DIST, '.web-version')
  const built = existsSync(stamp) ? readFileSync(stamp, 'utf8') : null
  if (!force && built === version && !version.endsWith('+dirty')) return version
  execFileSync('npx', ['vite', 'build', '--mode', 'mock', '--outDir', DIST, '--emptyOutDir'], {
    cwd: WEB_DIR,
    stdio: 'inherit',
  })
  writeFileSync(stamp, version)
  return version
}

/** SPA라 없는 경로는 index.html로 돌립니다. */
export function serve(port = 0) {
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, 'http://x').pathname)
    let file = join(DIST, path)
    if (!file.startsWith(DIST + '/') || !existsSync(file) || statSync(file).isDirectory()) file = join(DIST, 'index.html')
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' })
    createReadStream(file).pipe(res)
  })
  return new Promise((ok) => server.listen(port, '127.0.0.1', () => ok({ server, url: `http://127.0.0.1:${server.address().port}` })))
}
