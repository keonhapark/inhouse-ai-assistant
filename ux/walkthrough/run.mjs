// 과업 걸어 보기 실행기입니다.
//   node walkthrough/run.mjs [--label baseline] [--only E1,A2] [--rebuild]
// web을 모의 데이터 모드로 빌드해 띄우고, 브라우저 하나로 과업을 차례로 돌립니다.
// 결과: research/walkthrough/<label>/results.json, results.md, shots/*.jpg
// --only를 주면 그 과업의 결과만 바꾸고 나머지는 그대로 둡니다.
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { chromium } from 'playwright'
import { buildMockWeb, serve } from '../lib/serve.mjs'
import { outcomeOf, summarize } from './outcome.mjs'
import { personas, tasks } from './tasks.mjs'
import { Blocked, User } from './user.mjs'

const { values: args } = parseArgs({
  options: {
    label: { type: 'string', default: 'baseline' },
    only: { type: 'string' },
    rebuild: { type: 'boolean', default: false },
    // 페르소나 기기 대신 이 창 크기로 돌립니다(예: 768x1024, 태블릿 폭 확인)
    viewport: { type: 'string' },
  },
})
const root = resolve(import.meta.dirname, '..')
const outDir = resolve(root, 'research/walkthrough', args.label)
const shotDir = resolve(outDir, 'shots')
const only = args.only?.split(',')
const jsonPath = resolve(outDir, 'results.json')

// 전체 실행이면 폴더를 비우고, --only면 그 과업의 스크린샷만 지웁니다.
let results = []
if (only && existsSync(jsonPath)) {
  results = JSON.parse(readFileSync(jsonPath, 'utf8')).results
  for (const f of existsSync(shotDir) ? readdirSync(shotDir) : []) {
    if (only.some((id) => f.startsWith(`${id}-`))) rmSync(resolve(shotDir, f))
  }
} else {
  rmSync(outDir, { recursive: true, force: true })
}
mkdirSync(shotDir, { recursive: true })
mkdirSync(resolve(root, '.cache'), { recursive: true })

const webVersion = buildMockWeb({ force: args.rebuild })
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

const meta = { label: args.label, at: new Date().toISOString(), mode: 'web 모의 데이터(msw)', web: webVersion, viewport: args.viewport ?? '페르소나 기기', personas }
const save = () => {
  const order = new Map(tasks.map((t, i) => [t.id, i]))
  results.sort((a, b) => order.get(a.id) - order.get(b.id))
  writeFileSync(jsonPath, JSON.stringify({ meta, results }, null, 2) + '\n')
  writeFileSync(resolve(outDir, 'results.md'), summarize(meta, results))
}

for (const task of tasks.filter((t) => !only || only.includes(t.id))) {
  const persona = personas[task.persona]
  const [vw, vh] = args.viewport?.split('x').map(Number) ?? []
  const viewport = vw ? { width: vw, height: vh } : persona.viewport
  const ctx = await browser.newContext({ viewport, locale: 'ko-KR', timezoneId: 'Asia/Seoul' })
  const page = await ctx.newPage()
  const u = new User(page, { shotDir, taskId: task.id })
  const names = new Set(task.criteria.map(([, name]) => name))
  const judged = new Map()
  const judge = (name, pass, evidence) => {
    // 기준 이름이 어긋나면 그 기준이 조용히 "못 봄"으로 남으므로 바로 멈춥니다.
    if (!names.has(name)) throw new Error(`${task.id}: criteria에 없는 기준입니다: ${name}`)
    judged.set(name, { pass: Boolean(pass), evidence: evidence?.slice?.(0, 500) })
  }
  const t0 = Date.now()
  let blocked = null
  let error = null
  try {
    await page.goto(`${url}/login`)
    await page.getByLabel('사번').fill(persona.account)
    await page.getByLabel('비밀번호').fill('demo')
    await page.getByRole('button', { name: '로그인' }).click()
    // 재설계 뒤에는 역할별 첫 화면으로 가므로(결재자 /approvals, 관리자 /ops/metrics) 로그인 화면을 떠나는 것만 기다립니다.
    await page.waitForURL((u) => u.pathname !== '/login')
    await page.getByRole('main').first().waitFor()
    await page.waitForTimeout(400) // 역할별 첫 화면으로 다시 보내는 이동이 끝날 때까지
    await task.run(u, page, { receipt, judge })
  } catch (err) {
    if (err instanceof Blocked) {
      blocked = err.step
      await u.shot('blocked').catch(() => {})
    } else {
      // 스크립트 오류는 과업 실패와 다르게 남기고 다음 과업으로 갑니다.
      error = String(err?.message ?? err).slice(0, 500)
    }
  }
  const criteria = task.criteria.map(([kind, name]) => ({ kind, name, ...(judged.get(name) ?? { pass: null }) }))
  const outcome = outcomeOf({ blocked, error, criteria })
  results = results.filter((r) => r.id !== task.id)
  results.push({
    id: task.id,
    persona: persona.name,
    title: task.title,
    outcome,
    blocked,
    error,
    counts: u.counts,
    actions: u.actions,
    steps: u.steps,
    ms: Date.now() - t0,
    criteria,
    shots: u.shots,
  })
  save()
  console.log(`${task.id} ${outcome}${blocked ? ` (${blocked})` : ''}${error ? ` 오류: ${error}` : ''} 클릭 ${u.counts.clicks} 입력칸 ${u.counts.fields} 조작 단계 ${u.actions}`)
  await ctx.close()
}
await browser.close()
server.close()
