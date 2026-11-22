// 와이어프레임 HTML을 흐름별 PNG로 뽑습니다: node research/wireframes/render.mjs
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from 'playwright'

const dir = import.meta.dirname
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1340, height: 900 }, deviceScaleFactor: 1 })
await page.goto(pathToFileURL(resolve(dir, 'index.html')).href)
// headless 브라우저에는 한글 글꼴이 없어 web이 쓰는 Pretendard(OFL)를 넣어 그립니다.
const font = pathToFileURL(resolve(dir, '../../../web/node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2')).href
await page.addStyleTag({
  content: `@font-face{font-family:P;src:url(${font}) format('woff2');font-weight:45 920}body{font-family:P,system-ui,sans-serif}`,
})
await page.evaluate(() => document.fonts.ready)
for (const id of ['f1', 'f2', 'f3', 'f4', 'f5']) {
  await page.locator(`#${id}`).screenshot({ path: resolve(dir, `${id}.png`) })
}
await browser.close()
