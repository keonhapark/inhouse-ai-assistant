import { HttpResponse } from 'msw'
import type { Problem } from '../api/client'

export function problem(status: number, code: string, title: string): HttpResponse<Problem> {
  return HttpResponse.json(
    { type: `urn:problem:${code}`, title, status },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}
