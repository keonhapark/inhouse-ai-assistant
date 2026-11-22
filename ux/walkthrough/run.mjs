// 과업 걸어 보기 실행기입니다.
//   node walkthrough/run.mjs [--label baseline] [--only E1,A2]
// web을 모의 데이터 모드로 빌드해 띄우고, 브라우저 하나로 과업을 차례로 돌립니다.
// 결과: research/walkthrough/<label>/results.json, results.md, shots/*.jpg
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { chromium } from 'playwright'
import { buildMockWeb, serve } from '../lib/serve.mjs'
import { personas, tasks } from './tasks.mjs'
import { Blocked, User } from './user.mjs'

const { values: args } = parseArgs({
  options: {
    label: { type: 'string', default: 'baseline' },
    only: { type: 'string' },
    rebuild: { type: 'boolean', default: false },
  },
})
const root = resolve(import.meta.dirname, '..')
const outDir = resolve(root, 'research/walkthrough', args.label)
const shotDir = resolve(outDir, 'shots')
rmSync(outDir, { recursive: true, force: true })
mkdirSync(shotDir, { recursive: true })
mkdirSync(resolve(root, '.cache'), { recursive: true })

buildMockWeb({ force: args.rebuild })
const { server, url } = await serve()
const browser = await chromium.launch()

// 영수증 사진은 실행 때 그려서 씁니다(모의 서버는 사진 내용과 관계없이 정해 둔 값을 돌려줍니다).
const receipt = resolve(root, '.cache/receipt.png')
{
  const p = await browser.newPage({ viewport: { width: 320, height: 420 } })
  await p.setContent(`<div style="font:14px sans-serif;padding:16px;line-height:1.7">
    <b>가온식당 성수점</b><br>사업자 000-00-00000<br>2026-11-20 12:41<br><hr>
    점심 정식 x4 ... 42,000<br><hr><b>합계 42,000원</b></div>`)
  await p.screenshot({ path: receipt })
  await p.close()
}

const only = args.only?.split(',')
const results = []
for (const task of tasks.filter((t) => !only || only.includes(t.id))) {
  const persona = personas[task.persona]
  const ctx = await browser.newContext({ viewport: persona.viewport, locale: 'ko-KR', timezoneId: 'Asia/Seoul' })
  const page = await ctx.newPage()
  await page.goto(`${url}/login`)
  await page.getByLabel('사번').fill(persona.account)
  await page.getByLabel('비밀번호').fill('demo')
  await page.getByRole('button', { name: '로그인' }).click()
  await page.waitForURL(`${url}/`)

  const u = new User(page, { shotDir, taskId: task.id })
  const judged = new Map()
  const judge = (name, pass, evidence) => judged.set(name, { pass: Boolean(pass), evidence: evidence?.slice?.(0, 500) })
  const t0 = Date.now()
  let blocked = null
  try {
    await task.run(u, page, { receipt, judge })
  } catch (err) {
    if (!(err instanceof Blocked)) throw err
    blocked = err.step
    await u.shot('blocked')
  }
  const criteria = task.criteria.map(([kind, name]) => ({ kind, name, ...(judged.get(name) ?? { pass: null }) }))
  const doneOk = criteria.filter((c) => c.kind === '완료').every((c) => c.pass)
  const checkOk = criteria.filter((c) => c.kind === '확인').every((c) => c.pass)
  const outcome = blocked || !doneOk ? '실패' : checkOk ? '성공' : '부분 성공'
  results.push({
    id: task.id,
    persona: persona.name,
    title: task.title,
    outcome,
    blocked,
    counts: u.counts,
    steps: u.steps,
    ms: Date.now() - t0,
    criteria,
    shots: u.shots,
  })
  console.log(`${task.id} ${outcome}${blocked ? ` (${blocked})` : ''} 클릭 ${u.counts.clicks} 입력칸 ${u.counts.fields} 단계 ${u.steps.length}`)
  await ctx.close()
}
await browser.close()
server.close()

const meta = { label: args.label, at: new Date().toISOString(), mode: 'web 모의 데이터(msw)', personas }
writeFileSync(resolve(outDir, 'results.json'), JSON.stringify({ meta, results }, null, 2) + '\n')

const lines = [
  `# 과업 걸어 보기 결과: ${args.label}`,
  '',
  '가상 사용자 결과입니다. 사람이 아니라 스크립트가 화면에 보이는 이름으로 요소를 찾아 조작했습니다. 데이터는 web 모의 데이터 모드(msw)입니다.',
  '',
  '| 과업 | 페르소나 | 결과 | 클릭 | 입력 칸(글자) | 키 | 단계 | 막힌 곳 | 못 채운 확인 기준 |',
  '|---|---|---|---|---|---|---|---|---|',
  ...results.map((r) => {
    const miss = r.criteria.filter((c) => c.pass !== true).map((c) => c.name)
    const c = r.counts
    return `| ${r.id} ${r.title} | ${r.persona} | ${r.outcome} | ${c.clicks} | ${c.fields}(${c.chars}) | ${c.keys} | ${r.steps.length} | ${r.blocked ?? '-'} | ${miss.join('<br>') || '-'} |`
  }),
  '',
]
writeFileSync(resolve(outDir, 'results.md'), lines.join('\n'))
