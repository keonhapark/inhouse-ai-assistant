import { describe, expect, it } from 'vitest'
import { problemTitle } from './client'

describe('problemTitle', () => {
  it('제목과 같은 말인 상세는 붙이지 않습니다', () => {
    expect(problemTitle({ title: '본인이 올린 문서는 결재할 수 없습니다', detail: '본인이 올린 문서는 결재할 수 없습니다.' })).toBe('본인이 올린 문서는 결재할 수 없습니다')
    expect(problemTitle({ title: '결재할 수 없습니다. 이미 처리된 문서입니다.', detail: '이미 처리된 문서입니다.' })).toBe('결재할 수 없습니다. 이미 처리된 문서입니다.')
  })

  it('상세가 제목을 품으면 상세만, 제목이 상세를 품으면 제목만 보입니다(공백·끝 문장부호는 무시)', () => {
    expect(problemTitle({ title: '결재할 수 없습니다', detail: '결재할 수 없습니다. 이미 처리된 문서입니다.' })).toBe('결재할 수 없습니다. 이미 처리된 문서입니다.')
    expect(problemTitle({ title: '결재할  수 없습니다!', detail: '결재할 수\n없습니다' })).toBe('결재할  수 없습니다!')
  })

  it('다른 말인 상세는 제목 뒤에 붙이고, 제목이 없으면 기본 문장을 씁니다', () => {
    expect(problemTitle({ title: '결재할 수 없습니다.', detail: '문서가 이미 반려됐습니다.' })).toBe('결재할 수 없습니다. 문서가 이미 반려됐습니다.')
    expect(problemTitle(undefined, '기본')).toBe('기본')
  })
})
