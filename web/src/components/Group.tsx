import type { ReactNode } from 'react'

type Props = { id: string; title: ReactNode; /** 오른쪽 건수("3명"). 제목 이름에 섞이지 않게 제목 밖에 둡니다 */ n?: ReactNode; level?: 2 | 3 }

/** 묶음 목록의 머리(ux/design-system.md 3.4): 왼쪽 제목, 오른쪽 건수 */
export function GroupHead({ id, title, n, level = 3 }: Props) {
  const H = level === 2 ? 'h2' : 'h3'
  return (
    <div className="group__head">
      <H id={id} className="group__h">
        {title}
      </H>
      {n != null && <span className="group__n">{n}</span>}
    </div>
  )
}
