// text/event-stream을 읽어 이벤트 하나씩 돌려줍니다. POST 응답이라 EventSource를 쓰지 못해 직접 읽습니다.
// 규칙은 HTML 표준 "event stream interpretation"의 부분집합(event, data, 주석 줄, 빈 줄로 끊기)입니다.

export type SseMessage = { event: string; data: string }

export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let event = ''
  let data: string[] = []

  // 빈 줄이면 모은 이벤트를 돌려줍니다.
  function line(text: string): SseMessage | null {
    if (text === '') {
      const msg = data.length ? { event: event || 'message', data: data.join('\n') } : null
      event = ''
      data = []
      return msg
    }
    if (text.startsWith(':')) return null
    const colon = text.indexOf(':')
    const field = colon < 0 ? text : text.slice(0, colon)
    let value = colon < 0 ? '' : text.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    return null
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      for (;;) {
        const nl = buf.search(/[\r\n]/)
        if (nl < 0) break
        // \r로 끝난 조각은 다음 조각의 \n과 한 줄바꿈일 수 있어 기다립니다.
        if (buf[nl] === '\r' && nl === buf.length - 1) break
        const width = buf.startsWith('\r\n', nl) ? 2 : 1
        const msg = line(buf.slice(0, nl))
        buf = buf.slice(nl + width)
        if (msg) yield msg
      }
    }
    buf += decoder.decode()
    // 끝에 줄바꿈이나 빈 줄 없이 닫혀도 모은 이벤트는 버리지 않습니다.
    if (buf) line(buf.replace(/\r$/, ''))
    const last = line('')
    if (last) yield last
  } finally {
    reader.releaseLock()
  }
}
