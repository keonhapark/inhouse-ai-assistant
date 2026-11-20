import { describe, expect, it } from 'vitest'
import { buildTree, pathTo, type Unit } from './tree'

const u = (id: string, parentId: string | null): Unit => ({ id, name: id, kind: 'team', parentId })

describe('buildTree', () => {
  it('parentId로 묶고 받은 순서를 지킵니다', () => {
    const roots = buildTree([u('top', null), u('b', 'top'), u('a', 'top'), u('a1', 'a')])
    expect(roots.map((r) => r.id)).toEqual(['top'])
    expect(roots[0].children.map((c) => c.id)).toEqual(['b', 'a'])
    expect(roots[0].children[1].children.map((c) => c.id)).toEqual(['a1'])
  })

  it('부모가 목록에 없으면 맨 위에 둡니다', () => {
    expect(buildTree([u('x', 'missing')]).map((r) => r.id)).toEqual(['x'])
  })

  it('부모 고리가 있어도 부서를 빠뜨리지 않습니다', () => {
    const roots = buildTree([u('a', 'b'), u('b', 'a')])
    const all = roots.flatMap((r) => [r.id, ...r.children.map((c) => c.id)])
    expect(all.sort()).toEqual(['a', 'b'])
  })
})

describe('pathTo', () => {
  it('맨 위부터 경로를 돌려줍니다', () => {
    const units = [u('top', null), u('mid', 'top'), u('leaf', 'mid')]
    expect(pathTo(units, 'leaf').map((x) => x.id)).toEqual(['top', 'mid', 'leaf'])
    expect(pathTo(units, 'nope')).toEqual([])
  })

  it('고리에서 멈춥니다', () => {
    expect(pathTo([u('a', 'b'), u('b', 'a')], 'a').map((x) => x.id)).toEqual(['b', 'a'])
  })
})
