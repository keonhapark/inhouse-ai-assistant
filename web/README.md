# web

직원이 쓰는 AI 비서(채팅), 결재·대결 설정, 조직도·AI 에이전트 화면과 감사 권한자의 운영 화면입니다. React, TypeScript, Vite로 만들고, gateway(`contracts/openapi/gateway.yaml`)만 부릅니다. 디자인 기준은 `ux/design-system.md`(재설계 #558)이고 모든 화면을 이 기준으로 옮겼습니다(#557). `DESIGN.md`는 옮기기 전 안내입니다. 예전 주소(`/inbox`, `/admin`, `/eval`)는 새 주소로 옮겨 갑니다.

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

사람이 웹 화면으로 직접 써 보는 실사용 시험은 [절차](docs/manual-test.md)와 [기록 양식](docs/manual-test-record.md)을 따릅니다. 결과는 `eval/reports/manual/`에 둡니다.

## 구조

| 경로 | 내용 |
|---|---|
| `src/api/schema.d.ts` | gateway 계약에서 만든 타입(생성 파일) |
| `src/api/client.ts` | openapi-fetch 클라이언트. 직원 JWT를 붙이고 401이면 로그아웃합니다 |
| `src/auth/` | 로그인 상태(토큰은 sessionStorage) |
| `src/styles/tokens.css` | 디자인 토큰(밝음·어두움). `ux/design-system/tokens.css`와 이름·값이 같습니다 |
| `src/components/` | 공용 부품과 스타일: 버튼, 태그, 묶음 목록(`GroupHead`), 표, 세그먼트, 팝오버, 한국식 날짜 고르개(`DatePicker`) |
| `src/pages/` | 로그인, 앱 셸, 디자인 부품(`/design`) |
| `src/shell/` | 왼쪽 탐색 막대(업무·회사·운영 묶음, 결재 건수, 접기, 사용자 메뉴의 테마), 명령 팔레트(Ctrl K), 로그인 뒤 역할별 첫 화면 |
| `src/inbox/` | 결재(`/approvals`: 결재 대기·대결 대기·결재 완료·기안함, 두 줄 행 목록과 상세, 결재선, 승인 확인 팝오버, 반려 사유)와 대결 설정(`/delegations`: 대결자 찾기, 날짜 고르개, 양식 범위, 내용 확인 → 대결 지정, 해제) |
| `src/org/` | 조직도(사람 찾기, 부서 나무, 상위 경로, 구성원·하위 부서·담당 AI 에이전트)와 AI 에이전트(담당 부서, 사용할 수 있는 사람, AI 처리, 할 수 있는 일과 실행 방식). `/org`, `/agents` |
| `src/admin/` | 운영 화면(auditor만, 탐색 막대의 운영 묶음). 기간 세그먼트와 날짜 범위, 운영 지표(합계, 에이전트별, 차단 이유, 에이전트 자동 선택, 비용 상한), 외부 전송 기록(가린 자리 표시), 감사 로그(이름 표시, 필터, 더 보기). `/ops/metrics`, `/ops/egress`, `/ops/audit` |
| `src/eval/` | 평가 리포트(auditor만). eval 하네스의 보고서 JSON(`contracts/eval/report.schema.json`)을 gateway `/eval/reports`로 받아 실행 조건, 세트별 지표(비율과 95% 구간 막대, 짝 차이와 판정), 실행 전 확인 요청·경로·비용, 시나리오별 회차 결과를 보여 줍니다. 통계는 보고서 summary 값을 그대로 씁니다. `/ops/eval` |
| `src/chat/` | AI 비서(채팅). SSE 읽기(`sse.ts`), ChatEvent를 화면 상태로 바꾸는 리듀서(`thread.ts`), 실행 전 확인 시트·완료한 일 행·근거 규정 부품 |
| `src/display/` | 화면 표시 이름(도구·필드·역할·담당 AI), 시각·금액·날짜 표기 |
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

## 결재 화면이 계약을 쓰는 방법

- 승인·반려는 화면이 본 문서 `version`을 보냅니다. 409(`version-conflict`)면 오류 문구를 보여 주고 문서를 다시 불러옵니다.
- `Idempotency-Key`는 결정·버전·의견이 모두 같은 재시도에만 다시 씁니다. 내용이 다른데 키가 같으면 erp가 `idempotency-key-reused`로 거절하기 때문입니다.
- 대결 지정은 `dryRun=true`로 내용 확인을 먼저 받고, 지정에는 내용 확인을 만든 요청 본문을 그대로 보냅니다. 내용 확인 뒤 입력을 바꾸면 확인 카드를 지웁니다.
- 결재선 이름은 gateway가 붙인 `steps[].approverName`·`actedByName`을 쓰고, 없으면 직원 ID를 보여 줍니다.

## 실제 gateway와 붙여 확인한 결과

재설계(#557) 전 화면으로 확인한 기록입니다. 화면 이름은 그때 것(승인함, 되돌리기, 실행 승인 카드)입니다.

`infra/compose.yaml`의 `full` 프로필(erp, gateway, agent, rag, LiteLLM, 로컬 모델 `qwen3.5:9b`)로 띄워 2026-11-20에 확인했습니다. 직원(E0007)이 인사 에이전트에게 오후 반차를 신청하고 되돌린 뒤, 다시 신청한 것을 팀장(E0006)이 승인함에서 승인했습니다.

![실제 실행: 반차 신청 → 되돌리기 → 다시 신청 → 팀장 승인](docs/images/demo-leave-real.gif)

GIF는 화면이 바뀌지 않는 구간(로컬 모델 응답을 기다리는 20~40초)을 빼고 빠르게 돌린 것입니다.

| 실제 채팅(되돌린 뒤) | 실제 승인함 |
|---|---|
| ![실제 채팅](docs/images/real-chat-undo.png) | ![실제 승인함](docs/images/real-inbox.png) |

모의 서버와 다른 점:

| 항목 | 모의 서버 | 실제 | 화면 영향 |
|---|---|---|---|
| 답 조각(`delta`), 도구 기록(`tool_call`) | 보냄 | 보내지 않음(답이 `message` 한 번에 옴) | 답이 한 번에 나타남. 스트리밍 커서와 "도구 실행" 줄이 없음 |
| 쓴 모델(`model`) | `message`·`done`에 붙임(실제 모델 이름) | `done`에 붙임. 이름은 별칭(`local`, `external`)(2026-11-21 API로 확인) | 배지는 `location`으로 정하므로 같음 |
| 실행 승인 카드 | 결재 회수(`irreversible`)에서 나옴. 회의실 예약(`reversible_write`)은 카드 없이 실행하고 되돌리기를 붙임 | 같은 위험 등급 정책(결정 0003). 휴가 신청도 `reversible_write`·`auto_with_undo`라 카드 없이 실행되고 되돌리기가 붙음 | 정책대로 동작 |
| `toolLabel` | 있음 | 없음 | 카드 머리에 도구 ID를 보여 줌 |
| `blocked.code` | 이유별 | `policy_denied` 하나 | 문구만 보여 주므로 영향 없음 |
| 결재 문서 `fields` | 한국어 키 | 팩 `forms.yaml`의 키(`leave_type`, `start_date`)와 값(`half_pm`) | 값은 양식 스키마의 `x-labels`로 바꿔 보여 줌("오후 반차"). 필드 이름은 스키마에 `title`이 없어 키 그대로 |
| 감사 로그 순서 | 시각 순(오래된 것부터) | 같음(계약) | 첫 쪽이 기간의 가장 오래된 이벤트 |
| 감사 `llm.request`의 행위자 | 직원·에이전트 있음 | 직원·에이전트가 `null`인 것이 많음 | 직원·에이전트 필터로 찾을 수 없음(gateway에 알림) |
| 비용 상한 0 | 없음 | 인사·기술연구소가 상한 0(`exceeded: true`) | "상한 0 · 외부 안 씀"으로 보여 줌 |
| 라우팅 시간 | 즉시 | 로컬 모델이 바쁘면 시간 제한(504)으로 `fallback` | 에이전트를 직접 고르면 라우팅을 건너뜀 |

다시 확인하는 방법:

```bash
source scripts/env.sh 6
docker compose -f infra/compose.yaml --env-file .env --profile full up -d --build --wait
# http://localhost:8600 에서 E0007로 로그인 → 부서 에이전트 "인사" → 반차 신청 → 되돌리기
# E0006으로 로그인 → 승인함 → 승인
```

2026-11-20 확인 때는 compose에 맞지 않는 곳이 두 군데 있어 로컬 덮어쓰기 파일로 우회했습니다. rag가 빈 `RAG_EXTRA_DOCS`·`RAG_MARKERS_FILE`을 거절해 두 변수를 뺐고, agent가 모델 별칭 대신 `qwen3.5:9b`를 보내 gateway가 422로 거절해 `AGENT_LLM_MODEL=local`을 넣었습니다. 두 가지는 이후 rag(#97)와 agent(#96)에서 고쳐졌습니다.

## 화면

재설계(#557) 뒤 화면입니다. 1440×900, `ko-KR`·`Asia/Seoul`로 Playwright headless Chromium에서 찍었습니다(2026-11-24).

### 모의 서버

`npm run dev:mock`으로 띄워 모의 직원(직원 `E1001`, 팀장 `E2001`, 감사 `E2008`, 비밀번호 `demo`)으로 찍었습니다. 어두움은 시스템 테마(`prefers-color-scheme: dark`)로 찍었습니다.

| AI 비서: 실행 전 확인(결재 회수) | 어두움 |
|---|---|
| ![실행 전 확인](docs/images/chat-sheet-light.png) | ![실행 전 확인 어두움](docs/images/chat-sheet-dark.png) |

| AI 비서: 완료한 일(회의실 예약, 실행 취소) | 명령 팔레트(Ctrl K) |
|---|---|
| ![완료한 일](docs/images/chat-done-light.png) | ![명령 팔레트](docs/images/palette-light.png) |

| 결재: 목록과 상세 | 어두움 |
|---|---|
| ![결재](docs/images/approvals-light.png) | ![결재 어두움](docs/images/approvals-dark.png) |

| 결재: 승인 확인 팝오버 | 대결 설정: 날짜 고르개 |
|---|---|
| ![승인 확인](docs/images/approvals-confirm-light.png) | ![대결 설정](docs/images/delegations-light.png) |

| 조직도: 사람 찾기 | 어두움 |
|---|---|
| ![조직도](docs/images/org-light.png) | ![조직도 어두움](docs/images/org-dark.png) |

| AI 에이전트: 할 수 있는 일 | 어두움 |
|---|---|
| ![AI 에이전트](docs/images/agents-light.png) | ![AI 에이전트 어두움](docs/images/agents-dark.png) |

| 운영 지표 | 어두움 |
|---|---|
| ![운영 지표](docs/images/ops-metrics-light.png) | ![운영 지표 어두움](docs/images/ops-metrics-dark.png) |

| 감사 로그(이름 + 작은 ID) | 평가 리포트 |
|---|---|
| ![감사 로그](docs/images/ops-audit-light.png) | ![평가 리포트](docs/images/ops-eval-light.png) |

| 로그인 | 어두움 |
|---|---|
| ![로그인](docs/images/login-light.png) | ![로그인 어두움](docs/images/login-dark.png) |

대결 설정·감사 로그·평가 리포트의 어두움 화면은 `docs/images/*-dark.png`에 있습니다.

### 실제 스택

`infra/compose.yaml`의 `full` 프로필(erp, gateway, agent, rag, LiteLLM, 이 PC의 Ollama)을 세션 6 포트로 띄우고 web은 `npm run dev`로 붙여 찍었습니다. 이미지는 새로 빌드하지 않고 하루 전에 빌드한 것을 썼습니다. 직원 `E0007`이 AI 비서에 연차 규정을 묻고 오후 반차를 신청한 뒤, 팀장 `E0006`의 결재 대기에 그 문서가 들어온 것을 찍었습니다. 운영 화면은 감사 권한이 있는 `E0057`로 찍었습니다.

| AI 비서: 규정 답(근거 규정 2건) | AI 비서: 반차 신청 → 완료한 일 |
|---|---|
| ![실제 규정 답](docs/images/stack-chat-answer.png) | ![실제 완료한 일](docs/images/stack-chat-done.png) |

| 결재 대기에 들어온 문서 | 대결 설정 |
|---|---|
| ![실제 결재](docs/images/stack-approvals.png) | ![실제 대결 설정](docs/images/stack-delegations.png) |

| 운영 지표 | 감사 로그 |
|---|---|
| ![실제 운영 지표](docs/images/stack-ops-metrics.png) | ![실제 감사 로그](docs/images/stack-ops-audit.png) |

| 조직도 | AI 에이전트 |
|---|---|
| ![실제 조직도](docs/images/stack-org.png) | ![실제 AI 에이전트](docs/images/stack-agents.png) |

실제 스택에서 본 것 중 web 밖에서 고칠 것:

- 에이전트 답 본문에 "되돌릴 수 있습니다: …(행동 act_…)"처럼 내부 행동 ID와 옛 말이 들어갑니다(agent 고정 안내 문구).
- 결재 문서 상세의 필드 순서가 사유 → 종료일 → 종류 → 시작일로 나옵니다. 모의 서버는 양식 순서대로 나옵니다.

다시 찍는 방법:

```bash
source scripts/env.sh 6
docker compose -f infra/compose.yaml --profile full up -d --wait postgres erp rag agent litellm gateway
cd web && npm run dev            # http://localhost:8600
```

### 사진 첨부

채팅에서 JPEG·PNG 사진을 한 번에 3장(한 장 5MB)까지 첨부해 보냅니다(gateway 메시지 `attachments`, data URL). 형식은 파일 앞 바이트로 보고(MIME이 비거나 `image/jpg`여도 받음, HEIC는 JPEG로 저장해 달라고 안내), 화면 표시는 object URL로, data URL은 보낼 때만 만듭니다. 사진이 거절되면(413·415·422) 입력하던 글과 사진을 되돌립니다. 실행 전 확인 시트에는 gateway가 준 `fromAttachments`가 true이거나 마지막 카드 뒤에 사진을 보낸 적이 있으면 "사진에서 읽은 값" 태그를 붙입니다(사진에서 읽은 값은 신뢰 불가, 결정 0004). `fromAttachments`는 agent가 그 턴에 사진을 읽었는지만 알려 주므로, 사진을 보낸 뒤 되물은 질문에 글로 답한 턴의 카드는 false여도 표시합니다. 지난 대화는 기록의 첨부 메타로 "사진 n장 첨부"만 보여 줍니다(사진 본문은 저장하지 않음). 화면의 영수증은 시험용으로 지어낸 것이고, 모의 서버는 사진을 읽지 않고 정해 둔 값을 돌려줍니다(실제 읽기는 agent의 로컬 비전 모델).

실제 스택(S6, `PACK_STAGE=3`)에서 로컬 모델을 코랩 T4(터널 경유)로 붙여 확인했습니다(2026-11-22). 영수증은 `eval/tools/make_receipts.py`가 Noto Sans KR(SIL OFL)로 그린 개발 묶음 그림이고, 불량 사진·도면은 `eval/images/`의 생성 그림입니다. 세 경우 모두 에이전트가 사진을 보낸 턴에 값을 읽었습니다. 영수증·불량 사진은 한 번 되물은 뒤 다음 턴에 확인 카드가 떴고, 그 카드에 사진에서 읽은 값이라는 표시가 붙습니다. 도면은 실행할 도구가 없어 답 글로만 돌려줍니다.

- 영수증 `rcp-dev-002`: 금액·날짜·가맹점·사업자번호 네 값이 정답과 같았습니다. 다른 영수증(`rcp-dev-003`)에서는 날짜를 2027-03-24 대신 2024-03-27로 읽었습니다.
- 불량 사진 `defect-001`: 품목 코드 BRG-6204가 정답과 같았고, 유형은 `scratches`(정답 `scratch`)로 읽었습니다. 수량·로트 번호는 사진에 없어 되물었습니다.
- 도면 `dwg-001`: 부품 번호, 치수 4개, 주기(재질·모따기)가 정답과 같았습니다.

| 실제(재설계 전): 영수증 → 되물음 → 경비 정산 카드 | 실제: 불량 사진 → 되물음 → 불량 보고서 카드 |
|---|---|
| ![실제 영수증 첨부](docs/images/real-chat-attach-receipt.png) | ![실제 불량 사진 첨부](docs/images/real-chat-attach-defect.png) |

| 실제(재설계 전): 도면 읽기(연구소 에이전트) | |
|---|---|
| ![실제 도면 첨부](docs/images/real-chat-attach-drawing.png) | |

## 라이선스 표기

- Pretendard: SIL Open Font License 1.1
- MSW, openapi-typescript, openapi-fetch, React, React Router, Vite, Radix Primitives(`@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-popover`), cmdk: MIT
- Lucide 아이콘(`lucide-react`): ISC
