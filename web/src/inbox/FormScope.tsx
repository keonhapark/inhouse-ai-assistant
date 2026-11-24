import { useId, useState } from 'react'
import type { Schemas } from '../api/client'

const ALL = '*'

/**
 * 대결 범위 양식(DelegationScope.formTypes). "고른 양식"이 기본이고, "모든 양식"(["*"])은 따로 골라야 합니다(ia.md F4, design-system 3.5).
 * 모든 양식은 대결자가 어떤 결재든 대신 하게 되므로, 확인 시트에서 한 번 더 경고합니다.
 */
type Props = {
  value: string[]
  /** GET /approval-forms 결과. 불러오지 못했으면 error에 이유 */
  forms: Schemas['ApprovalForm'][]
  error: string | null
  onChange(v: string[]): void
}

export function FormScope({ value, forms, error, onChange }: Props) {
  const helpId = useId()
  const all = value.includes(ALL)
  // 양식 목록을 못 받으면 고를 양식이 없어 모든 양식만 고를 수 있습니다
  const canPick = forms.length > 0
  // "모든 양식"으로 갔다가 돌아오면 골라 두었던 양식을 되살립니다(라디오를 화살표로 지나가기만 해도 바뀌므로)
  const [picked, setPicked] = useState<string[]>([])
  function toggle(id: string, on: boolean) {
    onChange(on ? [...value, id] : value.filter((v) => v !== id))
  }
  function chooseAll() {
    if (!all) setPicked(value)
    onChange([ALL])
  }

  return (
    <fieldset className="picker">
      <legend>양식 범위</legend>
      <label className="picker__option">
        <input type="radio" name="form-scope" checked={!all} disabled={!canPick} onChange={() => onChange(picked)} />
        고른 양식만
      </label>
      {!all && canPick && (
        <div className="picker__forms" role="group" aria-label="대신 결재할 양식" aria-describedby={value.length === 0 ? helpId : undefined}>
          {forms.map((f) => (
            <label key={f.id} className="picker__option">
              <input type="checkbox" checked={value.includes(f.id)} onChange={(e) => toggle(f.id, e.target.checked)} />
              {f.name}
            </label>
          ))}
        </div>
      )}
      <label className="picker__option">
        <input type="radio" name="form-scope" checked={all} onChange={chooseAll} />
        모든 양식
      </label>
      {error && (
        <p role="alert" className="alert">
          {error} 모든 양식만 고를 수 있습니다.
        </p>
      )}
      {!all && canPick && value.length === 0 && (
        <p id={helpId} className="field-help">
          대신 결재할 양식을 하나 이상 고르세요.
        </p>
      )}
    </fieldset>
  )
}
