import { Badge, LocalBadge, RiskBadge } from '../components/Badge'
import { Button } from '../components/Button'
import '../chat/chat.css'
import './pages.css'

const TOKENS = ['bg', 'surface', 'fill', 'fill-2', 'sep', 'sep-strong', 'text', 'text-2', 'accent', 'accent-fill', 'progress', 'success', 'warning', 'danger']

/** DESIGN.md의 토큰과 기본 부품을 한 화면에 모아 라이트·다크에서 확인합니다. */
export function DesignPage() {
  return (
    <main className="page design">
      <h1>디자인 부품</h1>

      <section aria-labelledby="tokens">
        <h2 id="tokens">토큰</h2>
        <ul className="swatches">
          {TOKENS.map((t) => (
            <li key={t}>
              <span className="swatch" style={{ background: `var(--${t})` }} />
              <code>--{t}</code>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="buttons">
        <h2 id="buttons">버튼</h2>
        <div className="row">
          <Button variant="primary">실행</Button>
          <Button>취소</Button>
          <Button variant="danger">반려</Button>
          <Button variant="primary" disabled>
            실행
          </Button>
        </div>
      </section>

      <section aria-labelledby="badges">
        <h2 id="badges">배지</h2>
        <div className="row">
          <RiskBadge risk="read" />
          <RiskBadge risk="reversible_write" />
          <RiskBadge risk="irreversible" />
          <Badge tone="accent">진행</Badge>
          <Badge tone="success">승인</Badge>
          <Badge tone="danger">반려</Badge>
          <Badge>회수</Badge>
          <LocalBadge />
        </div>
      </section>

      <section aria-labelledby="cards">
        <h2 id="cards">실행 전 확인 카드</h2>
        <section className="sheet" aria-label="실행 전 확인: 회의실 예약">
          <header className="sheet__head">
            <h3 className="sheet__title">회의실 예약</h3>
          </header>
          <p className="sheet__summary">3층 소회의실을 예약합니다.</p>
          <footer className="sheet__foot">
            <span className="sheet__when">14:32까지 확인</span>
            <Button>취소</Button>
            <Button variant="primary">회의실 예약</Button>
          </footer>
        </section>
      </section>
    </main>
  )
}
