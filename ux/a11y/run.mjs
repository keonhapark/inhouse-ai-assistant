// 화면별 axe-core 자동 점검입니다.
//   node a11y/run.mjs [--label baseline]
// 밝음·어두움(prefers-color-scheme) 두 번 돌리고, 화면별 위반 규칙·영향도·요소 수를 셉니다.
// 화면마다 전체 스크린샷(shots/)을 남겨 휴리스틱 평가와 전후 비교에 씁니다.
// 자동 점검은 WCAG 문제의 일부만 잡습니다. 키보드 순서·스크린리더 낭독은 따로 봐야 합니다.
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseArgs } from 'node:util'
import AxeBuilder from '@axe-core/playwright'
import { chromium } from 'playwright'
import { buildMockWeb, serve } from '../lib/serve.mjs'

const { values: args } = parseArgs({ options: { label: { type: 'string', default: 'baseline' } } })
const root = resolve(import.meta.dirname, '..')
const outDir = resolve(root, 'research/a11y', args.label)
const shotDir = resolve(outDir, 'shots')
mkdirSync(shotDir, { recursive: true })

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']

async function login(page, url, account) {
  await page.goto(`${url}/login`)
  await page.getByLabel('사번').fill(account)
  await page.getByLabel('비밀번호').fill('demo')
  await page.getByRole('button', { name: '로그인' }).click()
  await page.waitForURL(`${url}/`)
}
async function say(page, text, waitFor) {
  const box = page.getByRole('textbox', { name: '메시지' })
  await box.fill(text)
  await box.press('Enter')
  await waitFor.waitFor({ timeout: 10000 })
  await page.waitForTimeout(1500) // 스트림 끝(done)까지 기다립니다
}

// 화면 이름, 계정, 그 상태로 만드는 조작
const screens = [
  ['로그인', null, async (p) => p.getByLabel('사번').waitFor()],
  ['로그인 오류', null, async (p) => {
    await p.getByLabel('사번').fill('E9999')
    await p.getByLabel('비밀번호').fill('x')
    await p.getByRole('button', { name: '로그인' }).click()
    await p.getByRole('alert').waitFor()
  }],
  ['채팅 빈 화면', 'E1001', async () => {}],
  ['채팅 답·근거·실행한 일', 'E1001', async (p) => {
    await say(p, '연차 규정 알려 줘', p.getByText(/근거 \d+건/))
    await p.getByText(/근거 \d+건/).click()
    await say(p, '내일 회의실 예약해 줘', p.getByRole('region', { name: '실행한 일' }))
  }],
  ['채팅 실행 미리보기', 'E1001', async (p) => {
    await say(p, '반차 결재 회수해 줘', p.getByRole('region', { name: /실행 미리보기/ }))
  }],
  ['승인함 내 차례', 'E2001', async (p) => {
    await p.getByRole('link', { name: '승인함' }).click()
    await p.getByRole('button', { name: /연차 휴가 신청/ }).waitFor()
  }],
  ['승인함 문서 상세(대결)', 'E2001', async (p) => {
    await p.getByRole('link', { name: '승인함' }).click()
    await p.getByRole('tab', { name: '대결' }).click()
    await p.getByRole('button', { name: /출장 경비/ }).click()
    await p.getByRole('region', { name: /결재 문서/ }).waitFor()
  }],
  ['승인함 위임 미리보기', 'E2001', async (p) => {
    await p.getByRole('link', { name: '승인함' }).click()
    const panel = p.getByRole('complementary', { name: '대결 설정' })
    await panel.getByRole('searchbox').fill('한지우')
    await panel.getByRole('radio', { name: /한지우/ }).check()
    await panel.getByRole('textbox', { name: '사유' }).fill('출장')
    await panel.getByRole('button', { name: '미리보기' }).click()
    await p.getByRole('region', { name: '위임 미리보기' }).waitFor()
  }],
  ['조직도', 'E1001', async (p) => {
    await p.getByRole('link', { name: '조직도' }).click()
    await p.getByRole('navigation', { name: '부서' }).getByRole('button').first().waitFor()
  }],
  ['에이전트', 'E1001', async (p) => {
    await p.getByRole('link', { name: '에이전트' }).click()
    await p.getByRole('heading', { level: 1 }).waitFor()
    await p.waitForTimeout(500)
  }],
  ['관리 운영 지표', 'E2008', async (p) => {
    await p.getByRole('link', { name: '관리' }).click()
    await p.getByRole('region', { name: '에이전트별 표' }).waitFor()
  }],
  ['관리 외부 전송 기록', 'E2008', async (p) => {
    await p.getByRole('link', { name: '관리' }).click()
    await p.getByRole('tab', { name: '외부 전송 기록' }).click()
    await p.getByRole('tabpanel').getByRole('listitem').first().waitFor()
  }],
  ['관리 감사 로그', 'E2008', async (p) => {
    await p.getByRole('link', { name: '관리' }).click()
    await p.getByRole('tab', { name: '감사 로그' }).click()
    await p.getByRole('region', { name: '감사 이벤트 표' }).waitFor()
  }],
  ['평가 리포트', 'E2008', async (p) => {
    await p.getByRole('link', { name: '평가' }).click()
    await p.getByRole('region', { name: '시나리오별 결과 표' }).waitFor()
  }],
]

buildMockWeb()
const { server, url } = await serve()
const browser = await chromium.launch()
const out = []
for (const scheme of ['light', 'dark']) {
  for (const [name, account, prepare] of screens) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR', colorScheme: scheme })
    const page = await ctx.newPage()
    if (account) await login(page, url, account)
    else await page.goto(`${url}/login`)
    await prepare(page)
    await page.screenshot({ path: `${shotDir}/${scheme}-${name.replace(/[ ·()]+/g, '-').replace(/-$/, '')}.jpg`, type: 'jpeg', quality: 70, fullPage: true })
    const r = await new AxeBuilder({ page }).withTags(TAGS).analyze()
    const violations = r.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      wcag: v.tags.filter((t) => /^wcag\d/.test(t)),
      help: v.help,
      nodes: v.nodes.length,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
    }))
    out.push({ scheme, screen: name, violations, incomplete: r.incomplete.map((v) => ({ id: v.id, nodes: v.nodes.length })) })
    console.log(`${scheme} ${name}: 규칙 ${violations.length}, 요소 ${violations.reduce((a, v) => a + v.nodes, 0)}`)
    await ctx.close()
  }
}
await browser.close()
server.close()

const axeVersion = (await import('axe-core/package.json', { with: { type: 'json' } })).default.version
writeFileSync(resolve(outDir, 'results.json'), JSON.stringify({ meta: { label: args.label, at: new Date().toISOString(), axeVersion, tags: TAGS }, screens: out }, null, 2) + '\n')

// 요약 표: 화면 × 테마, 영향도별 요소 수
const IMPACTS = ['critical', 'serious', 'moderate', 'minor']
const lines = [
  `# axe-core 점검 결과: ${args.label}`,
  '',
  `axe-core ${axeVersion}, 규칙 묶음 ${TAGS.join(', ')}. web 모의 데이터 모드, 1280×800.`,
  '',
  '| 화면 | 테마 | 위반 규칙 | 위반 요소 | critical | serious | moderate | minor | 규칙 |',
  '|---|---|---|---|---|---|---|---|---|',
  ...out.map((s) => {
    const by = (i) => s.violations.filter((v) => v.impact === i).reduce((a, v) => a + v.nodes, 0)
    const total = s.violations.reduce((a, v) => a + v.nodes, 0)
    return `| ${s.screen} | ${s.scheme === 'light' ? '밝음' : '어두움'} | ${s.violations.length} | ${total} | ${IMPACTS.map(by).join(' | ')} | ${s.violations.map((v) => `\`${v.id}\`(${v.nodes})`).join(' ') || '-'} |`
  }),
  '',
]
writeFileSync(resolve(outDir, 'results.md'), lines.join('\n'))
