import { describe, expect, it } from 'vitest'
import { readSse } from './sse'

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch))
      c.close()
    },
  })
}

async function collect(s: ReadableStream<Uint8Array>) {
  const out = []
  for await (const m of readSse(s)) out.push(m)
  return out
}

describe('readSse', () => {
  it('event와 data를 빈 줄 단위로 묶습니다', async () => {
    expect(await collect(streamOf('event: delta\ndata: {"a":1}\n\nevent: done\ndata: {}\n\n'))).toEqual([
      { event: 'delta', data: '{"a":1}' },
      { event: 'done', data: '{}' },
    ])
  })

  it('조각 경계가 줄·글자 중간이어도 같은 결과를 냅니다', async () => {
    const text = 'event: delta\r\ndata: {"t":"회의실"}\r\n\r\n'
    const bytes = new TextEncoder().encode(text)
    const chunks: ReadableStream<Uint8Array> = new ReadableStream({
      start(c) {
        for (const b of bytes) c.enqueue(new Uint8Array([b]))
        c.close()
      },
    })
    expect(await collect(chunks)).toEqual([{ event: 'delta', data: '{"t":"회의실"}' }])
  })

  it('주석 줄은 건너뛰고 여러 data 줄은 줄바꿈으로 잇습니다', async () => {
    expect(await collect(streamOf(': ping\n\ndata: a\ndata: b\n\n'))).toEqual([{ event: 'message', data: 'a\nb' }])
  })

  it('끝에 빈 줄이 없어도 마지막 이벤트를 돌려줍니다', async () => {
    expect(await collect(streamOf('event: done\ndata: {}'))).toEqual([{ event: 'done', data: '{}' }])
  })
})
