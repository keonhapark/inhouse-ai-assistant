// 시안을 1440×900 PNG로 찍습니다: node mockups/render.mjs [mixed,ops]
// headless 브라우저에는 한글 글꼴이 없어 web이 쓰는 Pretendard(OFL)를 넣어 그립니다.
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from 'playwright'
import { DIRECTIONS } from './src/templates.mjs'

const here = import.meta.dirname
const font = pathToFileURL(resolve(here, '../../web/node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2')).href
const dirs = process.argv[2]?.split(',') ?? Object.keys(DIRECTIONS)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
// 바깥 서체 CDN을 막고 로컬 서체로 그립니다(네트워크와 관계없이 같은 그림).
await page.route(/cdn\.jsdelivr\.net/, (r) => r.fulfill({ status: 200, contentType: 'text/css', body: '' }))
for (const dir of dirs) {
  for (const screen of ['chat', 'approvals']) {
    await page.goto(pathToFileURL(resolve(here, dir, `${screen}.html`)).href)
    await page.addStyleTag({ content: `@font-face{font-family:'Pretendard Variable';src:url(${font}) format('woff2');font-weight:45 920}` })
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({ path: resolve(here, dir, `${screen}.png`) })
  }
}
await browser.close()
