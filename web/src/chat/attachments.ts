/** 채팅 이미지 첨부의 제한(gateway 계약: jpeg·png data URL, 메시지당 3장, 한 장 5MB). */
export const MAX_IMAGES = 3
export const MAX_BYTES = 5 * 1024 * 1024
export const IMAGE_TYPES = ['image/jpeg', 'image/png'] as const

export type PickedImage = { id: string; name: string; type: string; bytes: number; dataUrl: string }

let seq = 0

/**
 * 고른 파일을 확인해 붙일 이미지와 거절 사유로 나눕니다. 이미 붙인 수를 넘으면 앞에서부터 MAX_IMAGES까지만 받습니다.
 * 형식은 파일의 MIME 형식으로 봅니다(서버가 다시 확인함).
 */
export async function pickImages(files: File[], already: number): Promise<{ images: PickedImage[]; errors: string[] }> {
  const images: PickedImage[] = []
  const errors: string[] = []
  for (const f of files) {
    if (!(IMAGE_TYPES as readonly string[]).includes(f.type)) {
      errors.push(`${f.name}: JPEG·PNG 사진만 붙일 수 있습니다.`)
      continue
    }
    if (f.size > MAX_BYTES) {
      errors.push(`${f.name}: 5MB보다 큰 사진은 붙일 수 없습니다.`)
      continue
    }
    if (already + images.length >= MAX_IMAGES) {
      errors.push(`사진은 한 번에 ${MAX_IMAGES}장까지 붙일 수 있습니다.`)
      break
    }
    try {
      images.push({ id: `img-${++seq}`, name: f.name, type: f.type, bytes: f.size, dataUrl: await readDataUrl(f) })
    } catch {
      errors.push(`${f.name}: 사진을 읽지 못했습니다.`)
    }
  }
  return { images, errors }
}

function readDataUrl(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => (typeof r.result === 'string' ? resolve(r.result) : reject(new Error('not a string')))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(f)
  })
}

export const formatBytes = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`)
