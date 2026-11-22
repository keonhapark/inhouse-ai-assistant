// 시안 HTML을 만듭니다: node mockups/build.mjs
// 만든 HTML은 빌드 도구 없이 브라우저로 바로 열 수 있는 정적 파일입니다.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { refinedApprovals, refinedChat } from './src/refined.mjs'
import { DIRECTIONS, approvalsScreen, chatScreen } from './src/templates.mjs'

const here = import.meta.dirname
for (const dir of Object.keys(DIRECTIONS)) {
  writeFileSync(join(here, dir, 'chat.html'), chatScreen(dir))
  writeFileSync(join(here, dir, 'approvals.html'), approvalsScreen(dir))
}
// 다듬은 판(#571)
writeFileSync(join(here, 'refined', 'chat.html'), refinedChat())
writeFileSync(join(here, 'refined', 'approvals.html'), refinedApprovals())
console.log(`시안 ${Object.keys(DIRECTIONS).length * 2 + 2}장을 만들었습니다`)
