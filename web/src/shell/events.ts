/** 채팅 화면이 받는 "새 대화" 이벤트. 채팅 화면이 아니면 AI 비서로 옮기기만 합니다(처음 열면 빈 대화) */
export const NEW_CHAT = 'inhouse-ai:new-chat'

/** 맥은 ⌘ K, 그 밖은 Ctrl K. 맥의 Ctrl K(줄 끝까지 지우기)는 두고, 한글을 조합하는 중에는 받지 않습니다 */
const isMac = () => /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
export const isPaletteKey = (e: KeyboardEvent) =>
  e.key.toLowerCase() === 'k' && !e.isComposing && !e.defaultPrevented && (isMac() ? e.metaKey : e.ctrlKey) && !e.altKey && !e.shiftKey
