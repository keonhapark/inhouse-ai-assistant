/**
 * 채팅 답의 마크다운 일부(문단·줄바꿈·목록·굵게·기울임·코드·제목 줄·구분선·링크)를 React 요소로 그립니다(#529).
 *
 * HTML 문자열을 만들지 않고(dangerouslySetInnerHTML 없음) 모든 글자를 React 텍스트로 넣으므로, 답에 든 HTML은
 * 글자 그대로 보입니다. 링크는 http·https이고 사용자 정보(a@b)가 없는 주소만 새 창 링크로 만들고, 실제로 가는
 * host를 옆에 보입니다. 그 밖의 주소(javascript:, data:, file: 등)는 "글(주소)" 글자로 둡니다. 답에는 사진·문서에서 읽은 신뢰할 수 없는 글이 섞일 수 있습니다(결정 0004).
 * 스트리밍 중에는 닫히지 않은 표시(**, ```)가 올 수 있어, 짝이 맞지 않으면 글자로 두거나 끝까지 코드로 봅니다.
 */
import { Fragment, type ReactNode } from 'react'

type ListEntry = { indent: number; ordered: boolean; num: number; text: string }
type ListNode = { indent: number; ordered: boolean; start: number; items: ListItem[] }
type ListItem = { text: string; children: ListNode[] }
type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'heading'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'hr' }
  | { kind: 'list'; list: ListNode }

const FENCE = /^\s*```[^`]*$/ // 여는 줄 뒤에 백틱이 또 있으면(```ls```) 한 줄 코드로 봅니다
const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/
const HR = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/
const ITEM = /^(\s*)([*+-]|\d{1,9}[.)])\s+(.*)$/

/** 제목 줄 끝의 닫는 #을 뗍니다. 정규식으로 하면 긴 공백에서 되짚기가 폭증해 손으로 자릅니다. */
function headingText(raw: string): string {
  let t = raw.trimEnd()
  let j = t.length
  while (j > 0 && t[j - 1] === '#') j--
  if (j === 0 || /\s/.test(t[j - 1])) t = t.slice(0, j).trimEnd()
  return t
}

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (FENCE.test(line)) {
      const body: string[] = []
      i++
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i++])
      i++ // 닫는 줄(없으면 끝)
      blocks.push({ kind: 'code', text: body.join('\n') })
    } else if (!line.trim()) {
      i++
    } else if (HEADING.test(line)) {
      blocks.push({ kind: 'heading', text: headingText(HEADING.exec(line)![1]) })
      i++
    } else if (HR.test(line)) {
      blocks.push({ kind: 'hr' })
      i++
    } else if (ITEM.test(line)) {
      const entries: ListEntry[] = []
      while (i < lines.length) {
        const m = ITEM.exec(lines[i])
        if (m) {
          const marker = m[2]
          const ordered = /\d/.test(marker)
          entries.push({ indent: m[1].replace(/\t/g, '    ').length, ordered, num: ordered ? parseInt(marker, 10) : 1, text: m[3] })
          i++
        } else if (lines[i].trim() && /^\s+/.test(lines[i]) && !FENCE.test(lines[i])) {
          entries[entries.length - 1].text += '\n' + lines[i].trim() // 들여 쓴 이어지는 줄
          i++
        } else if (!lines[i].trim() && i + 1 < lines.length && ITEM.test(lines[i + 1])) {
          i++ // 항목 사이 빈 줄
        } else break
      }
      for (const list of buildLists(entries)) blocks.push({ kind: 'list', list })
    } else {
      const para: string[] = []
      while (i < lines.length && lines[i].trim() && !FENCE.test(lines[i]) && !HEADING.test(lines[i]) && !HR.test(lines[i]) && !ITEM.test(lines[i])) {
        para.push(lines[i++].trim())
      }
      blocks.push({ kind: 'p', lines: para })
    }
  }
  return blocks
}

/** 들여쓰기로 하위 목록을 만듭니다. 같은 깊이에서 목록 종류(번호·기호)가 바뀌면 새 목록으로 나눕니다. */
function buildLists(entries: ListEntry[]): ListNode[] {
  const roots: ListNode[] = []
  const stack: ListNode[] = []
  for (const e of entries) {
    while (stack.length > 1 && e.indent < stack[stack.length - 1].indent) stack.pop()
    const top = stack[stack.length - 1]
    if (top && e.indent > top.indent && top.items.length > 0) {
      const child: ListNode = { indent: e.indent, ordered: e.ordered, start: e.num, items: [] }
      top.items[top.items.length - 1].children.push(child)
      stack.push(child)
    } else if (!top || top.ordered !== e.ordered) {
      const list: ListNode = { indent: e.indent, ordered: e.ordered, start: e.num, items: [] }
      if (stack.length <= 1) {
        roots.push(list)
        stack.length = 0
      } else {
        stack.pop()
        const parent = stack[stack.length - 1]
        parent.items[parent.items.length - 1].children.push(list)
      }
      stack.push(list)
    }
    stack[stack.length - 1].items.push({ text: e.text, children: [] })
  }
  return roots
}

// 코드 → 링크 → 굵게 → 기울임 순. 굵게·기울임은 표시 바로 안쪽이 공백이 아니어야 합니다(5 * 3, 2 ** 3은 글자 그대로).
// 굵게 안에는 기울임(*x*)이 올 수 있고, 닫는 ** 뒤에 *가 또 있으면 더 늘려 ***강조***를 굵게+기울임으로 봅니다.
const INLINE = /`([^`\n]+)`|\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)|\*\*(?=\S)([^\n]*?\S)\*\*(?!\*)|\*(?=[^\s*])([^*\n]*?[^\s*]|[^\s*])\*/g

/** http·https이고 사용자 정보(https://a@b)가 없는 주소만 링크로 만듭니다. */
function safeUrl(url: string): URL | null {
  try {
    const u = new URL(url)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
    if (u.username || u.password) return null
    return u
  } catch {
    return null
  }
}

function inline(text: string, key = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const k = `${key}-${n++}`
    if (m[1] !== undefined) out.push(<code key={k}>{m[1]}</code>)
    else if (m[2] !== undefined) {
      // 링크 글자는 답이 정하므로 실제로 가는 곳(host, 퓨니코드)을 옆에 늘 보입니다
      const url = safeUrl(m[3])
      out.push(
        url ? (
          <Fragment key={k}>
            <a href={url.href} target="_blank" rel="noopener noreferrer">
              {inline(m[2], k)}
              <span className="visually-hidden">(새 창)</span>
            </a>
            <span className="md__host"> ({url.host})</span>
          </Fragment>
        ) : (
          `${m[2]}(${m[3]})`
        ),
      )
    } else if (m[4] !== undefined) out.push(<strong key={k}>{inline(m[4], k)}</strong>)
    else out.push(<em key={k}>{inline(m[5], k)}</em>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function lines(text: string, key: string): ReactNode[] {
  return text.split('\n').flatMap((l, i) => (i === 0 ? inline(l, `${key}-${i}`) : [<br key={`${key}-br${i}`} />, ...inline(l, `${key}-${i}`)]))
}

function renderList(list: ListNode, key: string, tail: ReactNode): ReactNode {
  const items = list.items.map((it, i) => {
    const isLast = i === list.items.length - 1
    const kids = it.children.map((c, j) => renderList(c, `${key}-${i}-${j}`, isLast && j === it.children.length - 1 ? tail : null))
    return (
      <li key={i}>
        {lines(it.text, `${key}-${i}`)}
        {kids}
        {isLast && it.children.length === 0 && tail}
      </li>
    )
  })
  return list.ordered ? (
    <ol key={key} start={list.start === 1 ? undefined : list.start}>
      {items}
    </ol>
  ) : (
    <ul key={key}>{items}</ul>
  )
}

export function Markdown({ text, tail }: { text: string; tail?: ReactNode }) {
  const blocks = parseBlocks(text)
  if (blocks.length === 0) return <>{tail}</>
  return (
    <>
      {blocks.map((b, i) => {
        const t = i === blocks.length - 1 ? tail : null
        const key = `b${i}`
        switch (b.kind) {
          case 'p':
            return (
              <p key={key}>
                {lines(b.lines.join('\n'), key)}
                {t}
              </p>
            )
          case 'heading':
            return (
              <p key={key} className="md__heading">
                <strong>{inline(b.text, key)}</strong>
                {t}
              </p>
            )
          case 'code':
            return (
              <pre key={key}>
                <code>{b.text}</code>
                {t}
              </pre>
            )
          case 'hr':
            return (
              <Fragment key={key}>
                <hr />
                {t}
              </Fragment>
            )
          case 'list':
            return renderList(b.list, key, t)
        }
      })}
    </>
  )
}
