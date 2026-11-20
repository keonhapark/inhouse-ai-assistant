# web

직원 채팅과 팀장 승인함 화면입니다(승인함은 준비 중). React, TypeScript, Vite로 만들고, gateway(`contracts/openapi/gateway.yaml`)만 부릅니다. 디자인 기준은 `DESIGN.md`입니다.

## 실행

```bash
npm ci
npm run dev:mock     # gateway 계약 모의 서버(MSW)로 실행합니다. 사번 E1001 또는 E2001, 비밀번호 demo
npm run dev          # 실제 gateway에 붙입니다. /api를 GATEWAY_URL(기본 http://localhost:$PORT_GATEWAY)로 넘깁니다
```

포트는 `docs/ports.md`를 따릅니다. 저장소 루트에서 `source scripts/env.sh 6`을 하면 web은 8600, gateway는 8610입니다.

## 검사

```bash
npm run lint     # oxlint
npm test         # vitest + Testing Library, 요청은 MSW 모의 서버가 받습니다
npm run build    # tsc -b와 vite build
npm run gen:api  # 계약이 바뀌면 src/api/schema.d.ts를 다시 만듭니다(openapi-typescript)
```

## 구조

| 경로 | 내용 |
|---|---|
| `src/api/schema.d.ts` | gateway 계약에서 만든 타입(생성 파일) |
| `src/api/client.ts` | openapi-fetch 클라이언트. 직원 JWT를 붙이고 401이면 로그아웃합니다 |
| `src/auth/` | 로그인 상태(토큰은 sessionStorage) |
| `src/styles/tokens.css` | DESIGN.md 토큰(라이트·다크) |
| `src/components/` | 기본 부품(버튼, 배지, 카드) |
| `src/pages/` | 로그인, 상단바, 디자인 부품(`/design`) |
| `src/chat/` | 직원 채팅. SSE 읽기(`sse.ts`), ChatEvent를 화면 상태로 바꾸는 리듀서(`thread.ts`), 미리보기·행동·근거 부품 |
| `src/mocks/` | gateway 계약 모의 서버(MSW)와 지어낸 직원 데이터 |
| `Dockerfile`, `nginx/` | 정적 파일과 `/api` 프록시, `GET /health` |

## 대비

`src/styles/contrast.test.ts`가 토큰 쌍의 대비를 WCAG 식으로 계산합니다. `--success`(흰 바탕 4.3:1)와 `--warning`(4.2:1)은 글자색으로 쓰면 본문 기준 4.5:1에 못 미쳐, 배지는 글자를 `--text`로 두고 상태색을 테두리와 점(3:1 기준)에만 씁니다.

## 실행 이미지

```bash
docker build -t iaa-web .
docker run -p 8600:80 -e GATEWAY_URL=http://host.docker.internal:8610 iaa-web
```

## 채팅 화면이 ChatEvent를 쓰는 방법

| ChatEvent | 화면 |
|---|---|
| `route` | 대화 머리에 에이전트 이름, 고른 방법(자동·직접·맞는 부서 없음), 이유 |
| `delta` → `message` | 조각을 이어 붙이다가 `message`로 확정합니다. `model.location`이 `local`이면 "로컬에서 처리" 배지 |
| `tool_call` | 접힌 "도구 실행" 줄 |
| `approval_required` | 미리보기 카드(위험 배지, 바뀌는 값 전 → 후, 만료 시각, 실행·취소). 결정 전에는 입력을 막습니다(gateway는 409) |
| `approval_decided` | 카드 발에 "실행함"·"취소함" |
| `action` | 행동 카드. `undoable`이면 되돌리기(같은 카드에서는 같은 `Idempotency-Key`) |
| `citations` | 같은 차례 답 아래 접이식 근거. `verified: false`는 "인용 확인 안 됨" |
| `blocked`, `error` | 이유 한 문장. 다시 시도할 수 있는 오류면 "다시 보내기" |
| `done` | 스트리밍 끝 |

`seq`가 이미 반영한 값 이하이면 버립니다. 대화를 다시 열면 `GET /conversations/{id}`의 `events`를 같은 리듀서로 다시 그립니다.

## 화면

모의 서버(`npm run dev:mock`)로 실행해 찍은 화면입니다.

| 미리보기 카드 | 실행·되돌리기·차단 |
|---|---|
| ![미리보기](docs/images/chat-preview-light.png) | ![행동](docs/images/chat-action-light.png) |

| 근거와 로컬 처리 | 다크 모드 |
|---|---|
| ![근거](docs/images/chat-citations-light.png) | ![다크](docs/images/chat-preview-dark.png) |

| 로그인 오류 | 디자인 부품 |
|---|---|
| ![로그인 오류](docs/images/login-error-light.png) | ![부품](docs/images/design-light.png) |

## 라이선스 표기

- Pretendard: SIL Open Font License 1.1
- MSW, openapi-typescript, openapi-fetch, React, React Router, Vite: MIT
