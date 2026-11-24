import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// 토큰 대비 시험. ux/design-system/tokens.test.mjs와 같은 방식입니다(명세 ux/design-system.md 7.4).
// 글자로 쓰는 색이 실제로 깔리는 면(반투명 면은 아래 면과 섞은 색) 위에서 밝음·어두움 모두 4.5:1 이상인지 봅니다.
const css = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8')

function block(selector: string): string {
  const start = css.indexOf(selector)
  if (start < 0) throw new Error(`${selector} 블록이 없습니다`)
  const open = css.indexOf('{', start + selector.length - 1)
  return css.slice(open + 1, css.indexOf('}', open))
}

function vars(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  // 주석 안의 글은 읽지 않습니다
  for (const m of body.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/--([a-z0-9-]+):\s*([^;]+);/gi)) out[m[1]] = m[2].trim()
  return out
}

const light = vars(block(':root {'))
// 어두움 블록만 읽습니다. var() 참조는 :root에만 있으므로 값을 풀 때만 밝음 블록을 봅니다.
const darkOnly = vars(block(":root[data-theme='dark'] {"))
const dark = { ...light, ...darkOnly }
const COLOR = /#[0-9a-f]{6}|rgb\(/i

/** var(--x)를 풀어 '#rrggbb'나 'rgb(…)'를 돌려줍니다 */
function value(t: Record<string, string>, name: string): string {
  if (name.startsWith('#')) return name
  const v = t[name]
  if (!v) throw new Error(`--${name} 값이 없습니다`)
  const ref = /^var\(--([a-z0-9-]+)\)$/.exec(v)
  return ref ? value(t, ref[1]) : v
}

type RGBA = [number, number, number, number]
function parse(v: string): RGBA {
  if (v.startsWith('#')) return [...[1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)), 1] as RGBA
  const m = /rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)%\)/.exec(v)
  if (!m) throw new Error(`색을 읽지 못했습니다: ${v}`)
  return [+m[1], +m[2], +m[3], +m[4] / 100]
}

/** 반투명 색을 아래 면 위에 얹은 색 */
function over(top: string, under: string): [number, number, number] {
  const [r, g, b, a] = parse(top)
  const [R, G, B] = parse(under)
  return [r * a + R * (1 - a), g * a + G * (1 - a), b * a + B * (1 - a)]
}

const lum = (rgb: number[]) =>
  rgb
    .map((c) => c / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0)

export function ratio(a: number[], b: number[]): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

// [글자, 면, 면 아래(반투명 면일 때)]. 앞 23쌍은 ux/design-system/tokens.test.mjs의 PAIRS입니다.
const PAIRS: [string, string, string?][] = [
  ['text', 'bg'],
  ['text', 'surface'],
  ['text-2', 'bg'],
  ['text-2', 'surface'],
  ['text-2', 'surface-2'],
  ['text-2', 'fill-2', 'surface'],
  ['text-2', 'sidebar-bg', 'bg'],
  ['text', 'sel', 'surface'],
  ['text-2', 'sel', 'surface'],
  ['text', 'seg-thumb'],
  ['text-2', 'popover-bg', 'surface'],
  ['#ffffff', 'avatar-bg'],
  ['accent', 'surface'],
  ['accent', 'bg'],
  ['accent', 'sel', 'surface'],
  ['on-accent', 'accent-fill'],
  ['progress', 'surface'],
  ['progress', 'bg'],
  ['success', 'surface'],
  ['warning', 'surface'],
  ['danger', 'surface'],
  ['danger', 'fill', 'surface'],
  ['neutral', 'surface'],
]

describe.each([
  ['밝음', light],
  ['어두움', dark],
])('%s 토큰 대비', (_name, t) => {
  it.each(PAIRS)('글자 %s / 면 %s(아래 %s)는 4.5:1 이상입니다', (fg, bg, under) => {
    const face = under ? over(value(t, bg), value(t, under)) : parse(value(t, bg)).slice(0, 3)
    expect(ratio(parse(value(t, fg)).slice(0, 3), face)).toBeGreaterThanOrEqual(4.5)
  })
})

describe('어두움 블록', () => {
  it('밝음에 값으로 있는 색 토큰은 어두움에도 모두 있습니다', () => {
    const missing = Object.entries(light)
      .filter(([, v]) => COLOR.test(v) && !v.includes('var('))
      .map(([k]) => k)
      .filter((k) => !(k in darkOnly))
    expect(missing).toEqual([])
  })

  it('prefers-color-scheme와 data-theme 블록의 값이 같습니다', () => {
    expect(vars(block(":root:not([data-theme='light']) {"))).toEqual(darkOnly)
  })
})
