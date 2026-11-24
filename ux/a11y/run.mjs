// 화면별 axe-core 자동 점검입니다.
//   node a11y/run.mjs [--label baseline]
// 밝음·어두움(prefers-color-scheme) 두 번 돌리고, 화면별 위반 규칙·영향도·요소 수를 셉니다.
// 화면마다 전체 스크린샷(shots/)을 남겨 휴리스틱 평가와 전후 비교에 씁니다.
// 자동 점검은 WCAG 문제의 일부만 잡습니다. 키보드 순서·스크린리더 낭독은 따로 봐야 합니다.
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseArgs } from 'node:util'
import AxeBuilder from '@axe-core/playwright'
import { chromium } from 'playwright'
import { buildMockWeb, serve } from '../lib/serve.mjs'

const { values: args } = parseArgs({ options: { label: { type: 'string', default: 'baseline' } } })
const root = resolve(import.meta.dirname, '..')
const outDir = resolve(root, 'research/a11y', args.label)
const shotDir = resolve(outDir, 'shots')
rmSync(outDir, { recursive: true, force: true }) // 이름이 바뀐 화면의 옛 캡처가 남지 않게
mkdirSync(shotDir, { recursive: true })

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']

async function login(page, url, account) {
  await page.goto(`${url}/login`)
  await page.getByLabel('사번').fill(account)
  await page.getByLabel('비밀번호').fill('demo')
  await page.getByRole('button', { name: '로그인' }).click()
  // 재설계 뒤에는 역할별 첫 화면으로 가므로(결재자 /approvals, 관리자 /ops/metrics) 로그인 화면을 떠나는 것만 기다립니다.
    await page.waitForURL((u) => u.pathname !== '/login')
    await page.getByRole('main').first().waitFor()
    await page.waitForTimeout(400)
}
async function say(page, text, waitFor) {
  const box = page.getByRole('textbox', { name: '메시지' })
  await box.fill(text)
  await box.press('Enter')
  await waitFor.waitFor({ timeout: 10000 })
  await page.waitForTimeout(1500) // 스트림 끝(done)까지 기다립니다
}

// 화면 이름, 계정, 그 상태로 만드는 조작.
// #557 재설계 뒤 주소(/approvals, /delegations, /ops/*)와 이름에 맞췄습니다. 화면 상태 14개는 기준선과 같은 것이고,
// 캡처 파일 이름(SLUG)도 기준선과 같게 두어 전후를 짝지어 볼 수 있게 했습니다.
const goLink = async (p, name, path) => {
  if (new URL(p.url()).pathname !== path) await p.getByRole('link', { name, exact: true }).click()
  await p.waitForURL((u) => u.pathname === path)
}
const screens = [
  ['로그인', null, async (p) => p.getByLabel('사번').waitFor()],
  ['로그인 오류', null, async (p) => {
    await p.getByLabel('사번').fill('E9999')
    await p.getByLabel('비밀번호').fill('x')
    await p.getByRole('button', { name: '로그인' }).click()
    await p.getByRole('alert').waitFor()
  }],
  ['채팅 빈 화면', 'E1001', async (p) => p.getByRole('textbox', { name: '메시지' }).waitFor()],
  ['채팅 답·근거·완료한 일', 'E1001', async (p) => {
    await say(p, '연차 규정 알려 줘', p.getByText(/근거( 규정)? \d+건/))
    await p.getByText(/근거( 규정)? \d+건/).click()
    await say(p, '내일 회의실 예약해 줘', p.getByRole('region', { name: '완료한 일' }))
  }],
  ['채팅 실행 전 확인', 'E1001', async (p) => {
    await say(p, '반차 결재 회수해 줘', p.getByRole('region', { name: /실행 전 확인/ }))
  }],
  ['결재 대기', 'E2001', async (p) => {
    await goLink(p, /^결재\s*(,|$)/, '/approvals')
    await p.getByRole('button', { name: /연차 휴가 신청/ }).waitFor()
  }],
  ['결재 문서 상세(대결)', 'E2001', async (p) => {
    await goLink(p, /^결재\s*(,|$)/, '/approvals')
    await p.getByRole('tab', { name: /^대결 대기/ }).click()
    await p.getByRole('tabpanel').getByRole('button').first().click()
    await p.getByRole('region', { name: /결재 문서/ }).waitFor()
  }],
  ['대결 지정 확인', 'E2001', async (p) => {
    await goLink(p, '대결 설정', '/delegations')
    const main = p.getByRole('main', { name: '대결 설정' })
    await main.getByRole('searchbox', { name: '이름 검색' }).fill('한지우')
    await main.getByRole('radio', { name: /한지우/ }).check()
    await main.getByRole('textbox', { name: '사유' }).fill('출장')
    await main.getByRole('button', { name: '내용 확인' }).click()
    await p.getByRole('region', { name: '대결 지정 확인' }).waitFor()
  }],
  ['조직도', 'E1001', async (p) => {
    await goLink(p, '조직도', '/org')
    await p.getByRole('navigation', { name: '부서' }).getByRole('button').first().waitFor()
  }],
  ['AI 에이전트', 'E1001', async (p) => {
    await goLink(p, 'AI 에이전트', '/agents')
    await p.getByRole('heading', { level: 1 }).waitFor()
    await p.waitForTimeout(500)
  }],
  ['운영 지표', 'E2008', async (p) => {
    await goLink(p, '운영 지표', '/ops/metrics')
    await p.getByRole('region', { name: '에이전트별 표' }).waitFor()
  }],
  ['외부 전송 기록', 'E2008', async (p) => {
    await goLink(p, '외부 전송 기록', '/ops/egress')
    await p.getByRole('main').getByRole('listitem').first().waitFor()
  }],
  ['감사 로그', 'E2008', async (p) => {
    await goLink(p, '감사 로그', '/ops/audit')
    await p.getByRole('region', { name: '감사 이벤트 표' }).waitFor()
  }],
  ['평가 보고서', 'E2008', async (p) => {
    await goLink(p, '평가 보고서', '/ops/eval')
    await p.getByRole('region', { name: '시나리오별 결과 표' }).waitFor()
  }],
]

// 캡처 파일 이름. CI 경로 검사가 한글 파일 이름을 읽지 못해 영문으로 둡니다. 기준선과 같은 이름입니다.
const SLUG = {
  '로그인 오류': 'login-error',
  '로그인': 'login',
  '채팅 빈 화면': 'chat-empty',
  '채팅 답·근거·완료한 일': 'chat-answer',
  '채팅 실행 전 확인': 'chat-preview',
  '결재 대기': 'inbox',
  '결재 문서 상세(대결)': 'inbox-doc-delegated',
  '대결 지정 확인': 'inbox-delegation-preview',
  '조직도': 'org',
  'AI 에이전트': 'agents',
  '운영 지표': 'admin-metrics',
  '외부 전송 기록': 'admin-egress',
  '감사 로그': 'admin-audit',
  '평가 보고서': 'eval',
}

const webVersion = buildMockWeb()
const { server, url } = await serve()
const browser = await chromium.launch()
const out = []
for (const scheme of ['light', 'dark']) {
  for (const [name, account, prepare] of screens) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR', colorScheme: scheme })
    const page = await ctx.newPage()
    try {
      if (account) await login(page, url, account)
      else await page.goto(`${url}/login`)
      await prepare(page)
    } catch (err) {
      // 화면을 만들지 못하면 그 화면만 오류로 남기고 다음으로 갑니다(빈 화면을 점검해 0건으로 세지 않게).
      out.push({ scheme, screen: name, error: String(err?.message ?? err).slice(0, 300), violations: [], incomplete: [] })
      console.log(`${scheme} ${name}: 화면을 만들지 못함`)
      await ctx.close()
      continue
    }
    await page.mouse.move(1279, 799) // 마지막으로 누른 메뉴에 마우스가 머문 채(hover) 찍히지 않게
    await page.screenshot({ path: `${shotDir}/${scheme}-${SLUG[name]}.jpg`, type: 'jpeg', quality: 70, fullPage: true })
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
writeFileSync(resolve(outDir, 'results.json'), JSON.stringify({ meta: { label: args.label, at: new Date().toISOString(), web: webVersion, axeVersion, tags: TAGS }, screens: out }, null, 2) + '\n')

// 요약 표: 화면 × 테마, 영향도별 요소 수
const IMPACTS = ['critical', 'serious', 'moderate', 'minor']
const lines = [
  `# axe-core 점검 결과: ${args.label}`,
  '',
  `axe-core ${axeVersion}, 규칙 묶음 ${TAGS.join(', ')}. web 모의 데이터 모드(web 버전 \`${webVersion}\`), 1280×800.`,
  '',
  '| 화면 | 테마 | 위반 규칙 | 위반 요소 | critical | serious | moderate | minor | 규칙 |',
  '|---|---|---|---|---|---|---|---|---|',
  ...out.map((s) => {
    const by = (i) => s.violations.filter((v) => v.impact === i).reduce((a, v) => a + v.nodes, 0)
    const total = s.violations.reduce((a, v) => a + v.nodes, 0)
    if (s.error) return `| ${s.screen} | ${s.scheme === 'light' ? '밝음' : '어두움'} | 오류: ${s.error} | | | | | | |`
    return `| ${s.screen} | ${s.scheme === 'light' ? '밝음' : '어두움'} | ${s.violations.length} | ${total} | ${IMPACTS.map(by).join(' | ')} | ${s.violations.map((v) => `\`${v.id}\`(${v.nodes})`).join(' ') || '-'} |`
  }),
  '',
]
writeFileSync(resolve(outDir, 'results.md'), lines.join('\n'))
