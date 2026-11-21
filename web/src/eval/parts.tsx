import type { Schemas } from '../api/client'
import { conditionName, diffText, proportionText } from './labels'

/**
 * 비율과 95% 구간을 0~100% 막대 위에 점과 선으로 보여 줍니다. 값은 옆 글자로 읽고 그림은 보조입니다(aria-hidden).
 */
/** 0~1로 묶습니다. 스키마가 범위를 막지 않아 다른 생성기가 범위 밖 값을 써도 막대 밖에 그리지 않습니다. */
const clamp = (v: number) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0)

export function Interval({ p }: { p: Schemas['proportion'] | undefined }) {
  if (!p || p.N === 0) return <span className="muted">-</span>
  const rate = clamp(p.rate ?? p.n / p.N)
  return (
    <span className="ci">
      {p.low != null && p.high != null && (
        <span className="ci__track" aria-hidden="true">
          <span className="ci__range" style={{ left: `${clamp(p.low) * 100}%`, width: `${Math.max(0, clamp(p.high) - clamp(p.low)) * 100}%` }} />
          <span className="ci__dot" style={{ left: `${rate * 100}%` }} />
        </span>
      )}
      <span className="ci__text">{proportionText(p)}</span>
    </span>
  )
}

/** 짝 차이(-100%p~+100%p)와 구간. 가운데 세로선이 0입니다. */
export function Diff({ d }: { d: Schemas['pairedDiff'] | undefined }) {
  if (!d || d.pairs === 0) return <span className="muted">-</span>
  const x = (v: number) => `${clamp((v + 1) / 2) * 100}%`
  return (
    <span className="ci">
      <span className="ci__track ci__track--diff" aria-hidden="true">
        <span className="ci__zero" />
        <span className="ci__range" style={{ left: x(d.low), width: `${Math.max(0, clamp((d.high + 1) / 2) - clamp((d.low + 1) / 2)) * 100}%` }} />
        <span className="ci__dot" style={{ left: x(d.diff) }} />
      </span>
      <span className="ci__text">{diffText(d)}</span>
    </span>
  )
}

/** 조건을 열로 두는 표의 머리. */
export function ConditionHead({ first, conditions }: { first: string; conditions: string[] }) {
  return (
    <thead>
      <tr>
        <th scope="col">{first}</th>
        {conditions.map((c) => (
          <th scope="col" key={c}>
            {conditionName(c)}
          </th>
        ))}
      </tr>
    </thead>
  )
}

/** 넓은 표를 좁은 화면에서 가로로 넘겨 봅니다. 키보드로도 넘길 수 있게 포커스를 받습니다. */
export function Scroll({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  )
}
