# gateway·erp 사용자 문구 점검

기준: `ux/copy-guide.md`. 코드는 읽기만 했고 실행한 것은 없습니다. 줄 번호는 모두 실제 파일에서 확인했습니다.

## 읽는 법과 범위

- 웹은 problem+json을 `title + " " + detail`로 이어 붙여 보여 줍니다(`web/src/api/client.ts:62-66`). 그래서 detail이 제목과 같거나 칸 코드로 시작하면 화면에 그대로 드러납니다.
- 웹은 401을 받으면 로그아웃하므로 `TokenService`의 401 detail은 직원 화면에 나오지 않는다고 보고 뺐습니다.
- 웹은 `errors[].message`를 보여 주지 않습니다. 영어 errors 메시지(`unknown`, `required`, `before start_date` 등)는 슬랙·에이전트가 보여 주는지 **확인 필요**입니다.
- 화면 코드가 만드는 값에만 걸리는 개발자용 오류(JSON 본문, cursor, since·until 오프셋, `X-Eval-*`, `agentId만 받습니다`, 첨부 `{kind…}`, 모델 별칭·필드, `response_format`, Idempotency-Key, scope·위임 토큰, `RFC 3339(오프셋 포함)`, `box`·`role`·`status`의 "~ 중 하나")는 직원이 입력으로 일으킬 수 없어 표에서 뺐습니다.
- egress(`/v1/*`) 오류는 에이전트가 받습니다. 직원 화면까지 가는지 확실하지 않은 줄은 근거 칸에 "확인 필요"를 붙였습니다.
- 감사 detail·알림(alerter)·로그는 운영자용이라 뺐습니다.

## gateway

| 파일:줄 | 지금 문구 | 고칠 문구 | 분류 | 근거 |
|---|---|---|---|---|
| gateway/gateway/chat.py:231 | 에이전트 응답 형식이 틀렸습니다 | AI 에이전트의 답을 읽지 못했습니다. 다시 보내 주세요. | 어색함 | 2.3 할 일 없음, 1.2 AI 에이전트. retryable=false라 다시 보내면 되는지 확인 필요 |
| gateway/gateway/chat.py:257 | 장치가 막았습니다 (blockedReason이 없을 때 기본값) | 회사 정책상 처리할 수 없는 요청입니다. 다른 방법으로 요청하거나 담당 부서에 문의하세요. | 용어 불일치 | 1.2 정책으로 막힘(직원 화면 "처리할 수 없는 요청"), 1.4 "장치"는 평가 용어 |
| gateway/gateway/chat.py:260 | 에이전트 실행이 실패했습니다 | AI 에이전트가 요청을 끝내지 못했습니다. 다시 보내 주세요. | 직역투 | 2.4 무생물 주어, 2.3 할 일 없음 |
| gateway/gateway/chat.py:264 | 에이전트가 답하지 않았습니다. 잠시 뒤 다시 보내 주세요 | AI 에이전트가 답하지 않았습니다. 잠시 뒤 다시 보내 주세요. | 용어 불일치 | 1.2 AI 에이전트, 문장 끝 마침표 |
| gateway/gateway/chat.py:276, 548 | 실행 승인을 기다리는 중입니다 | 실행 전 확인이 남아 있습니다. 확인 카드에서 먼저 결정하세요. | 용어 불일치 | 1.2 실행 전 확인, 2.3 할 일 없음 |
| gateway/gateway/chat.py:295 | 등록부에 없는 에이전트로 라우팅됐습니다 | 요청을 맡을 AI 에이전트를 찾지 못했습니다. AI 에이전트를 직접 골라 다시 보내세요. | 직역투 | 2.4 영어 그대로("라우팅")·피동, "등록부"는 내부 말, 2.3 |
| gateway/gateway/chat.py:304 | 직원이 골랐습니다 (route.reason) | 직접 골랐습니다 | 어색함 | 1.2 고른 이유 한 줄. 읽는 사람이 바로 그 직원인데 3인칭으로 씀 |
| gateway/gateway/chat.py:312 | {agent.name} 에이전트를 부를 수 없습니다 (blocked.reason) | {부서} 담당 AI는 쓸 권한이 없습니다. 다른 AI 에이전트를 고르세요. | 용어 불일치 | 1.2 부서별 AI("재무 담당 AI"), 1.2 정책으로 막힘(이유+다음 행동). 다음 행동 문구는 확인 필요 |
| gateway/gateway/chat.py:371 | 실행 승인이 없습니다 | 확인할 실행이 없습니다. | 용어 불일치 | 1.2 실행 전 확인. "승인"은 결재 용어(1.1)와 겹침 |
| gateway/gateway/chat.py:373 | 요청한 직원만 결정합니다 | 요청한 사람만 확인할 수 있습니다. | 어색함 | 2.3 규칙을 서술하는 말투 대신 무슨 일이 났는지 |
| gateway/gateway/chat.py:376 | 이미 결정했거나 기다리는 승인이 아닙니다 | 이미 처리한 실행 전 확인입니다. | 용어 불일치 | 1.2 실행 전 확인 |
| gateway/gateway/chat.py:378-379 | 승인 시간이 지났습니다 / 새 메시지를 보내면 이 실행은 거절로 처리하고 대화를 이어 갑니다 | 확인 시간이 지났습니다. / 이 실행은 하지 않았습니다. 다시 하려면 새 메시지를 보내세요. | 용어 불일치 | 1.2 "확인 시간 지남", 2.3 결과 먼저 |
| gateway/gateway/chat.py:405 | 에이전트가 이 승인을 기다리고 있지 않습니다 | 이미 끝난 실행 전 확인입니다. 새 메시지를 보내세요. | 용어 불일치 | 1.2, 2.3 할 일 없음 |
| gateway/gateway/chat.py:442 | 처리 중 오류가 났습니다 | 메시지를 처리하지 못했습니다. 다시 보내 주세요. | 어색함 | 2.3 모호한 말만으로 끝남 |
| gateway/gateway/chat.py:526; gateway/gateway/delegation.py:40 | 이 에이전트를 부를 수 없습니다 (detail: 에이전트 id) | 이 AI 에이전트를 쓸 권한이 없습니다. 다른 AI 에이전트를 고르세요. (detail은 코드 id 대신 표시 이름) | 용어 불일치 | 1.2 AI 에이전트, 1.4 코드 이름은 화면에 내지 않음, 2.3 |
| gateway/gateway/delegation.py:31, 38 | 없는 에이전트입니다 (detail: 에이전트 id) | 없는 AI 에이전트입니다. 목록을 새로 고친 뒤 다시 고르세요. | 용어 불일치 | 1.2, 1.4, 2.3 할 일 없음 |
| gateway/gateway/chat.py:62 | attachments는 1~{N}개 배열이어야 합니다 | 사진은 한 번에 {N}장까지 올릴 수 있습니다. | 직역투 | 2.4 영어 그대로(필드 이름), 1.2 "사진". 화면이 장수를 미리 막는지 확인 필요 |
| gateway/gateway/chat.py:545 | content는 1~{N}자 문자열이어야 합니다 | 메시지는 {N}자까지 보낼 수 있습니다. 줄여서 다시 보내세요. | 직역투 | 2.4 영어 그대로, 2.3 |
| gateway/gateway/chat.py:558 | decision은 approve·reject, comment는 200자 이하입니다 | 의견은 200자까지 쓸 수 있습니다. (decision 쪽은 개발자용으로 따로 나눔) | 직역투 | 2.4 영어 그대로, 1.1 의견 |
| gateway/gateway/vision.py:102-103 | 이미지는 {N}화소까지 받습니다 / {i}번째 이미지: {w}x{h} | 사진은 {N}화소까지 올릴 수 있습니다. 크기를 줄여 다시 올리세요. / {i}번째 사진({w}×{h}) | 용어 불일치 | 1.2 "사진"으로 통일, 2.3. 대화 첨부(chat.py:69)도 이 검사를 거쳐 직원에게 보임 |
| gateway/gateway/vision.py:109 | 이미지를 읽을 수 없습니다 / {i}번째 이미지 | 사진을 열 수 없습니다. 다른 사진을 올리세요. / {i}번째 사진 | 용어 불일치 | 1.2, 2.3 할 일 없음 |
| gateway/gateway/vision.py:125 | 이미지는 jpeg·png만 받습니다 / {i}번째 이미지: {mime} | JPG나 PNG 사진만 올릴 수 있습니다. / {i}번째 사진 | 용어 불일치 | 1.2, 2.4 MIME 코드값 노출 |
| gateway/gateway/vision.py:128-129, 135-136 | 이미지 한 장은 {N}MB까지 받습니다 / {i}번째 이미지: {bytes}B | 사진 한 장은 {N}MB까지 올릴 수 있습니다. 크기를 줄여 다시 올리세요. / {i}번째 사진(4.2MB) | 용어 불일치 | 1.2, 2.3 숫자 단위 |
| gateway/gateway/vision.py:138 | 이미지 내용이 선언한 형식과 맞지 않습니다 | 사진 파일이 손상됐거나 형식이 맞지 않습니다. JPG나 PNG로 다시 저장해 올리세요. | 직역투 | 2.4 "선언한"(declared) 직역 |
| gateway/gateway/vision.py:122, 133 | 이미지는 base64 data URL만 받습니다 / 이미지 base64가 올바르지 않습니다 | 사진을 읽지 못했습니다. 다시 올리세요. | 직역투 | 2.4 영어 그대로, 2.3. 화면이 인코딩하므로 직원에게 닿는 경우는 확인 필요 |
| gateway/gateway/slack_login.py:69 | 슬랙 로그인 토큰으로는 부를 수 없는 기능입니다 | 슬랙에서는 쓸 수 없는 기능입니다. 웹 화면에서 하세요. | 직역투 | 2.4 영어 그대로("토큰"), 2.3. erp 쪽 같은 개념 문구와도 셋이 다름(erp 표 참고) |
| gateway/gateway/slack_login.py:160, 171 | 이 슬랙 사용자와 연결된 직원이 없습니다 | 이 슬랙 계정과 연결된 직원 정보가 없습니다. 관리자에게 계정 연결을 요청하세요. | 어색함 | 2.3 할 일 없음. 요청할 곳은 확인 필요 |
| gateway/gateway/slack_login.py:166, 176 | erp 서비스 로그인에 실패했습니다 (detail: 서비스 비밀값이 설정되지 않음 / erp {status}) | 사내 시스템에 로그인하지 못했습니다. 잠시 뒤 다시 시도해 주세요. (detail은 운영 기록에만) | 직역투 | 2.4 무생물 주어, 영어 시스템 이름, 2.3. 슬랙 브리지가 이 문구를 직원에게 보이는지 확인 필요 |
| gateway/gateway/erp_client.py:28, 30, 46 | erp가 제때 답하지 않았습니다 / erp에 연결하지 못했습니다 / erp 오류 | 사내 시스템이 답하지 않습니다. 잠시 뒤 다시 시도해 주세요. / 사내 시스템에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요. / 사내 시스템 오류 | 용어 불일치 | 직원에게 erp를 부르는 말이 용어집에 없음(아래 목록), 2.3 할 일 없음. relay로 결재 화면 등에 그대로 보임 |
| gateway/gateway/audit_query.py:106; gateway/gateway/ops.py:114; erp/.../audit/AuditController.java:38 | 감사 조회 역할만 봅니다 | 감사 기록은 감사 조회 역할이 있어야 볼 수 있습니다. | 어색함 | 2.3 규칙 서술 대신 무슨 일인지. 관리 화면 |
| gateway/gateway/ops.py:240 | since가 until보다 늦습니다 | 시작 시각이 끝 시각보다 늦습니다. 기간을 다시 고르세요. | 직역투 | 2.4 영어 그대로(파라미터 이름), 2.3. 관리 화면 기간 선택에서 나는지 확인 필요 |
| gateway/gateway/egress.py:201 | 에이전트 {id}는 외부 모델을 쓸 수 없습니다(local_only) | {표시 이름} 에이전트는 외부 모델을 쓰지 않도록 설정돼 있습니다. | 직역투 | 2.4 코드값 그대로(local_only), 1.4 코드 이름은 뒤에 작게. 함수 설명에 "사용자에게 보여 줄 이유"라고 돼 있으나 실제 도달 화면은 확인 필요 |
| gateway/gateway/egress.py:544 | 사내 기밀이 들어 있어 보낼 수 없습니다 | 사내 기밀 정보가 있어 외부 AI로 보내지 않았습니다. 기밀 내용을 빼고 다시 보내 주세요. | 어색함 | 1.2 외부 AI 사용, 2.3 할 일 없음. 에이전트를 거쳐 직원에게 닿는지 확인 필요 |
| gateway/gateway/registry.py:52 | 팩 단위 외부 LLM 금지(pack.yaml model_policy_override) (GET /agents modelPolicy.reason) | 회사 설정으로 외부 모델을 쓰지 않습니다. | 직역투 | 2.4 영어 그대로(파일·키 이름), 1.2 외부 모델, 1.4. AI 에이전트 화면에 나오는지 확인 필요 |

## erp

| 파일:줄 | 지금 문구 | 고칠 문구 | 분류 | 근거 |
|---|---|---|---|---|
| erp/.../common/Problems.java:18 | 인증이 필요합니다 | 로그인이 필요합니다. | 용어 불일치 | 1.3 로그인. gateway relay.py:35는 이미 "로그인이 필요합니다" |
| erp/.../common/ProblemHandler.java:70 (Problems.java TITLES에 `internal` 없음) | title "internal" / detail "서버 오류" | 서버에서 요청을 처리하지 못했습니다. / 잠시 뒤 다시 시도해 주세요. | 직역투 | 2.4 영어 그대로(코드가 제목으로 나감), 2.3 모호한 말 |
| erp/.../common/Problems.java:22; erp/.../auth/ScopeGuard.java:30 | 서비스 로그인 토큰으로는 부를 수 없는 사람 화면 전용 기능입니다 / 서비스 로그인(슬랙) 토큰으로 부를 수 없는 기능입니다 | 슬랙에서는 쓸 수 없는 기능입니다. 웹 화면에서 하세요. | 직역투 | 2.4 영어 그대로, 2.3. gateway slack_login.py:69와 같은 말로 |
| erp/.../common/Problems.java:28; erp/.../approval/ApprovalService.java:126 | 문서가 그사이 바뀌었습니다 / 현재 version은 {n}입니다 | 그사이 다른 사람이 먼저 바꿨습니다. 새로 고친 뒤 다시 확인하세요. (detail의 version 숫자는 뺌) | 어색함 | 2.3 할 일 없음, 2.4 영어 그대로. 예약·티켓·견적에도 쓰여 "문서"가 맞지 않음 |
| erp/.../sales/QuoteService.java:168; erp/.../quality/DefectReportService.java:109; erp/.../ticket/TicketService.java:148 | 그사이 견적이 바뀌었습니다 / 그사이 보고서가 바뀌었습니다 / 그사이 티켓이 바뀌었습니다 | 그사이 견적이 바뀌었습니다. 새로 고친 뒤 다시 시도하세요. | 어색함 | 2.3 할 일 없음. 제목과 이어 붙으면 같은 말이 두 번 나옴 |
| erp/.../write/WriteExecutor.java:205 | 그사이 다른 요청이 같은 리소스를 바꿨습니다 | 그사이 다른 사람이 먼저 바꿨습니다. 새로 고친 뒤 다시 확인하세요. | 직역투 | 2.4 영어 그대로("리소스")·무생물 주어, 2.3 |
| erp/.../write/WriteExecutor.java:208 | 같은 상태를 바꾸는 요청이 겹쳤습니다 | 같은 일이 동시에 들어왔습니다. 새로 고친 뒤 다시 확인하세요. | 직역투 | 2.4 무생물 주어, 2.3 |
| erp/.../common/Problems.java:29; erp/.../approval/ApprovalService.java:116 | 지금 상태에서는 할 수 없습니다 / 문서 상태가 {in_progress 등}입니다 | 이미 결재가 끝난 문서입니다({승인·반려·회수}). | 용어 불일치 | 1.1 상태는 표시 이름(진행 중 등), 코드 값은 화면에 내지 않음 |
| erp/.../approval/ApprovalService.java:172 | 문서 상태가 {status}라 회수할 수 없습니다 | {승인·반려·회수}된 문서라 회수할 수 없습니다. | 용어 불일치 | 1.1 코드 값 노출 |
| erp/.../common/Problems.java:30; erp/.../delegation/DelegationAuthority.java:54 | 현재 결재 차례가 아닙니다 | 지금 결재 대기 중인 문서가 아닙니다. 결재 대기 목록을 새로 고치세요. | 용어 불일치 | 1.1 "결재 차례"는 "결재 대기"로, 2.3. 문장 다듬기는 확인 필요 |
| erp/.../common/Problems.java:31; erp/.../approval/ApprovalService.java:120 | 본인이 올린 문서는 결재할 수 없습니다 | 본인이 기안한 문서는 결재할 수 없습니다. | 용어 불일치 | 1.1 기안. 제목과 detail이 같아 화면에 두 번 나옴 |
| erp/.../common/Problems.java:32-34 | 유효한 대결 위임이 없습니다 / 대결 위임 기간이 아닙니다 / 대결 위임 범위 밖입니다 | 이 문서를 대결할 수 있는 대결 지정이 없습니다. / 대결 기간이 아닙니다. / 대결 범위 밖의 문서입니다. | 용어 불일치 | 1.1 "위임"은 쓰지 않음 |
| erp/.../common/Problems.java:35; erp/.../delegation/DelegationService.java:128 | 해지된 대결 위임입니다 / 이미 해지된 위임입니다 | 해제된 대결입니다. / 이미 해제된 대결입니다. | 용어 불일치 | 1.1 해지 대신 대결 해제 |
| erp/.../common/Problems.java:36; erp/.../delegation/DelegationAuthority.java:51 | 재위임은 허용하지 않습니다 / 재위임은 따라가지 않습니다 | 대결자는 맡은 결재를 다른 사람에게 다시 맡길 수 없습니다. / 대결자가 다시 맡긴 결재는 할 수 없습니다. | 용어 불일치 | 1.1 위임. "따라가지 않습니다"는 내부 구현 말 |
| erp/.../common/Problems.java:37; erp/.../delegation/DelegationService.java:85 | 본인에게 위임할 수 없습니다 | 본인을 대결자로 지정할 수 없습니다. 다른 사람을 고르세요. | 용어 불일치 | 1.1 대결자·대결 지정, 2.3. 제목과 detail이 같아 두 번 나옴 |
| erp/.../common/Problems.java:38; erp/.../delegation/DelegationService.java:96 | 위임 기간이 너무 깁니다 / 최대 {n}일입니다 | 대결 기간이 너무 깁니다. / 대결 기간은 최대 {n}일입니다. 기간을 줄이세요. | 용어 불일치 | 1.1, 2.3 할 일 없음 |
| erp/.../common/Problems.java:39; erp/.../delegation/DelegationService.java:76 | 대결을 등록할 권한이 없습니다 / 위임자 본인이나 등록 권한이 있는 역할만 등록합니다 | 대결을 지정할 권한이 없습니다. / 본인 결재의 대결만 지정할 수 있습니다. 다른 사람의 대결은 인사 담당에게 요청하세요. | 용어 불일치 | 1.1 대결 지정, "위임자"(용어집 없음), 2.3. 역할 이름은 확인 필요 |
| erp/.../common/Problems.java:40; erp/.../leave/LeaveService.java:77-79 | 연차 잔여가 부족합니다 / 필요 {n}일, 남은 {m}일 | 남은 연차가 부족합니다. / 이 신청에는 {n}일이 필요한데 남은 연차는 {m}일입니다. 기간을 줄이세요. | 어색함 | 2.3 한 문장·할 일 없음 |
| erp/.../common/Problems.java:41; erp/.../room/RoomService.java:192 | 같은 시간에 예약이 있습니다 / {회의실}에 겹치는 예약이 있습니다 | 이미 예약된 시간입니다. / {회의실}은 그 시간에 이미 예약돼 있습니다. 다른 시간을 고르세요. | 어색함 | 2.3 예문 그대로. 제목·detail이 같은 말을 반복 |
| erp/.../common/Problems.java:42; erp/.../write/ActionController.java:73 | 되돌릴 수 없는 행동입니다 / {operation}은 되돌릴 수 없습니다 | 실행 취소할 수 없는 작업입니다. / {작업 표시 이름}은 실행 취소할 수 없습니다. | 용어 불일치 | 1.2 실행 취소, 1.4 operationId 코드 노출 |
| erp/.../common/Problems.java:43; erp/.../write/ActionController.java:69 | 이미 되돌린 행동입니다 | 이미 실행 취소한 작업입니다. | 용어 불일치 | 1.2. 제목과 detail이 같아 두 번 나옴 |
| erp/.../common/Problems.java:44 | 상태가 바뀌어 되돌릴 수 없습니다 | 그사이 상태가 바뀌어 실행 취소할 수 없습니다. | 용어 불일치 | 1.2 실행 취소 |
| erp/.../write/ActionController.java:84 | 행동이 없습니다 | 실행 기록이 없습니다. | 직역투 | 2.4 action 직역. 대응 말은 용어집에 없음(아래 목록) |
| erp/.../approval/ApprovalService.java:87, 147 | 결재 차례: {제목} (알림) | 결재 대기: {제목} | 용어 불일치 | 1.1 "결재 차례"는 "결재 대기" |
| erp/.../approval/ApprovalService.java:134-135 | 대결 처리(후열): {이름}님이 '{제목}'을 승인했습니다 | 후열(대결 내역 확인): {이름}님이 대결로 '{제목}' 문서를 승인했습니다. | 용어 불일치 | 1.1 후열은 한 번 풀어 씀. 조사 "을" 고정은 받침 없는 제목에서 틀림 |
| erp/.../approval/ApprovalService.java:151-152 | '{제목}'을 승인합니다(대결: {이름} 대신) | '{제목}' 문서를 승인합니다({이름}님 대결). | 어색함 | 2.4 괄호 안 구어, 조사 고정 |
| erp/.../approval/ApprovalService.java:175; erp/.../ticket/TicketService.java:95; erp/.../room/RoomService.java:76 | '{제목}'을 회수합니다 / IT 티켓 '{제목}'을 올립니다 / {회의실}을 {때}에 예약합니다 | '{제목}' 문서를 회수합니다. / IT 티켓 '{제목}'을 올립니다(을/를 자동 선택) / {회의실}을(를) 받침에 맞게: "회의실 C를 11월 21일 14:00~15:00에 예약합니다" | 어색함 | 2.3. 이름 뒤 조사를 "을"로 고정해 "회의실 C을"처럼 틀림 |
| erp/.../approval/ApprovalService.java:98 | 이미 결재가 진행됐거나 끝난 문서입니다 | 이미 결재가 시작돼 실행 취소할 수 없습니다. 기안함에서 문서 상태를 확인하세요. | 어색함 | 2.3 할 일 없음 |
| erp/.../approval/ApprovalService.java:103 | 결재 요청을 되돌렸습니다(회수) | 상신을 취소하고 문서를 회수했습니다. | 용어 불일치 | 1.1 상신, 1.2 실행 취소 |
| erp/.../approval/ApprovalService.java:163 | 요청자 본인만 회수합니다 | 기안자만 회수할 수 있습니다. | 용어 불일치 | 1.1 기안 |
| erp/.../approval/ApprovalLineResolver.java:48 | 맞는 결재선 규칙이 없습니다 | 이 양식에 맞는 결재선이 없어 상신할 수 없습니다. 관리자에게 문의하세요. | 어색함 | 2.3 할 일 없음. 문의처는 확인 필요 |
| erp/.../approval/FormValidator.java:43; erp/.../common/Bodies.java:29 | detail = 양식 입력이 올바르지 않습니다 / 입력이 올바르지 않습니다 (제목과 같음) | detail은 비우거나 첫 오류 칸을 문장으로: "금액을 확인하세요." | 어색함 | 2.3 할 일 없음. title+detail로 같은 말이 두 번 나옴 |
| erp/.../approval/FormValidator.java:59-60 | {amountField}가 {a} × {b}({want})와 다릅니다 | 금액이 수량 × 단가({want}원)와 다릅니다. 금액을 다시 확인하세요. | 직역투 | 2.4 칸 코드 그대로, 2.3 숫자 단위. 칸 이름은 팩 표시 이름으로 |
| erp/.../leave/LeaveService.java:52 | end_date가 start_date보다 앞입니다 | 끝나는 날이 시작일보다 앞입니다. 날짜를 다시 고르세요. | 직역투 | 2.4 영어 그대로, 1.1 코드 값 |
| erp/.../leave/LeaveService.java:56 | 반차는 하루만 씁니다 | 반차는 하루만 신청할 수 있습니다. 시작일과 끝나는 날을 같게 고르세요. | 어색함 | 2.3 |
| erp/.../leave/LeaveService.java:119 | {field}: 날짜 형식이 아닙니다 | {시작일·끝나는 날}을 날짜로 입력하세요. 예: 2026-11-21 | 직역투 | 2.4 칸 코드(start_date) 노출 |
| erp/.../common/ApiException.java:42 (validation 공통) | "{field}: {message}" 예: "endsAt: 시작이 끝보다 앞이어야 합니다", "validUntil: 오늘이나 그 뒤 날짜" | detail은 문장만 두고 칸 코드는 errors[].field에만 | 직역투 | 2.4 영어 그대로, 1.4 코드 이름 노출. 모든 ApiException.validation detail이 이 꼴로 화면에 나감 |
| erp/.../delegation/DelegationService.java:89; erp/.../room/RoomService.java:143, 170 | 시작이 끝보다 앞이어야 합니다 | 끝나는 시각은 시작 시각보다 늦어야 합니다. | 어색함 | 2.3 |
| erp/.../delegation/DelegationService.java:92 | 끝이 이미 지났습니다 | 끝나는 시각이 이미 지났습니다. 지금 이후로 고르세요. | 어색함 | 2.3 할 일 없음 |
| erp/.../delegation/DelegationService.java:108 | {이름}님의 결재 대결을 맡았습니다({기간}) (알림) | {이름}님의 대결자가 됐습니다({기간}). | 용어 불일치 | 1.1 대결자 |
| erp/.../delegation/DelegationService.java:111-112 | {A}님이 {B}님을 내 결재 대결로 등록했습니다({기간}) (알림) | {A}님이 {B}님을 내 대결자로 지정했습니다({기간}). | 용어 불일치 | 1.1 대결자·대결 지정 |
| erp/.../delegation/DelegationService.java:115-116 | {X}님의 결재를 {Y}님이 대신합니다({기간}, 양식 {formId 목록}) | {Y}님을 {X}님의 대결자로 지정합니다({기간}, 양식: {양식 표시 이름 또는 "모든 양식"}). | 용어 불일치 | 1.1 대결 지정, 1.1 양식 이름은 팩 표시 이름(지금은 id·`*`가 그대로 나감) |
| erp/.../delegation/DelegationService.java:125 | 이 위임으로 이미 결재한 문서가 있습니다 | 이 대결로 이미 결재한 문서가 있어 실행 취소할 수 없습니다. 대결 해제를 쓰세요. | 용어 불일치 | 1.1, 2.3 할 일 없음 |
| erp/.../delegation/DelegationService.java:133 | 대결 위임 등록을 되돌렸습니다 | 대결 지정을 취소했습니다. | 용어 불일치 | 1.1, 1.2 |
| erp/.../delegation/DelegationService.java:142, 183 | 위임이 없습니다 | 대결 지정이 없습니다. | 용어 불일치 | 1.1 |
| erp/.../delegation/DelegationService.java:144 | 위임자 본인이나 인사 담당만 해지합니다 | 본인이나 인사 담당만 대결을 해제할 수 있습니다. | 용어 불일치 | 1.1 대결 해제 |
| erp/.../delegation/DelegationService.java:149 | 이미 {revoked·expired}입니다 | 이미 해제된 대결입니다. / 이미 끝난 대결입니다. | 용어 불일치 | 1.1 코드 값 노출 |
| erp/.../delegation/DelegationService.java:154 | 대결 위임을 해지합니다 | 대결을 해제합니다. | 용어 불일치 | 1.1 |
| erp/.../delegation/DelegationService.java:44; erp/.../room/RoomService.java:41 (DelegationService 108·112·115, RoomService 76·93에서 씀) | 2026-11-21 14:00 ~ 2026-11-22 18:00 (yyyy-MM-dd HH:mm) | 11월 21일 14:00 ~ 11월 22일 18:00 | 어색함 | 2.3 날짜 표기 |
| erp/.../room/RoomService.java:85 | 예약자 본인만 취소합니다 | 예약한 사람만 취소할 수 있습니다. | 어색함 | 2.3 |
| erp/.../room/RoomService.java:104, 120 | 예약 시작 시각이 지났습니다 | 이미 시작한 예약이라 실행 취소할 수 없습니다. | 어색함 | 2.3 결과(무엇을 못 하는지)가 빠짐 |
| erp/.../room/RoomService.java:109 | 회의실 예약을 되돌렸습니다(취소) | 회의실 예약을 취소했습니다. | 용어 불일치 | 1.2 |
| erp/.../room/RoomService.java:117 | 예약이 취소 상태가 아닙니다 | 이미 다시 잡힌 예약입니다. | 어색함 | 2.3. 실제 경우(취소의 실행 취소를 두 번)는 확인 필요 |
| erp/.../room/RoomService.java:124, 131 | 그 시간에 다른 예약이 들어왔습니다 | 그사이 같은 시간에 다른 예약이 잡혀 되살릴 수 없습니다. 다른 시간으로 새로 예약하세요. | 어색함 | 2.3 할 일 없음 |
| erp/.../room/RoomService.java:134 | 예약 취소를 되돌렸습니다 | 취소한 예약을 되살렸습니다. | 용어 불일치 | 1.2 "되돌리기" 쓰지 않음. "취소의 실행 취소" 표현은 확인 필요 |
| erp/.../room/RoomService.java:146, 148, 150, 152 | 30분 단위로 예약합니다 / 같은 날 안에서 예약합니다 / 최대 4시간입니다 / 지난 시각은 예약할 수 없습니다 | 30분 단위로만 예약할 수 있습니다. / 하루 안에서만 예약할 수 있습니다. / 한 번에 4시간까지 예약할 수 있습니다. / 지난 시각은 예약할 수 없습니다. 지금 이후 시각을 고르세요. | 어색함 | 2.3 |
| erp/.../sales/QuoteService.java:102, 117, 165; erp/.../quality/DefectReportService.java:70, 106; erp/.../ticket/TicketService.java:71, 145, 166; erp/.../delegation/DelegationService.java:167 | 영업 역할만 전체를 봅니다 / 영업 역할만 견적을 씁니다 / 영업 역할만 발행합니다 / 품질 확인 역할만 전체를 봅니다 / 품질 확인 역할만 확정합니다 / 티켓 담당만 전체를 봅니다 / 티켓 담당만 상태를 바꿉니다 / 티켓 담당만 상태 변경을 되돌립니다 / 인사 담당만 전체를 봅니다 | "~은 ~만 할 수 있습니다" 꼴: "견적 발행은 영업 담당만 할 수 있습니다.", "전체 목록은 품질 담당만 볼 수 있습니다." | 어색함 | 2.3 규칙 서술 대신 무슨 일인지. 역할 이름("역할"/"담당")도 섞임(아래 목록) |
| erp/.../sales/QuoteService.java:138 | 금액이 너무 큽니다 | 견적 금액이 한도({n}원)를 넘습니다. 수량이나 품목을 줄이세요. | 어색함 | 2.3 할 일 없음. 한도 값은 확인 필요 |
| erp/.../sales/QuoteService.java:143 | 오늘이나 그 뒤 날짜 | 유효 기한은 오늘 이후 날짜로 고르세요. | 어색함 | 2.1 문장으로 끝나지 않음 |
| erp/.../sales/QuoteService.java:156; erp/.../quality/DefectReportService.java:97 | 그사이 발행되었습니다 / 그사이 확정되었습니다 | 그사이 견적이 발행돼 실행 취소할 수 없습니다. / 그사이 보고서가 확정돼 실행 취소할 수 없습니다. | 직역투 | 2.4 주어 없는 피동, 2.3 |
| erp/.../sales/QuoteService.java:158; erp/.../quality/DefectReportService.java:99; erp/.../ticket/TicketService.java:105, 173 | 견적 초안을 되돌렸습니다(취소) / 불량 보고서 초안을 되돌렸습니다(취소) / IT 티켓 작성을 되돌렸습니다(취소) / IT 티켓 상태 변경을 되돌렸습니다 | 견적 초안을 취소했습니다. / 불량 보고서 초안을 취소했습니다. / IT 티켓을 취소했습니다. / IT 티켓 상태를 원래대로 돌렸습니다. | 용어 불일치 | 1.2 "되돌리기" 대신 실행 취소·취소 |
| erp/.../sales/QuoteService.java:171; erp/.../quality/DefectReportService.java:112; erp/.../ticket/TicketService.java:112, 129, 151, 154 | {status} 견적은 발행할 수 없습니다 / {status} 보고서는 확정할 수 없습니다 / {status} 티켓에는 댓글을 달 수 없습니다 / 티켓이 {status}입니다 / {from}에서 {to}로 바꿀 수 없습니다 / IT 티켓 '{제목}'을 {status}로 바꿉니다 | 상태 코드 대신 표시 이름: "이미 발행한 견적입니다.", "종료된 티켓에는 댓글을 달 수 없습니다.", "IT 티켓 '{제목}'을 처리 중으로 바꿉니다." | 용어 불일치 | 1.1 코드 값은 화면에 내지 않음. 견적·보고서·티켓 상태 표시 이름이 용어집에 없음 |
| erp/.../sales/QuoteService.java:174 | 유효 기한이 지났습니다 | 유효 기한이 지나 발행할 수 없습니다. 유효 기한을 고쳐 새 견적을 쓰세요. | 어색함 | 2.3 할 일 없음. 다음 행동은 확인 필요 |
| erp/.../ticket/TicketService.java:103 | 그사이 댓글이 달렸거나 처리가 시작됐습니다 | 그사이 댓글이 달렸거나 처리가 시작돼 실행 취소할 수 없습니다. | 어색함 | 2.3 결과가 빠짐 |
| erp/.../org/OrgService.java:57 | 직원 {id}가 없습니다 | 없는 직원입니다(사번 {사번}). | 어색함 | 1.4 이름(사번), 조사 "가" 고정("emp-2001가") |

`erp/...`는 `erp/src/main/java/io/inhouse/erp`의 줄임입니다.

### 함께 볼 점(행으로 세지 않음)

- `WriteOutcome.summary`는 미리보기(`WriteExecutor.java:79`)와 실행 결과(`WriteExecutor.java:155`)에 같은 문자열을 씁니다. 그래서 실행이 끝난 뒤에도 "결재를 올립니다", "회수합니다"처럼 현재형이 남습니다. 2.3은 결과를 "~했습니다"로 쓰므로 미리보기용과 결과용을 나눠야 합니다. 반면 실행 취소 summary는 "~되돌렸습니다"처럼 과거형이라 둘이 섞여 있습니다.
- erp 제목(`Problems.java`)은 "가짜 erp와 같은 문구"라고 적혀 있습니다. 제목을 바꾸면 웹 모의 서버도 함께 바꿔야 합니다.
- 제목과 detail 모두 마침표가 없습니다. 웹이 공백 하나로 이어 붙여 "입력이 올바르지 않습니다 endsAt: …"처럼 한 문장으로 붙어 보입니다. 문구에 마침표를 넣거나 웹이 줄을 나눠야 합니다(웹 쪽 일).

## contracts/openapi

- `erp.yaml`·`gateway.yaml`에는 직원에게 보이는 고정 한국어 문구(enum 표시 이름 등)가 없습니다. enum은 모두 코드 값(`in_progress`, `policy_denied`, `local_only` 등)입니다.
- `erp.yaml` ProblemCode에는 `internal`이 있지만 erp `Problems.java` TITLES에는 없습니다. 위 `ProblemHandler.java:70` 행은 erp에서 고치면 되고 계약 변경은 필요 없습니다.
- 상태·차단 코드의 표시 이름을 계약에 두려면(`x-display-name` 같은 확장) 계약 변경이라 **따로 이슈가 필요합니다.** 지금은 웹이 각자 붙이고 있어, erp가 문장에 상태 코드를 넣는 위 행들과 이름이 어긋날 수 있습니다.

## 분류별 개수

| 분류 | gateway | erp | 합계 |
|---|---|---|---|
| 직역투 | 12 | 10 | 22 |
| AI 말투 | 0 | 0 | 0 |
| 용어 불일치 | 15 | 31 | 46 |
| 어색함 | 7 | 24 | 31 |
| 합계 | 34 | 65 | 99 |

AI 말투가 0인 것은 gateway·erp가 고정 문구만 두고 모델 문장을 만들지 않기 때문입니다.

## 무슨 일이 났는지만 있고 할 일이 없는 오류

표에서 2.3 "할 일 없음"에 해당하는 오류 행: **39개**(gateway 18, erp 21).

- gateway: chat.py 231, 257, 260, 276·548, 295, 312, 405, 442, 526·delegation 40, delegation 31·38, vision 109, vision 122·133, slack_login 69, 160·171, 166·176, erp_client 28·30·46, ops 240, egress 544
- erp: ProblemHandler 70, Problems 22·ScopeGuard 30, Problems 28·ApprovalService 126, Quote 168 외 2, WriteExecutor 205, 208, Problems 30, Problems 37, Problems 38, Problems 39, Problems 40, Problems 41, ApprovalService 98, ApprovalLineResolver 48, FormValidator 43·Bodies 29, DelegationService 92, 125, RoomService 124·131, RoomService 152, QuoteService 138, 174

## 용어집에 없는데 정해야 할 말

1. **erp를 직원에게 부르는 이름**: "사내 시스템", "ERP", "그룹웨어" 중 하나. gateway 오류에 "erp"가 소문자로 그대로 나갑니다.
2. **대결을 맡기는 사람**: 지금 "위임자". 용어집은 맡는 사람(대결자)만 정했습니다. 1.1 후열 행에 나오는 "원 결재자"로 할지 정해야 합니다.
3. **대결을 대신 등록한 사람**(인사 담당이 남의 대결을 지정할 때): 지금 "등록 권한이 있는 역할".
4. **실행 전 확인에서 실행하지 않기로 한 결정**: 지금 "거절"(reject). 버튼은 "취소"인데 결과 이름과 안내 문장("거절로 처리")을 정해야 합니다.
5. **실행 전 확인에서 결정하는 동작**: 지금 "결정", "승인". "승인"은 결재 용어와 겹칩니다.
6. **실행한 일 한 건(action)**: 지금 "행동". 실행 기록·작업 중 무엇으로 쓸지 정해야 합니다.
7. **취소의 실행 취소**(취소한 예약 되살리기, 해제의 실행 취소): "취소를 취소했습니다"가 되지 않을 말.
8. **역할 이름**: "영업 역할"/"영업 담당", "품질 확인 역할", "티켓 담당", "인사 담당", "감사 조회 역할"이 섞여 있습니다. "○○ 담당"으로 맞출지 정해야 합니다.
9. **결재 문서 밖 상태 표시 이름**: 견적(draft·issued·cancelled), 불량 보고서(draft·confirmed·cancelled), IT 티켓(open 등), 대결(scheduled·active·expired·revoked), 회의실 예약(confirmed·cancelled). 1.1에는 결재 문서 상태만 있습니다.
10. **휴가 날짜 칸 이름**: 시작일 / 끝나는 날(종료일).
11. **문의처 안내**: "관리자", "담당 부서", "인사 담당" 중 무엇으로 다음 행동을 안내할지. 슬랙 계정 연결, 결재선 없음, 에이전트 권한 없음에 필요합니다.
12. **슬랙 계정 연결**: 지금 "슬랙 사용자 매핑", "연결된 직원".
13. **초안**(견적 초안, 불량 보고서 초안): 결재의 "기안"과 구분해 그대로 둘지.
14. **사진 크기 표기**: "화소", "MB"를 직원 화면에 그대로 쓸지.
