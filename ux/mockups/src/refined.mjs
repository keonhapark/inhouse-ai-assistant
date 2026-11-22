// 다듬은 판(#571) 화면입니다. 데이터는 세 방향 시안과 같고, 문구는 ux/copy-guide.md를 따릅니다.
import * as D from './data.mjs'
import { icon, receiptSvg } from './templates.mjs'

const status = (tone, text) => `<span class="status status--${tone}">${text}</span>`

function sidebar(active, user) {
  const groups = D.nav
    .map(
      (g) => `<div><div class="nav__label">${g.group}</div>${g.items
        .map(
          (it) =>
            `<a class="nav__item${it.key === active ? ' is-active' : ''}" href="#"${it.key === active ? ' aria-current="page"' : ''}>${icon(it.icon)}<span>${it.label}</span>${it.count ? `<span class="nav__count" aria-label="결재 대기 ${it.count}건">${it.count}</span>` : ''}</a>`,
        )
        .join('')}</div>`,
    )
    .join('')
  return `<aside class="sidebar" aria-label="메뉴">
    <div class="brand"><span class="brand__mark" aria-hidden="true">${icon('sparkles')}</span><b>${D.company.name}</b></div>
    <button class="search" type="button">${icon('search')}<span>찾기·이동</span><kbd>Ctrl K</kbd></button>
    <nav class="nav">${groups}</nav>
    <div class="me"><span class="avatar">${user.initials}</span><span class="me__text"><b>${user.name}</b><span>${user.team} ${user.title}</span></span></div>
  </aside>`
}

function page({ title, active, user, body, screen }) {
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} · 다듬은 판 시안</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="refined.css">
</head>
<body class="screen-${screen}">
<div class="app">
${sidebar(active, user)}
${body}
</div>
</body>
</html>
`
}

const toolbar = (title, sub, middle = '') =>
  `<header class="toolbar"><h1>${title}</h1>${sub ? `<span class="toolbar__sub">${sub}</span>` : ''}<span class="toolbar__spacer"></span>${middle}${middle ? '<span class="toolbar__spacer"></span>' : ''}<button class="icon-btn" type="button" aria-label="알림, 새 알림 있음">${icon('bell')}<i class="ping"></i></button></header>`

// ───────────── AI 비서 ─────────────

const CONVS = [
  { title: '팀 점심 식대 정산', sub: ['재무 담당 AI', status('orange', '확인 필요')], when: '12:41', active: true },
  { title: '3층 소회의실 예약', sub: ['총무 담당 AI', status('green', '예약 완료')], when: '어제' },
  { title: '11월 24일 반차 회수', sub: ['인사 담당 AI', status('gray', '회수')], when: '11월 18일' },
  { title: '창원 출장 숙박비 한도', sub: ['재무 담당 AI'], when: '11월 17일' },
  { title: '올해 남은 연차', sub: ['인사 담당 AI'], when: '11월 13일' },
]

const FIELDS = [
  ['가맹점', '가온식당 성수점'],
  ['사용일', '2026년 11월 19일 (목)'],
  ['용도', '식대, 팀 점심 4명'],
  ['사업자번호', '123-45-67890'],
]
const fieldRows = (rows) => rows.map(([k, v]) => `<li class="row"><span class="row__label">${k}</span><span class="row__value">${v}</span></li>`).join('')
const amount = (cls) => `<div class="${cls}"><b>42,000원</b><span>1인 10,500원 / 한도 15,000원 ${icon('circle-check', 'ok')}식대 한도 안</span></div>`

function expenseSheet() {
  return `<article class="sheet" aria-label="실행 전 확인: 경비 정산 상신">
    <header class="sheet__head">
      <h3 class="sheet__title">경비 정산 상신</h3>
      <span class="tag">${icon('image')}사진에서 읽은 값</span>
    </header>
    ${amount('sheet__amount')}
    <div class="sheet__body">
      <div class="receipt-wrap">${receiptSvg(124)}<button class="btn btn--link" type="button">크게 보기</button></div>
      <ul class="group rows">${fieldRows(FIELDS)}</ul>
    </div>
    <p class="sheet__line">${icon('users')}<span>결재선</span><b>서도윤 팀장</b><span>결재 전 회수 가능</span></p>
    <footer class="sheet__foot">
      <span class="when">영수증과 맞는지 확인해 주세요. 12:50까지</span>
      <button class="btn btn--plain" type="button">취소</button>
      <button class="btn btn--primary" type="button">경비 정산 상신</button>
    </footer>
  </article>`
}

export function refinedChat() {
  const list = CONVS.map(
    (c) => `<li class="conv${c.active ? ' is-active' : ''}"><a href="#"${c.active ? ' aria-current="true"' : ''}>
      <span class="conv__title">${c.title}</span><time>${c.when}</time>
      <span class="conv__sub">${c.sub.join('')}</span></a></li>`,
  ).join('')
  const body = `<main class="main">
    <div class="chat-layout">
      <section class="convs" aria-label="대화 목록">
        <div class="convs__head"><h2>대화</h2><button class="icon-btn" type="button" aria-label="새 대화">${icon('square-pen')}</button></div>
        <ul>${list}</ul>
      </section>
      <section class="chat" aria-label="대화">
        ${toolbar('팀 점심 식대 정산', '재무 담당 AI')}
        <div class="chat__scroll"><div class="col">
          <div class="me-msg">어제 팀 점심 영수증이야. 식대로 경비 정산 올려 줘<small>${icon('paperclip')}영수증 사진 1장</small></div>
          <div class="agent-msg">
            <div class="agent-msg__who"><b>재무 담당 AI</b>${status('purple', '사내 처리')}</div>
            <p>영수증에서 가맹점, 사용일, 금액을 읽었습니다.</p>
          </div>
          ${expenseSheet()}
        </div></div>
        <div class="col">
          <form class="composer" onsubmit="return false">
            <label class="sr-only" for="msg">메시지</label>
            <textarea id="msg" rows="2" placeholder="예: 다음 주 화요일 오후에 6명 들어갈 회의실 잡아 줘"></textarea>
            <div class="composer__bar">
              <button class="chip" type="button">${icon('paperclip')}사진 첨부</button>
              <button class="chip" type="button">${icon('sparkles')}자동 선택${icon('chevron-down')}</button>
              <span class="spacer"></span>
              <button class="send" type="submit" aria-label="보내기" disabled>${icon('arrow-up')}</button>
            </div>
          </form>
        </div>
      </section>
    </div>
  </main>`
  return page({ title: 'AI 비서', active: 'chat', user: D.employee, body, screen: 'chat' })
}

// ───────────── 결재 ─────────────

const INBOX = [
  { icon: 'receipt', title: '팀 점심 식대', sub: '경비 정산 · 오지현', amt: '42,000원', note: '18분 전', tag: true, selected: true },
  { icon: 'calendar-clock', title: '연차 11월 26일~27일', sub: '휴가 신청 · 김태윤', amt: '2일', note: '어제' },
  { icon: 'package', title: '오일 실 35×52×8 200개', sub: '구매 요청 · 박세영 · 결재선 1/2', amt: '380,000원', note: '11월 18일' },
]
const DONE = [
  { icon: 'calendar-clock', title: '오후 반차 11월 23일', sub: '휴가 신청 · 김태윤', st: ['green', '승인'], at: '09:12' },
  { icon: 'receipt', title: '창원 출장 교통비', sub: '경비 정산 · 박세영 · 86,400원', st: ['green', '승인'], at: '08:57' },
  { icon: 'package', title: '버니어 캘리퍼스 2개', sub: '구매 요청 · 이준서 · 214,000원', st: ['red', '반려'], at: '08:40' },
]
const docRow = (a, right) => `<li class="doc-row${a.selected ? ' is-selected' : ''}"><a href="#"${a.selected ? ' aria-current="true"' : ''}>
      <span class="ico">${icon(a.icon)}</span>
      <span><span class="doc-row__title">${a.title}${a.tag ? `<span class="tag">${icon('image')}사진에서 읽은 값</span>` : ''}</span><span class="doc-row__sub">${a.sub}</span></span>
      <span class="doc-row__amt">${right}</span></a></li>`

export function refinedApprovals() {
  const seg = `<div class="seg" role="tablist" aria-label="결재함">
    <button class="is-on" role="tab" aria-selected="true" type="button">결재 대기 <span class="n">3</span></button>
    <button role="tab" aria-selected="false" type="button">대결 대기 <span class="n">1</span></button>
    <button role="tab" aria-selected="false" type="button">결재 완료</button>
    <button role="tab" aria-selected="false" type="button">기안함</button>
  </div>`
  const inbox = INBOX.map((a) => docRow(a, `${a.amt}<small>${a.note}</small>`)).join('')
  const done = DONE.map((a) => docRow(a, `${status(a.st[0], a.st[1])}<small>오늘 ${a.at}</small>`)).join('')
  const rows = [...FIELDS, ['결제 수단', '법인카드 ****-1460'], ['참석자', '오지현 외 3명'], ['계정과목', '복리후생비(식대)']]
  const body = `<main class="main">
    ${toolbar('결재', '', seg)}
    <div class="approvals">
      <section class="list-pane" aria-label="결재 목록">
        <p class="pane-note">${icon('arrow-right-left')}11월 24일까지 윤서진 팀장의 대결자입니다. 대결 대기 1건</p>
        <ul class="group rows">${inbox}</ul>
        <div><h2 class="group__head"><span>오늘 결재 완료</span><span>${DONE.length}건</span></h2><ul class="group rows rows--muted">${done}</ul></div>
      </section>
      <article class="detail" aria-label="결재 문서: 팀 점심 식대">
        <div class="detail__scroll">
          <header>
            <p class="detail__kicker"><span>경비 정산</span><span class="tnum">EXP-0107</span>${status('blue', '결재 대기')}</p>
            <h2>팀 점심 식대</h2>
            <div class="detail__who"><span class="avatar">지현</span><b>오지현</b><span>생산관리팀, 2026년 11월 20일 12:44 상신</span></div>
            <ol class="timeline" aria-label="결재선">
              <li class="done"><span class="dot">${icon('check')}</span><b>오지현</b><small>기안</small></li>
              <li class="now"><span class="dot">${icon('clock')}</span><b>서도윤 팀장</b><small>결재 대기</small></li>
            </ol>
          </header>
          ${amount('amount-hero')}
          <div class="detail__grid">
            <div>
              <ul class="group rows">${fieldRows(rows)}</ul>
              <p class="note">${icon('sparkles')}<span>AI 비서가 사진에서 읽고 기안자가 확인했습니다.</span></p>
            </div>
            <div class="receipt-wrap">${receiptSvg(120)}<button class="btn btn--link" type="button">크게 보기</button></div>
          </div>
        </div>
        <footer class="detail__foot">
          <div class="detail__opinion">
            <label class="sr-only" for="opinion">의견</label>
            <textarea id="opinion" rows="1" placeholder="의견"></textarea>
            <small>반려할 때는 반려 사유를 적어 주세요</small>
          </div>
          <button class="btn btn--danger" type="button">반려</button>
          <button class="btn btn--primary is-pressed" type="button" aria-expanded="true">승인</button>
        </footer>
        <div class="popover" role="dialog" aria-labelledby="pop-t">
          <div><h3 id="pop-t">42,000원 경비 정산을 승인할까요?</h3><p>승인하면 결재가 끝나고, 승인은 취소할 수 없습니다.</p></div>
          <div class="popover__actions"><button class="btn btn--plain btn--sm" type="button">취소</button><button class="btn btn--primary btn--sm" type="button">승인</button></div>
        </div>
      </article>
    </div>
  </main>`
  return page({ title: '결재', active: 'approvals', user: D.approver, body, screen: 'approvals' })
}
