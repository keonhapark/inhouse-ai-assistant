import type { Schemas } from '../api/client'

const ALL = '*'

/** 대결 범위 양식. "모든 양식"(["*"])이거나 고른 양식 목록입니다(DelegationScope.formTypes). */
type Props = {
  value: string[]
  /** GET /approval-forms 결과. 불러오지 못했으면 error에 이유 */
  forms: Schemas['ApprovalForm'][]
  error: string | null
  onChange(v: string[]): void
}

export function FormScope({ value, forms, error, onChange }: Props) {

  const all = value.includes(ALL)
  function toggle(id: string, on: boolean) {
    const next = on ? [...value.filter((v) => v !== ALL), id] : value.filter((v) => v !== id)
    onChange(next)
  }

  return (
    <fieldset className="picker">
      <legend>양식 범위</legend>
      <label className="picker__option">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? [ALL] : [])} />
        모든 양식
      </label>
      {forms.map((f) => (
        <label key={f.id} className="picker__option">
          <input type="checkbox" disabled={all} checked={!all && value.includes(f.id)} onChange={(e) => toggle(f.id, e.target.checked)} />
          {f.name}
        </label>
      ))}
      {error && (
        <p role="alert" className="alert">
          {error} 모든 양식만 고를 수 있습니다.
        </p>
      )}
      {value.length === 0 && (
        <p role="alert" className="alert">
          양식을 하나 이상 고르세요.
        </p>
      )}
    </fieldset>
  )
}
