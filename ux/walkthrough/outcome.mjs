// 과업 결과 판정과 요약 표입니다. 브라우저 없이 시험할 수 있게 실행기에서 떼어 두었습니다.

/**
 * - 오류: 스크립트가 깨짐(과업 결과가 아님)
 * - 실패: 막혔거나 완료 기준을 못 채움
 * - 부분 성공: 완료는 했지만 확인 기준을 못 채움(못 본 기준 포함)
 */
export function outcomeOf({ blocked, error, criteria }) {
  if (error) return '오류'
  const ok = (kind) => criteria.filter((c) => c.kind === kind).every((c) => c.pass === true)
  if (blocked || !ok('완료')) return '실패'
  return ok('확인') ? '성공' : '부분 성공'
}

/** 기준 하나를 표 칸 글로. pass가 null이면 막혀서 보지 못한 것입니다. */
export const missLabel = (c) => `${c.kind === '완료' ? '[완료] ' : ''}${c.name}${c.pass === null ? '(못 봄)' : ''}`

export function summarize(meta, results) {
  return [
    `# 과업 걸어 보기 결과: ${meta.label}`,
    '',
    `가상 사용자 결과입니다. 사람이 아니라 스크립트가 화면에 보이는 이름으로 요소를 찾아 조작했습니다. 데이터는 web 모의 데이터 모드(msw), web 버전 \`${meta.web}\`입니다.`,
    '',
    '- 조작 단계: 클릭·입력·키 단계 수. 눈으로 찾는 단계(see)는 빼서 과업끼리 견줄 수 있게 했습니다.',
    '- 못 채운 기준의 "(못 봄)"은 앞에서 막혀 판정하지 못한 기준입니다.',
    '',
    '| 과업 | 페르소나 | 결과 | 클릭 | 입력 칸(글자) | 키 | 조작 단계 | 막힌 곳 | 못 채운 기준 |',
    '|---|---|---|---|---|---|---|---|---|',
    ...results.map((r) => {
      const miss = r.criteria.filter((c) => c.pass !== true).map(missLabel)
      const c = r.counts
      const where = r.error ? `오류: ${r.error}` : (r.blocked ?? '-')
      return `| ${r.id} ${r.title} | ${r.persona} | ${r.outcome} | ${c.clicks} | ${c.fields}(${c.chars}) | ${c.keys} | ${r.actions} | ${where} | ${miss.join('<br>') || '-'} |`
    }),
    '',
  ].join('\n')
}
