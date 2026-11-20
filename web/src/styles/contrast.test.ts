import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const tokensCss = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8')

// DESIGN.md 원칙: 대비는 WCAG AA(본문 4.5:1, 그 밖의 UI 요소 3:1)를 지킵니다.

function block(selector: string): string {
  const start = tokensCss.indexOf(selector)
  if (start < 0) throw new Error(`${selector} 블록이 없습니다`)
  const open = tokensCss.indexOf('{', start)
  return tokensCss.slice(open + 1, tokensCss.indexOf('}', open))
}

function vars(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/--([a-z-]+):\s*(#[0-9a-f]{6})/gi)) out[m[1]] = m[2]
  return out
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const light = vars(block(':root {'))
const dark = vars(block("[data-theme='dark']"))

describe.each([
  ['라이트', light],
  ['다크', dark],
])('%s 토큰 대비', (_name, t) => {
  it.each([
    ['text', 'bg'],
    ['text', 'surface'],
    ['text-muted', 'surface'],
    ['text-muted', 'bg'],
    ['accent', 'surface'],
    ['on-fill', 'accent'],
    ['on-fill', 'danger'],
  ])('글자 %s / 바탕 %s는 4.5:1 이상입니다', (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each(['success', 'warning', 'danger', 'local', 'accent'])('배지 테두리·점 %s는 surface와 3:1 이상입니다', (c) => {
    expect(contrast(t[c], t.surface)).toBeGreaterThanOrEqual(3)
  })
})

describe('다크 모드 블록', () => {
  it('prefers-color-scheme와 data-theme 블록의 값이 같습니다', () => {
    expect(vars(block(":root:not([data-theme='light'])"))).toEqual(dark)
  })

  it('라이트와 같은 토큰 이름을 모두 정의합니다', () => {
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort())
  })
})
