import { useEffect, useState } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'
import { Toolbar } from '../shell/Toolbar'
import { DelegationPanel } from './DelegationPanel'
import './inbox.css'

/** 대결 설정 화면(ux/research/ia.md 2절). 결재 화면에서 떼어 내 탐색 막대의 업무 묶음에 둡니다 */
export function DelegationsPage() {
  const [forms, setForms] = useState<Schemas['ApprovalForm'][]>([])
  const [formsError, setFormsError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    api.GET('/approval-forms').then(
      ({ data, error }) => {
        if (!alive) return
        if (data) setForms(data.items)
        else setFormsError(problemTitle(error, '양식 목록을 불러오지 못했습니다.'))
      },
      () => alive && setFormsError('양식 목록을 불러오지 못했습니다.'),
    )
    return () => {
      alive = false
    }
  }, [])
  return (
    <main className="delegations" aria-labelledby="delegations-title">
      <Toolbar title="대결 설정" titleId="delegations-title" />
      <div className="delegations__body">
        <DelegationPanel forms={forms} formsError={formsError} />
      </div>
    </main>
  )
}
