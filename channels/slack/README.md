# 슬랙 브리지

직원이 슬랙 DM이나 채널 멘션으로 사내 AI 비서와 대화하게 하는 브리지입니다. gateway의 클라이언트로, 웹 화면과 같은 gateway API(대화, 실행 승인, 되돌리기, 알림)를 부릅니다. TypeScript, [Bolt for JavaScript](https://github.com/slackapi/bolt-js)(MIT) Socket Mode라 공개 URL이 필요 없습니다.

## 하는 일

| 슬랙에서 | 브리지가 하는 일 |
|---|---|
| 봇에게 DM, 또는 채널에서 `@봇` 멘션 | 슬랙 사용자를 gateway `/auth/slack`으로 직원 토큰과 바꾸고, 대화를 만들어 메시지를 보낸 뒤 답을 그 스레드에 올립니다. 같은 스레드는 같은 대화입니다 |
| 답에 근거가 있으면 | 문서 제목·조문과 인용문을 인용 블록으로 붙이고, 확인 안 된 인용은 표시합니다. 로컬 모델로 처리했으면 "로컬에서 처리"를 밝힙니다 |
| 되돌릴 수 없는 실행(`approval_required`) | 실행 미리보기 카드(바뀌는 값 전 → 후, 위험 등급)와 실행·취소 버튼. 누른 사람이 요청자 본인일 때만 gateway에 결정을 보냅니다 |
| 실행한 일(`action`) | 요약과, 되돌릴 수 있으면 되돌리기 버튼(요청자 본인만). 같은 행동은 같은 `Idempotency-Key`로 보내 두 번 눌러도 한 번만 되돌립니다 |
| 팀장 결재 차례 등 erp 알림 | 브리지에 한 번이라도 말을 건 직원에게 새 알림을 DM으로 보냅니다. 승인·반려는 사람 전용 기능이라 슬랙 버튼을 두지 않고 웹 승인함 링크만 붙입니다 |

- 봇 메시지와 편집·삭제(하위 형식이 있는 메시지)는 무시합니다.
- 연결된 직원 계정이 없는 슬랙 사용자에게는 안내만 하고 대화를 만들지 않습니다.
- 다른 사람이 남의 스레드에 쓰면 그 사람에게만 보이는 안내를 남기고 대화를 잇지 않습니다.
- 사용자·모델 글의 `&`, `<`, `>`는 바꿔 올려, 글 안의 `<!channel>` 같은 문자열이 멘션이나 링크로 읽히지 않게 합니다.

## 구조

| 파일 | 내용 |
|---|---|
| `src/bridge.ts` | 핵심. 스레드 ↔ 대화, 토큰 캐시(JWT `exp` 1분 전까지), 카드 소유자 확인, 알림 DM. Bolt와 gateway를 인터페이스(`Slack`, `Gateway`)로만 봐서 가짜로 시험합니다 |
| `src/gateway.ts` | gateway HTTP 클라이언트. SSE 스트림을 `ChatEvent`로 읽고, 오류는 problem+json `title`로 바꿉니다 |
| `src/render.ts` | `ChatEvent` 묶음 → Block Kit 메시지(답, 근거, 차단·오류, 미리보기 카드, 행동 카드, 알림) |
| `src/slack-app.ts` | Bolt 앱(Socket Mode)과 이벤트·버튼 연결 |
| `src/sse.ts` | `text/event-stream` 읽기(`web/src/chat/sse.ts`와 같은 규칙) |
| `src/schema.d.ts` | `contracts/openapi/gateway.yaml`에서 만든 타입(`npm run gen:api`) |

상태(스레드 ↔ 대화, 카드)는 메모리에만 둡니다. 브리지를 다시 시작하면 앞 카드의 버튼은 "더 결정할 수 없음" 안내만 하고, 새 스레드로 다시 시작합니다.

## 슬랙 앱 설정

- Socket Mode 켜기, App-Level Token(`connections:write`) → `SLACK_APP_TOKEN`
- Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write` → `SLACK_BOT_TOKEN`
- Event Subscriptions(봇): `app_mention`, `message.im`
- Interactivity 켜기(Socket Mode라 URL 없음)
- App Home의 Messages 탭에서 DM 보내기 허용

## 실행

환경 변수는 저장소 `.env`에서 읽습니다. 토큰과 비밀값은 출력하거나 커밋하지 않습니다.

| 변수 | 내용 |
|---|---|
| `SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN` | 위 슬랙 앱의 토큰 |
| `SLACK_BRIDGE_SECRET` | gateway `/auth/slack`이 브리지를 확인하는 비밀값(gateway와 같은 값) |
| `GATEWAY_URL` | 기본 `http://localhost:${PORT_GATEWAY}/api` |
| `WEB_URL` | 알림의 승인함 링크. 기본 `http://localhost:${PORT_WEB}` |
| `SLACK_NOTIFY_INTERVAL_MS` | 알림 확인 주기. 기본 60000 |

```bash
cd channels/slack
npm ci
npm test            # 시험(가짜 gateway·슬랙)
npm run typecheck
source ../../scripts/env.sh 6 && npm run dev   # 빌드 후 ../../.env를 읽어 실행
```

## 지금 상태

- gateway `/auth/slack`(#273)이 아직 없어, 요청 형식(`POST /auth/slack`, 헤더 `X-Slack-Bridge-Secret`, 본문 `{"slackUserId"}`, 응답 `LoginResponse`, 매핑 없으면 403)은 #273 계약이 정해지면 맞춥니다.
- 2026-11-21 실제 워크스페이스 토큰으로 Socket Mode 연결과 `auth.test`가 되는 것을 확인했습니다. 대화·버튼을 실제로 주고받은 확인과 스크린샷은 #273 뒤에 합니다.
- compose 서비스(`--profile slack`)와 CI job은 루트 파일이라 프로젝트 리드가 넣습니다. 이미지는 `channels/slack/Dockerfile`입니다.

## 라이선스 표기

- @slack/bolt: MIT
