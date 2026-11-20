import { describe, expect, it } from 'vitest'
import { changeRows } from './format'

describe('changeRows', () => {
  it('create는 후 값만 보여 줍니다', () => {
    expect(changeRows({ op: 'create', resource: 'room_reservation', after: { room: 'A', size: 4 } })).toEqual([
      { field: 'room', before: undefined, after: 'A' },
      { field: 'size', before: undefined, after: '4' },
    ])
  })

  it('update는 바뀐 필드만 전 → 후로 보여 줍니다', () => {
    expect(
      changeRows({ op: 'update', resource: 'delegation', before: { status: 'active', to: 'x' }, after: { status: 'revoked', to: 'x' } }),
    ).toEqual([{ field: 'status', before: 'active', after: 'revoked' }])
  })

  it('delete는 전 값만, 빈 값은 "없음"으로 보여 줍니다', () => {
    expect(changeRows({ op: 'delete', resource: 'r', before: { note: null } })).toEqual([
      { field: 'note', before: '없음', after: undefined },
    ])
  })
})
