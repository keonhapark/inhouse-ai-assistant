/** 채팅 이미지 첨부의 제한(gateway 계약: jpeg·png data URL, 메시지당 3장, 한 장 5MB). */
export const MAX_IMAGES = 3
export const MAX_BYTES = 5 * 1024 * 1024
/** 파일 고르기 창에서 보일 형식. 운영체제에 따라 MIME이 비거나 image/jpg로 오는 경우가 있어 확장자도 넣습니다 */
export const ACCEPT = 'image/jpeg,image/png,.jpg,.jpeg,.png'

export type MediaType = 'image/jpeg' | 'image/png'

/**
 * 보내기 전 사진. 화면 표시는 object URL로 하고(큰 data URL 문자열을 상태에 두지 않음), data URL은 보낼 때 만듭니다.
 * 다 쓰면 release로 object URL을 풉니다.
 */
export type PickedImage = { id: string; name: string; mediaType: MediaType; bytes: number; file: Blob; url: string }

let seq = 0

/** 파일 앞 바이트로 형식을 봅니다. 확장자·MIME은 운영체제마다 달라 믿지 않습니다. */
export async function sniff(file: Blob): Promise<MediaType | 'heic' | null> {
  const b = new Uint8Array(await readBytes(file.slice(0, 12)))
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return 'image/jpeg'
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return 'image/png'
  const brand = String.fromCharCode(...b.slice(4, 12))
  if (/^ftyp(heic|heix|hevc|mif1|msf1)/.test(brand)) return 'heic'
  return null
}

/**
 * 고른 파일을 확인해 붙일 사진과 거절 사유로 나눕니다. already는 이미 붙인 수입니다.
 * 넘친 사진은 몇 장을 뺐는지 알립니다.
 */
export async function pickImages(files: File[], already: number): Promise<{ images: PickedImage[]; errors: string[] }> {
  const images: PickedImage[] = []
  const errors: string[] = []
  let over = 0
  for (const f of files) {
    let kind: Awaited<ReturnType<typeof sniff>>
    try {
      kind = await sniff(f)
    } catch {
      errors.push(`${f.name}: 사진을 읽지 못했습니다.`)
      continue
    }
    if (kind === 'heic') {
      errors.push(`${f.name}: HEIC 사진은 첨부할 수 없습니다. 휴대폰 카메라 설정에서 JPEG(호환성 우선)로 저장해 주세요.`)
      continue
    }
    if (!kind) {
      errors.push(`${f.name}: JPEG·PNG 사진만 첨부할 수 있습니다.`)
      continue
    }
    if (f.size > MAX_BYTES) {
      errors.push(`${f.name}: 5MB보다 큰 사진은 첨부할 수 없습니다.`)
      continue
    }
    if (already + images.length >= MAX_IMAGES) {
      over++
      continue
    }
    images.push({ id: `img-${++seq}`, name: f.name, mediaType: kind, bytes: f.size, file: f, url: URL.createObjectURL(f) })
  }
  if (over) errors.push(`${over}장은 첨부하지 않았습니다. 사진은 한 번에 ${MAX_IMAGES}장까지 첨부할 수 있습니다.`)
  return { images, errors }
}

/** 보낼 때 data URL을 만듭니다. 머리는 앞 바이트로 본 형식으로 다시 붙입니다(계약: data:image/jpeg|png;base64,). */
export async function toDataUrl(img: PickedImage): Promise<string> {
  const raw = await new Promise<string>((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => (typeof r.result === 'string' ? resolve(r.result) : reject(new Error('not a string')))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(img.file)
  })
  return `data:${img.mediaType};base64,${raw.slice(raw.indexOf(',') + 1)}`
}

export function release(images: { url: string }[]) {
  for (const i of images) URL.revokeObjectURL(i.url)
}

function readBytes(b: Blob): Promise<ArrayBuffer> {
  if (typeof b.arrayBuffer === 'function') return b.arrayBuffer()
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as ArrayBuffer)
    r.onerror = () => reject(r.error)
    r.readAsArrayBuffer(b)
  })
}

export const formatBytes = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`)
