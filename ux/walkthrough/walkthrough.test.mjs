// 브라우저 없이 도는 시험입니다: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { outcomeOf } from './outcome.mjs'
import { tasks } from './tasks.mjs'

test('과업마다 judge로 부르는 기준 이름이 criteria와 같습니다', () => {
  for (const t of tasks) {
    const called = new Set([...t.run.toString().matchAll(/judge\(\s*'([^']+)'/g)].map((m) => m[1]))
    const declared = new Set(t.criteria.map(([, name]) => name))
    assert.deepEqual([...called].sort(), [...declared].sort(), t.id)
  }
})

test('과업 번호가 겹치지 않고 완료 기준이 하나 이상 있습니다', () => {
  assert.equal(new Set(tasks.map((t) => t.id)).size, tasks.length)
  for (const t of tasks) assert.ok(t.criteria.some(([kind]) => kind === '완료'), t.id)
})

test('결과 판정', () => {
  const c = (kind, pass) => ({ kind, name: `${kind}${pass}`, pass })
  assert.equal(outcomeOf({ criteria: [c('완료', true), c('확인', true)] }), '성공')
  assert.equal(outcomeOf({ criteria: [c('완료', true), c('확인', false)] }), '부분 성공')
  assert.equal(outcomeOf({ criteria: [c('완료', true), c('확인', null)] }), '부분 성공')
  assert.equal(outcomeOf({ criteria: [c('완료', null), c('확인', true)] }), '실패')
  assert.equal(outcomeOf({ blocked: '실행', criteria: [c('완료', true)] }), '실패')
  assert.equal(outcomeOf({ error: 'x', criteria: [c('완료', true)] }), '오류')
})
