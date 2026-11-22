// 토큰 대비 시험: npm test
// 글자로 쓰는 색이 실제로 깔리는 면(반투명 면은 아래 면과 섞은 색) 위에서 4.5:1 이상인지 밝음·어두움 모두 봅니다.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8')

function block(selector) {
  const start = css.indexOf(selector)
  assert.ok(start >= 0, `${selector} 블록이 없습니다`)
  const open = css.indexOf('{', start + selector.length - 1)
  return css.slice(open + 1, css.indexOf('}', open))
}
function vars(body) {
  const out = {}
  for (const m of body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/gi)) out[m[1]] = m[2].trim()
  return out
}
const light = vars(block(':root {'))
// 어두움은 밝음 값에 기대지 않고 그 블록만 읽습니다(어두움 값이 빠지면 시험이 잡음).
const dark = vars(block(":root[data-theme='dark'] {"))
const COLOR = /#[0-9a-f]{6}|rgb\(/i

/** '#rrggbb' 또는 'rgb(r g b / a%)'를 [r, g, b, a]로 */
function parse(v) {
  assert.ok(v, '값이 없습니다')
  if (v.startsWith('#')) return [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)).concat(1)
  const m = v.match(/rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)%\)/)
  assert.ok(m, `색을 읽지 못했습니다: ${v}`)
  return [+m[1], +m[2], +m[3], +m[4] / 100]
}
/** 반투명 색을 아래 면 위에 얹은 색 */
const over = (top, under) => {
  const [r, g, b, a] = parse(top)
  const [R, G, B] = parse(under)
  return [r * a + R * (1 - a), g * a + G * (1 - a), b * a + B * (1 - a)]
}
const lum = ([r, g, b]) =>
  [r, g, b]
    .map((c) => c / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0)
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

// [글자, 면, 면 아래(반투명 면일 때)]
const PAIRS = [
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

for (const [theme, t] of [['밝음', light], ['어두움', dark]]) {
  test(`${theme}: 글자 대비 4.5:1 이상`, () => {
    for (const [fg, bg, under] of PAIRS) {
      const face = under ? over(t[bg], t[under]) : parse(t[bg]).slice(0, 3)
      const r = ratio(parse(fg.startsWith('#') ? fg : t[fg]).slice(0, 3), face)
      assert.ok(r >= 4.5, `${theme} --${fg} / --${bg}${under ? `(on --${under})` : ''} = ${r.toFixed(2)}`)
    }
  })
}

test('밝음에 있는 색 토큰은 어두움에도 모두 있습니다', () => {
  const missing = Object.entries(light)
    .filter(([k, v]) => COLOR.test(v) && !v.includes('var('))
    .map(([k]) => k)
    .filter((k) => !(k in dark))
  assert.deepEqual(missing, [])
})

test('어두움 블록 둘(prefers-color-scheme, data-theme)의 값이 같습니다', () => {
  const media = vars(block(":root:not([data-theme='light']) {"))
  const attr = vars(block(":root[data-theme='dark'] {"))
  assert.deepEqual(media, attr)
})
