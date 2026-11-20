import type { Schemas } from '../api/client'

export type Unit = Schemas['Unit']
export type UnitNode = Unit & { children: UnitNode[] }

/**
 * 부서 목록을 parentId로 나무로 묶습니다. 받은 순서를 지키고, 부모가 목록에 없는 부서는 맨 위에 둡니다.
 * 부모 고리(A→B→A)가 있으면 고리에 든 부서도 맨 위로 올려 빠뜨리지 않습니다.
 */
export function buildTree(units: Unit[]): UnitNode[] {
  const nodes = new Map(units.map((u) => [u.id, { ...u, children: [] as UnitNode[] }]))
  const roots: UnitNode[] = []
  for (const n of nodes.values()) {
    const parent = n.parentId ? nodes.get(n.parentId) : undefined
    if (parent && !reaches(nodes, parent.id, n.id)) parent.children.push(n)
    else roots.push(n)
  }
  return roots
}

/** from에서 부모를 따라 올라가다 target을 만나면 true(target을 부모로 삼으면 고리가 생김). */
function reaches(nodes: Map<string, UnitNode>, from: string, target: string): boolean {
  const seen = new Set<string>()
  for (let cur: string | null | undefined = from; cur && !seen.has(cur); cur = nodes.get(cur)?.parentId) {
    if (cur === target) return true
    seen.add(cur)
  }
  return false
}

/** 맨 위 부서부터 id까지의 경로. 없는 id면 빈 배열입니다. */
export function pathTo(units: Unit[], id: string): Unit[] {
  const byId = new Map(units.map((u) => [u.id, u]))
  const path: Unit[] = []
  const seen = new Set<string>()
  for (let cur = byId.get(id); cur && !seen.has(cur.id); cur = cur.parentId ? byId.get(cur.parentId) : undefined) {
    seen.add(cur.id)
    path.unshift(cur)
  }
  return path
}
