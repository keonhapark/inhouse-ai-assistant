// 다듬은 판에 파스텔 강조색 후보를 덮어 찍습니다: node mockups/render-accents.mjs
// 결과: refined/accents/<후보>-<화면>-<밝음|어두움>.png
import { readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from 'playwright'

const here = import.meta.dirname
const font = pathToFileURL(resolve(here, '../../web/node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2')).href
const accents = readdirSync(resolve(here, 'refined/accents')).filter((f) => f.endsWith('.css')).map((f) => f.slice(0, -4))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route(/cdn\.jsdelivr\.net/, (r) => r.fulfill({ status: 200, contentType: 'text/css', body: '' }))
for (const accent of accents) {
  for (const screen of ['chat', 'approvals']) {
    for (const scheme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: scheme })
      await page.goto(pathToFileURL(resolve(here, 'refined', `${screen}.html`)).href)
      await page.addStyleTag({ content: `@font-face{font-family:'Pretendard Variable';src:url(${font}) format('woff2');font-weight:45 920}` })
      // 버튼 배경 전환(transition)이 도는 중에 찍히지 않게 끕니다.
      await page.addStyleTag({ content: '*{transition:none!important}' })
      await page.addStyleTag({ path: resolve(here, 'refined/accents', `${accent}.css`) })
      await page.evaluate(() => document.fonts.ready)
      await page.screenshot({ path: resolve(here, 'refined/accents', `${accent}-${screen}-${scheme}.png`) })
    }
  }
}
await browser.close()
