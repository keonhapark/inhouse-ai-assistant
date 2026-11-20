export type Redaction = { entity: string; placeholder: string; messageIndex: number; start: number; end: number }
export type Segment = { text: string; redaction?: Redaction }

/**
 * 가림 뒤 본문을 가린 자리와 나머지로 나눕니다. 위치는 UTF-16(자바스크립트 문자열 위치)입니다.
 * 범위가 본문을 벗어나거나 앞 범위와 겹치면 그 항목은 표시하지 않고 글은 그대로 둡니다.
 */
export function segments(content: string, redactions: Redaction[], messageIndex: number): Segment[] {
  const mine = redactions.filter((r) => r.messageIndex === messageIndex).sort((a, b) => a.start - b.start)
  const out: Segment[] = []
  let at = 0
  for (const r of mine) {
    if (r.start < at || r.end <= r.start || r.end > content.length) continue
    if (r.start > at) out.push({ text: content.slice(at, r.start) })
    out.push({ text: content.slice(r.start, r.end), redaction: r })
    at = r.end
  }
  if (at < content.length) out.push({ text: content.slice(at) })
  return out
}

/** 가린 종류의 화면 이름. 모르는 종류는 그대로 보여 줍니다. */
const ENTITY: Record<string, string> = {
  KR_RRN: '주민등록번호',
  KR_PHONE: '전화번호',
  KR_BANK_ACCOUNT: '계좌번호',
  KR_BRN: '사업자등록번호',
  KR_DRIVER_LICENSE: '운전면허번호',
  KR_PASSPORT: '여권번호',
  EMAIL_ADDRESS: '이메일',
  CREDIT_CARD: '카드번호',
}
export const entityName = (e: string) => ENTITY[e] ?? e
