// 시안 HTML 조각입니다. 세 방향이 같은 데이터와 같은 구조(ia.md 2절)를 쓰고,
// 방향마다 다른 것은 토큰(tokens.css), 배치 변형(layout), 방향 CSS(direction.css)입니다.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import * as D from './data.mjs'

const require = createRequire(import.meta.url)
const ICONS = join(dirname(require.resolve('lucide-static/package.json')), 'icons')

/** Lucide 아이콘(ISC)을 인라인 SVG로 넣습니다. */
export function icon(name, cls = '') {
  const svg = readFileSync(join(ICONS, `${name}.svg`), 'utf8')
    .replace(/<!--[\s\S]*?-->/, '')
    .replace(/class="[^"]*"/, `class="i ${cls}" aria-hidden="true"`)
    .replace(/\s*\n\s*/g, ' ')
    .trim()
  return svg
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export const badge = (tone, text, ic) => `<span class="badge badge--${tone}">${ic ? icon(ic) : '<i class="dot"></i>'}${esc(text)}</span>`

/** 우리가 그린 영수증입니다(인라인 SVG라 페이지 서체를 씁니다). */
export function receiptSvg(w = 200) {
  const r = D.receipt
  const h = Math.round(w * 1.42)
  const rows = r.items
    .map(([n, q, p], i) => {
      const y = 118 + i * 16
      return `<text x="14" y="${y}">${esc(n)}</text><text x="128" y="${y}" text-anchor="end">${q}</text><text x="186" y="${y}" text-anchor="end">${p}</text>`
    })
    .join('')
  return `<svg class="receipt" viewBox="0 0 200 284" width="${w}" height="${h}" role="img" aria-label="영수증 사진: ${esc(r.store)}, 합계 ${r.total}원">
  <defs><filter id="paper"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" result="n"/><feColorMatrix in="n" type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.05"/></feComponentTransfer><feBlend in="SourceGraphic" mode="multiply"/></filter></defs>
  <g transform="rotate(-1.2 100 142)">
    <path d="M4 2h192v272l-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6-8-6-8 6z" fill="#FBFAF7" stroke="#D9D6CF" stroke-width=".8" filter="url(#paper)"/>
    <g font-size="9.5" fill="#33302B" font-family="inherit">
      <text x="100" y="24" text-anchor="middle" font-size="12" font-weight="700">${esc(r.store)}</text>
      <text x="100" y="40" text-anchor="middle" fill="#6B665D">사업자 ${r.bizNo}</text>
      <text x="100" y="53" text-anchor="middle" fill="#6B665D">${esc(r.address)}</text>
      <text x="14" y="78">${r.at}</text>
      <line x1="14" x2="186" y1="90" y2="90" stroke="#B9B4AA" stroke-dasharray="2 2"/>
      <text x="14" y="104" fill="#6B665D">품목</text><text x="128" y="104" text-anchor="end" fill="#6B665D">수량</text><text x="186" y="104" text-anchor="end" fill="#6B665D">금액</text>
      ${rows}
      <line x1="14" x2="186" y1="160" y2="160" stroke="#B9B4AA" stroke-dasharray="2 2"/>
      <text x="14" y="180" font-size="11.5" font-weight="700">합계</text><text x="186" y="180" text-anchor="end" font-size="11.5" font-weight="700">${r.total}원</text>
      <text x="14" y="198" fill="#6B665D">${r.card}</text>
      <text x="14" y="212" fill="#6B665D">승인 12:38 일시불</text>
      <g fill="#33302B">${Array.from({ length: 34 }, (_, i) => `<rect x="${22 + i * 4.6}" y="230" width="${i % 3 ? 1.6 : 2.8}" height="22"/>`).join('')}</g>
    </g>
  </g>
</svg>`
}

function sidebar(dir, active, user, extra = '') {
  const groups = D.nav
    .map(
      (g) => `<div class="nav__group"><div class="nav__label">${g.group}</div>${g.items
        .map(
          (it) =>
            `<a class="nav__item${it.key === active ? ' is-active' : ''}" href="#"${it.key === active ? ' aria-current="page"' : ''}>${icon(it.icon)}<span>${it.label}</span>${it.count ? `<b class="nav__count" aria-label="받은 결재 ${it.count}건">${it.count}</b>` : ''}</a>`,
        )
        .join('')}</div>`,
    )
    .join('')
  return `<aside class="sidebar" aria-label="메뉴">
    <div class="brand"><span class="brand__mark" aria-hidden="true">${icon('sparkles')}</span><span class="brand__name">${D.company.name}</span><span class="brand__product">${D.company.product}</span></div>
    <button class="cmdk" type="button">${icon('search')}<span>찾기, 이동</span><kbd>Ctrl K</kbd></button>
    <nav class="nav">${groups}</nav>
    ${extra}
    <div class="me"><span class="avatar">${user.initials}</span><span class="me__text"><b>${user.name}</b><span>${user.team} ${user.title}</span></span>${icon('chevrons-up-down', 'me__more')}</div>
  </aside>`
}

function page({ dir, title, active, user, body, sidebarExtra = '', screen }) {
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} · ${DIRECTIONS[dir].name} 시안</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="../src/base.css">
<link rel="stylesheet" href="direction.css">
</head>
<body class="dir-${dir} screen-${screen}">
<div class="app">
${sidebar(dir, active, user, sidebarExtra)}
${body}
</div>
</body>
</html>
`
}

export const DIRECTIONS = {
  mixed: { name: '섞음', note: 'Linear식 셸 + Geist식 토큰 + Ramp식 경비·결재' },
  ops: { name: '운영 도구형', note: 'Linear + Geist + Carbon, 표 중심·밀도 높음' },
  assistant: { name: '대화 비서형', note: 'Fluent 2 + Ramp + Geist, 대화가 주인공·오른쪽 패널' },
}

// ───────────── AI 비서 ─────────────

function convList(compact = false) {
  return `<section class="convs" aria-label="대화 목록">
    <div class="convs__head"><h2>대화</h2><button class="btn btn--ghost btn--icon" type="button" aria-label="새 대화">${icon('plus')}</button></div>
    <ul>${D.conversations
      .map(
        (c) => `<li class="conv${c.active ? ' is-active' : ''}"><a href="#"${c.active ? ' aria-current="true"' : ''}>
        <span class="conv__title">${c.title}</span>
        <span class="conv__meta"><span>${c.agent}</span>${c.status ? badge(c.tone, c.status) : ''}<time>${c.when}</time></span>
      </a></li>`,
      )
      .join('')}</ul>
  </section>`
}

function fieldsDl(fields, cls = '') {
  return `<dl class="kv ${cls}">${fields.map(([k, v]) => `<div class="kv__row${k === '금액' ? ' kv__row--amount' : ''}"><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`
}

function approvalLine(line, cls = '') {
  return `<ol class="line ${cls}" aria-label="결재선">${line
    .map((s) => `<li class="line__step line__step--${s.state}"><span class="line__dot" aria-hidden="true">${s.state === 'done' ? icon('check') : s.state === 'current' ? icon('clock') : ''}</span><span class="line__who"><b>${s.name}</b><span>${s.role}${s.at ? ` ${s.at}` : ''}</span></span></li>`)
    .join('')}</ol>`
}

function previewCard(layout) {
  const e = D.expense
  const policy = `<p class="policy policy--ok">${icon('shield-check')}<span><b>${e.policy.text}</b> ${e.policy.detail}</span></p>`
  const head = `<header class="preview__head">
      <span class="preview__agent">${icon('receipt')}재무</span>
      <h3>${e.action}</h3>
      <span class="preview__badges">${badge('attention', '사진에서 읽은 값', 'image')}${badge('neutral', '되돌릴 수 있음')}</span>
    </header>`
  const attention = `<p class="caption">영수증과 값이 맞는지 확인한 뒤 올려 주세요. 틀린 값은 취소하고 고칠 값을 말하면 됩니다.</p>`
  const foot = `<footer class="preview__foot">
      <span class="preview__expire">${icon('clock')}${e.expiresIn}</span>
      <button class="btn btn--secondary" type="button">취소</button>
      <button class="btn btn--primary" type="button">${e.action}</button>
    </footer>`
  const receiptBox = (w) => `<figure class="preview__receipt">${receiptSvg(w)}<figcaption><button class="btn btn--ghost btn--sm" type="button">${icon('zoom-in')}크게 보기</button></figcaption></figure>`
  const lineBox = `<div class="preview__line"><h4>결재선</h4>${approvalLine(e.line, 'line--inline')}</div>`
  if (layout === 'panel') {
    return `<article class="preview preview--panel" aria-label="실행 미리보기: ${e.action}">
      ${head}
      <div class="preview__compare">${receiptBox(176)}${fieldsDl(e.fields)}</div>
      ${policy}${attention}${lineBox}${foot}
    </article>`
  }
  if (layout === 'dense') {
    return `<article class="preview preview--dense" aria-label="실행 미리보기: ${e.action}">
      ${head}
      <div class="preview__compare">${receiptBox(132)}<div class="preview__right">${fieldsDl(e.fields, 'kv--table')}${policy}${attention}${lineBox}</div></div>
      ${foot}
    </article>`
  }
  return `<article class="preview" aria-label="실행 미리보기: ${e.action}">
    ${head}
    <div class="preview__compare">${receiptBox(124)}<div class="preview__right">${fieldsDl(e.fields)}${policy}${attention}</div></div>
    ${lineBox}${foot}
  </article>`
}

function thread(layout) {
  const me = `<div class="msg msg--me"><div class="bubble">${D.chat.userText}<span class="attach">${icon('paperclip')}영수증 사진 1장</span></div></div>`
  const route = `<div class="route">${icon('receipt')}<b>재무</b><span>이 대화를 맡았습니다</span>${badge('local', '로컬에서 처리', 'lock')}</div>`
  const answer = `<div class="msg msg--agent"><p>${D.chat.answer}</p></div>`
  const pointer =
    layout === 'panel'
      ? `<div class="msg msg--agent"><button class="handoff" type="button">${icon('receipt')}<span class="handoff__text"><b>경비 정산 올리기</b><span>가온식당 성수점, 서도윤 팀장 결재</span></span><span class="handoff__amount">42,000원</span>${badge('attention', '확인 필요')}</button></div>`
      : previewCard(layout)
  return `${me}${route}${answer}${pointer}`
}

function composer() {
  return `<form class="composer" onsubmit="return false">
    <label class="sr-only" for="msg">메시지</label>
    <textarea id="msg" rows="2" placeholder="무엇을 할까요? 예: 다음 주 화요일 오후에 6명 들어갈 회의실 잡아 줘"></textarea>
    <div class="composer__bar">
      <button class="btn btn--ghost btn--sm" type="button">${icon('paperclip')}사진 첨부</button>
      <button class="chip" type="button">${icon('bot')}자동 선택${icon('chevron-down')}</button>
      <span class="composer__hint">Enter로 보내고 Shift+Enter로 줄을 바꿉니다</span>
      <button class="btn btn--primary btn--icon" type="submit" aria-label="보내기" disabled>${icon('send')}</button>
    </div>
  </form>`
}

export function chatScreen(dir) {
  const layout = { mixed: 'inline', ops: 'dense', assistant: 'panel' }[dir]
  const topbar = `<header class="topbar"><h1>${D.conversations[0].title}</h1><span class="topbar__sub">재무 에이전트</span><span class="topbar__spacer"></span><button class="btn btn--ghost btn--icon" type="button" aria-label="알림">${icon('bell')}<i class="ping"></i></button></header>`
  if (layout === 'panel') {
    const recents = `<div class="recents"><div class="nav__label">최근 대화</div>${D.conversations
      .slice(0, 4)
      .map((c) => `<a class="recent${c.active ? ' is-active' : ''}" href="#">${icon('message-square')}<span>${c.title}</span></a>`)
      .join('')}</div>`
    // 확인할 일 패널이 탐색 막대와 같은 높이에서 시작하도록 머리글은 대화 열 안에만 둡니다.
    const body = `<main class="main main--chat-panel">
      <div class="workspace">
        <section class="chat" aria-label="대화">${topbar}<div class="chat__scroll"><div class="chat__col">${thread('panel')}</div></div><div class="chat__col">${composer()}</div></section>
        <aside class="side" aria-label="확인할 일"><div class="side__head"><h2>확인할 일</h2><span class="side__count">1</span></div>${previewCard('panel')}</aside>
      </div>
    </main>`
    return page({ dir, title: 'AI 비서', active: 'chat', user: D.employee, body, sidebarExtra: recents, screen: 'chat' })
  }
  const body = `<main class="main main--chat">
    ${convList(layout === 'dense')}
    <section class="chat" aria-label="대화">
      ${topbar}
      <div class="chat__scroll"><div class="chat__col">${thread(layout)}</div></div>
      <div class="chat__col">${composer()}</div>
    </section>
  </main>`
  return page({ dir, title: 'AI 비서', active: 'chat', user: D.employee, body, screen: 'chat' })
}

// ───────────── 결재 ─────────────

function tabs() {
  return `<div class="tabs" role="tablist" aria-label="결재함">${D.approvalTabs
    .map((t) => `<button class="tab${t.active ? ' is-active' : ''}" role="tab" aria-selected="${!!t.active}" type="button">${t.label}${t.count ? `<span class="tab__count">${t.count}</span>` : ''}</button>`)
    .join('')}</div>`
}

// 표 열 정의. 방향마다 목록 폭이 달라 보이는 열을 고릅니다. 두 표(받은 결재, 오늘 처리한 결재)는 같은 열 폭을 써서 줄이 맞습니다.
const COLS = {
  form: { head: '양식', cls: 'c-form', td: (a) => `<span class="form">${icon(a.icon)}${a.form}</span>` },
  title: { head: '제목', td: (a) => `<a href="#" class="row-link">${a.title}</a>${a.tag ? ` ${badge(a.tag === '2단계' ? 'neutral' : 'attention', a.tag)}` : ''}` },
  titleIcon: { head: '제목', td: (a) => `<span class="form form--lead">${icon(a.icon)}<a href="#" class="row-link">${a.title}</a></span>${a.tag ? ` ${badge(a.tag === '2단계' ? 'neutral' : 'attention', a.tag)}` : ''}` },
  who: { head: '요청자', cls: 'c-who', td: (a) => a.requester },
  amount: { head: '금액', cls: 'c-amt', num: true, td: (a) => a.amount },
  received: { head: '받은 때', cls: 'c-at', td: (a) => a.received },
  wait: { head: '기다림', cls: 'c-st', td: (a) => a.wait },
  doneAt: { head: '처리한 때', cls: 'c-at', td: (a) => `오늘 ${a.at}` },
  result: { head: '결과', cls: 'c-st', td: (a) => badge(a.result[0], a.result[1]) },
}
const TABLES = {
  ops: { inbox: ['form', 'title', 'who', 'amount', 'received', 'wait'], done: ['form', 'title', 'who', 'amount', 'doneAt', 'result'] },
  mixed: { inbox: ['form', 'title', 'who', 'amount', 'wait'], done: ['form', 'title', 'who', 'amount', 'result'] },
  assistant: { inbox: ['titleIcon', 'who', 'amount'], done: ['titleIcon', 'who', 'result'] },
}

function table(cols, rows, { muted = false, selectable = false } = {}) {
  const spec = cols.map((k) => COLS[k])
  return `<table class="table${muted ? ' table--muted' : ''}">
    <colgroup>${spec.map((c) => `<col${c.cls ? ` class="${c.cls}"` : ''}>`).join('')}</colgroup>
    <thead><tr>${spec.map((c) => `<th${c.num ? ' class="num"' : ''}>${c.head}</th>`).join('')}</tr></thead>
    <tbody>${rows
      .map((a) => `<tr${selectable && a.selected ? ' class="is-selected" aria-selected="true"' : ''}>${spec.map((c) => `<td${c.num ? ' class="num"' : ''}>${c.td(a)}</td>`).join('')}</tr>`)
      .join('')}</tbody>
  </table>`
}

function docDetail(layout) {
  const d = D.approvalDoc
  const receipt = `<figure class="doc__receipt">${receiptSvg(layout === 'wide' ? 190 : 150)}<figcaption><button class="btn btn--ghost btn--sm" type="button">${icon('zoom-in')}크게 보기</button></figcaption></figure>`
  return `<article class="doc doc--${layout}" aria-label="결재 문서: ${d.title}">
    <header class="doc__head">
      <div class="doc__titles"><span class="doc__form">${icon('receipt')}${d.form} <span class="doc__no">${d.docNo}</span></span><h2>${d.title}</h2></div>
      ${badge('progress', '진행 중')}
    </header>
    <div class="doc__who"><span class="avatar avatar--sm">지현</span><span><b>${d.requester.name}</b> ${d.requester.team}</span><span class="doc__when">${d.submitted} 올림</span></div>
    <div class="doc__body">
      <div class="doc__values">${fieldsDl(d.fields)}<p class="policy policy--ok">${icon('shield-check')}<span><b>${d.policy.text}</b> ${d.policy.detail}</span></p><p class="source">${icon('sparkles')}${d.source}</p></div>
      ${receipt}
    </div>
    <section class="doc__section"><h3>결재선</h3>${approvalLine(d.line, layout === 'wide' ? 'line--vertical' : 'line--inline')}</section>
    <footer class="doc__foot">
      <label class="field field--inline"><span class="sr-only">의견</span><textarea rows="1" placeholder="의견(반려할 때는 이유를 꼭 적어 주세요)"></textarea></label>
      <div class="doc__actions">
        <button class="btn btn--secondary btn--danger-text" type="button">반려</button>
        <span class="doc__actions-spacer"></span>
        <div class="popover" role="dialog" aria-label="승인 확인">
          <p><b>42,000원 경비 정산을 승인할까요?</b>${d.confirm}</p>
          <div class="popover__actions"><button class="btn btn--secondary btn--sm" type="button">취소</button><button class="btn btn--primary btn--sm" type="button">${icon('check')}승인 확정</button></div>
        </div>
        <button class="btn btn--primary is-pressed" type="button" aria-expanded="true">${icon('check')}승인</button>
      </div>
    </footer>
  </article>`
}

export function approvalsScreen(dir) {
  const topbar = `<header class="topbar"><h1>결재</h1><span class="topbar__sub">받은 결재 3건, 대결로 받은 결재 1건</span><span class="topbar__spacer"></span><button class="btn btn--ghost btn--icon" type="button" aria-label="알림">${icon('bell')}<i class="ping"></i></button></header>`
  const t = TABLES[dir]
  const list = `${table(t.inbox, D.approvals, { selectable: true })}<h2 class="done-head">오늘 처리한 결재 ${D.doneToday.length}건</h2>${table(t.done, D.doneToday, { muted: true })}`
  const layout = { mixed: 'split', ops: 'narrow', assistant: 'wide' }[dir]
  const inList = dir === 'assistant'
  const body = `<main class="main main--approvals">
    ${inList ? '' : topbar}
    <div class="approvals approvals--${layout}">
      <section class="approvals__list" aria-label="결재 목록">${inList ? topbar : ''}${tabs()}<div class="approvals__filter"><button class="chip" type="button">${icon('filter')}양식 전체${icon('chevron-down')}</button><span class="approvals__note">${icon('arrow-right-left')}윤서진 팀장의 결재를 11월 24일까지 대신 맡고 있습니다</span></div>${list}</section>
      ${docDetail(layout)}
    </div>
  </main>`
  return page({ dir, title: '결재', active: 'approvals', user: D.approver, body, screen: 'approvals' })
}
