import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from './markdown'

const html = (text: string, tail?: React.ReactNode) => render(<Markdown text={text} tail={tail} />).container

describe('Markdown(채팅 답)', () => {
  it('굵게·기울임·코드를 그립니다', () => {
    const c = html('부품 번호는 **RND-PRT-1037**이고 *참고*로 `S45C`입니다.')
    expect(c.querySelector('strong')?.textContent).toBe('RND-PRT-1037')
    expect(c.querySelector('em')?.textContent).toBe('참고')
    expect(c.querySelector('code')?.textContent).toBe('S45C')
    expect(c.textContent).toBe('부품 번호는 RND-PRT-1037이고 참고로 S45C입니다.')
  })

  it('곱셈·별표 하나·닫히지 않은 굵게는 글자 그대로 둡니다', () => {
    const c = html('5 * 3 = 15, 2 ** 3, **스트리밍 중')
    expect(c.querySelector('strong, em')).toBeNull()
    expect(c.textContent).toBe('5 * 3 = 15, 2 ** 3, **스트리밍 중')
  })

  it('* · - 목록과 번호 목록, 들여 쓴 하위 목록을 그립니다', () => {
    const c = html('값:\n*   **금액**: 5,800원\n*   **날짜**: 2026-09-30\n    - 영수증 기준\n\n3. 셋째\n4. 넷째')
    const ul = c.querySelector('ul')!
    expect(ul.children).toHaveLength(2)
    expect(ul.children[0].textContent).toBe('금액: 5,800원')
    expect(ul.children[1].querySelector('ul li')?.textContent).toBe('영수증 기준')
    const ol = c.querySelector('ol')!
    expect(ol.getAttribute('start')).toBe('3')
    expect(Array.from(ol.children).map((li) => li.textContent)).toEqual(['셋째', '넷째'])
  })

  it('빈 줄로 문단을 나누고 문단 안 줄바꿈은 그대로 둡니다', () => {
    const c = html('첫 줄\n둘째 줄\n\n새 문단')
    const ps = c.querySelectorAll('p')
    expect(ps).toHaveLength(2)
    expect(ps[0].querySelector('br')).not.toBeNull()
    expect(ps[1].textContent).toBe('새 문단')
  })

  it('제목 줄은 굵은 문단으로, 코드 블록은 pre로 그립니다(닫히지 않은 블록 포함)', () => {
    const c = html('### 요약\n```\n<b>그대로</b>\n  들여쓰기\n```\n끝\n```\n열린 채')
    expect(c.querySelector('h1, h2, h3, h4, h5, h6')).toBeNull()
    expect(c.querySelector('p strong')?.textContent).toBe('요약')
    const pres = c.querySelectorAll('pre')
    expect(pres[0].textContent).toBe('<b>그대로</b>\n  들여쓰기')
    expect(pres[1].textContent).toBe('열린 채')
  })

  it('HTML은 글자로 두고 그리지 않습니다', () => {
    const c = html('<img src=x onerror="alert(1)"> <script>alert(1)</script> **<i>굵게</i>**')
    expect(c.querySelector('img, script, i')).toBeNull()
    expect(c.textContent).toContain('<script>alert(1)</script>')
    expect(c.querySelector('strong')?.textContent).toBe('<i>굵게</i>')
  })

  it('링크는 http·https만 새 창 링크로, 그 밖의 주소는 글자로 둡니다', () => {
    const c = html('[규정](https://intra.example/policy) [나쁨](javascript:alert(1)) [파일](file:///etc/passwd)')
    const links = c.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('https://intra.example/policy')
    expect(links[0].getAttribute('target')).toBe('_blank')
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer')
    expect(c.textContent).toContain('규정(새 창) (intra.example)')
    expect(c.textContent).toContain('나쁨(javascript:alert(1))')
    expect(c.textContent).toContain('파일(file:///etc/passwd)')
  })

  it('링크 글자와 다른 실제 주소(host)를 함께 보이고, 사용자 정보가 든 주소는 글자로 둡니다', () => {
    const c = html('[https://intra.example](https://evil.example/x) [규정](https://intra.example@evil.example/login)')
    const links = c.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].textContent).toBe('https://intra.example(새 창)')
    expect(c.textContent).toContain('(evil.example)')
    expect(c.textContent).toContain('규정(https://intra.example@evil.example/login)')
  })

  it('굵게 안의 기울임과 ***강조***를 그립니다', () => {
    const c = html('**굵게 *기울임* 굵게** ***강조***')
    const strongs = c.querySelectorAll('strong')
    expect(strongs[0].textContent).toBe('굵게 기울임 굵게')
    expect(strongs[0].querySelector('em')?.textContent).toBe('기울임')
    expect(strongs[1].querySelector('em')?.textContent).toBe('강조')
    expect(c.textContent).not.toContain('*')
  })

  it('한 줄 안의 ```코드```는 코드 블록을 열지 않습니다', () => {
    const c = html('```ls -al``` 로 봅니다\n\n다음 문단')
    expect(c.querySelector('pre')).toBeNull()
    expect(c.querySelectorAll('p')).toHaveLength(2)
    expect(c.querySelector('p code')?.textContent).toBe('ls -al')
  })

  it('긴 공백이 든 제목 줄도 빨리 그립니다(정규식 되짚기 없음)', () => {
    const t0 = performance.now()
    const c = html('# a' + ' '.repeat(4000) + 'b ##')
    expect(performance.now() - t0).toBeLessThan(200)
    expect(c.querySelector('p strong')?.textContent?.endsWith('b')).toBe(true)
  })

  it('tail(스트리밍 커서)을 마지막 블록 끝에 붙입니다', () => {
    const c = html('*   하나\n*   둘', <span data-testid="cursor" />)
    expect(c.querySelector('ul li:last-child [data-testid=cursor]')).not.toBeNull()
    const empty = html('', <span data-testid="cursor" />)
    expect(empty.querySelector('[data-testid=cursor]')).not.toBeNull()
  })
})
