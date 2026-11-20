import type { Schemas } from '../api/client'

type Prop = { title?: string; 'x-labels'?: Record<string, string> }
export type FieldRow = { key: string; label: string; value: string }

const raw = (v: unknown) => (v === null || v === undefined ? '–' : typeof v === 'object' ? JSON.stringify(v) : String(v))

/**
 * 결재 문서의 fields를 양식 스키마(GET /approval-forms의 fieldsSchema)로 읽기 좋게 폅니다.
 * 필드 이름은 속성의 title, 값은 x-labels(팩 forms.yaml)를 쓰고, 없으면 키와 원래 값을 그대로 둡니다.
 * 순서는 스키마 속성 순서이고 스키마에 없는 필드는 뒤에 붙입니다.
 */
export function fieldRows(fields: Record<string, unknown>, form?: Schemas['ApprovalForm']): FieldRow[] {
  const props = ((form?.fieldsSchema as { properties?: Record<string, Prop> } | undefined)?.properties ?? {}) as Record<string, Prop>
  const keys = [...Object.keys(props).filter((k) => k in fields), ...Object.keys(fields).filter((k) => !(k in props))]
  return keys.map((key) => {
    const p = props[key] ?? {}
    const v = fields[key]
    const label = typeof v === 'string' ? p['x-labels']?.[v] : undefined
    return { key, label: p.title ?? key, value: label ?? raw(v) }
  })
}
