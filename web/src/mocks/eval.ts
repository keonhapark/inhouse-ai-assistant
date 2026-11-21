import { http, HttpResponse } from 'msw'
import type { Schemas } from '../api/client'
import { employeeForToken } from './data'
import { problem } from './problem'
// 실제 1단계 보고서(eval/reports/2026-11-20-normal-stage1.json)를 그대로 옮긴 것입니다(summary는 하네스가 씀, #345).
import stage1 from './fixtures/eval-normal-stage1.json'

// openapi-typescript가 JSON Schema의 $defs를 속성으로 옮겨 적어 뺍니다(응답 본문에는 없음).
type Report = Omit<Schemas['report.schema'], '$defs'>

const REPORTS: Record<string, { title: string; report: Report }> = {
  '2026-11-20-normal-stage1': { title: '1단계 평가 보고서(정상 셋, 세 조건, 1회)', report: stage1 as unknown as Report },
}

function guard(request: Request): Response | null {
  const me = employeeForToken(request.headers.get('Authorization'))
  if (!me) return problem(401, 'unauthorized', '로그인이 필요합니다.')
  if (!me.roles.includes('auditor')) return problem(403, 'forbidden', '감사 조회 역할이 필요합니다.')
  return null
}

const api = (path: string) => `*/api${path}`

export const evalHandlers = [
  http.get(api('/eval/reports'), ({ request }) => {
    const denied = guard(request)
    if (denied) return denied
    const items: Schemas['EvalReportSummary'][] = Object.entries(REPORTS).map(([reportId, { title, report: r }]) => ({
      reportId,
      title,
      startedAt: r.meta.started_at,
      finishedAt: r.meta.finished_at || null,
      sets: [...new Set(r.rows.map((x) => x.set))],
      conditions: r.meta.conditions,
      repeats: r.meta.repeats,
      packStage: r.meta.pack_stage ?? null,
      doneRuns: r.meta.done_runs,
      plannedRuns: r.meta.planned_runs,
      complete: r.meta.complete,
      hasSummary: !!r.summary,
    }))
    return HttpResponse.json({ items })
  }),

  http.get(api('/eval/reports/:id'), ({ request, params }) => {
    const denied = guard(request)
    if (denied) return denied
    const found = REPORTS[String(params.id)]
    return found ? HttpResponse.json(found.report) : problem(404, 'not-found', '보고서를 찾지 못했습니다.')
  }),
]
