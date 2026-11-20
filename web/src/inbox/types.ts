import type { Schemas } from '../api/client'

/**
 * 계약은 InboxItem.steps를 allOf로 erp 단계와 이름(approverName·actedByName)을 합쳐 정의합니다.
 * 생성 타입은 두 배열 타입의 교집합이 되어 다루기 어려워, 단계 하나에 필드를 합친 타입으로 바꿔 씁니다.
 */
export type Step = Schemas['ApprovalStep'] & { approverName?: string; actedByName?: string | null }
export type InboxItem = Omit<Schemas['InboxItem'], 'steps'> & { steps: Step[] }

/** 응답 경계에서 한 번만 바꿉니다. openapi-fetch가 응답 타입을 다시 펼쳐 Schemas['InboxItem']과도 맞지 않습니다. */
export function toInboxItem<T extends { id: string; steps: unknown }>(d: T): InboxItem {
  return d as unknown as InboxItem
}
