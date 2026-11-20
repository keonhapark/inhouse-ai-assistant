# inhouse-ai-assistant

부서별 사내 AI 에이전트와, 모든 LLM 호출이 지나가는 출구(gateway)입니다. 직원이 채팅으로 휴가 결재·회의실 예약·규정 질의를 맡기면, 에이전트가 사내 시스템(erp)의 도구를 부르기 전에 권한·위험 등급·신뢰 등급을 확인하고, 되돌릴 수 있게 실행합니다. 업종에 따라 조직·에이전트·문서를 "업종 팩"으로 갈아 끼웁니다.

> 지금은 1단계(휴가·회의실·규정 질의, 직원 채팅과 팀장 승인함)까지 구현했고, 2단계(재무·구매자재 에이전트, 비용 상한, 판 메타)를 진행하고 있습니다.

## 구조

```
web ──▶ gateway ──▶ agent ──MCP──▶ erp (Spring Boot)
          │  ▲          │
          │  └── LLM ◀──┤──▶ rag (규정 질의)
          ▼
   LiteLLM 출구 ─▶ 로컬(Ollama, Qwen3.5-9B) / 외부
```

| 경로 | 내용 |
|---|---|
| `contracts/` | 모듈 사이 계약: OpenAPI(erp, gateway, agent, rag), MCP 도구 목록, 위임 토큰, 감사·추적 이벤트, 평가 시나리오, 업종 팩 스키마. 상태 있는 가짜 erp와 행동 계약 시험 |
| `packs/manufacturing/` | 가상 중견 부품 제조사(약 60명) 팩: 조직도, 역할, 문서 접근 태그, 결재 양식, 에이전트 등록부, 문서 목록, 고정 데이터 |
| `erp/` | 사내 시스템: 조직, 결재 문서 엔진, 결재 대결, 근태, 회의실 |
| `gateway/` | 출구 프록시, 가림·기밀 판정·라우팅 정책, 위임 토큰, 화면용 API |
| `agent/` | 에이전트 등록부 런타임, 입구 라우터, MCP 서버, LangGraph 실행 |
| `rag/` | 규정·제한 문서 검색, 문서 ACL, 인용 대조 |
| `eval/` | 정상·우려 시나리오, 판정, 비교 조건 실행기, 보고서 |
| `web/` | 직원 채팅, 팀장 승인함 |
| `infra/` | compose |

## 설계 요점

- **쓰기는 모두 미리보기 → 실행 → 되돌리기.** erp 쓰기 API는 `?dryRun=true`, `Idempotency-Key`, `POST /actions/{id}/undo`를 갖고, 오류는 RFC 9457 problem+json입니다.
- **위임 토큰.** gateway가 대화마다 10분짜리 토큰을 발급하고, 범위는 "요청자 권한 ∩ 라우팅된 에이전트의 도구 scope"입니다. 최종 확인은 erp가 합니다. 결재 승인은 사람 화면 전용이라 에이전트 도구에 없습니다.
- **결재 대결.** 부재 시 대리 결재는 기간·범위(양식, 금액 한도) 안에서만 되고, 재위임과 자기 결재는 막습니다. 대리 결재 기록에 원 결재자와 위임 ID를 남기고 후열 알림을 보냅니다.
- **입구 라우터는 한 번만 넘깁니다.** 에이전트끼리 요청을 넘기지 않아 권한이 섞이지 않습니다.
- **업종을 모르는 코어.** 부서 이름 같은 업종 용어는 팩에만 두고, CI가 코어 경로를 검사합니다.

## 실행

필요한 것: Python 3.12와 [uv](https://docs.astral.sh/uv/), Docker, (모델을 쓸 때) Ollama

```bash
cp .env.example .env            # 값 채우기(POSTGRES_PASSWORD, ERP_JWT_SECRET 등)
bash scripts/dev-keys.sh        # 위임 토큰 개발 키(커밋하지 않음)

# 계약 시험(가짜 erp 행동 계약 포함)
cd contracts && uv sync && uv run pytest -q

# 팩·코어 검사
uv run python -m tools.check_packs
uv run python -m tools.check_core_terms

# 가짜 erp + PostgreSQL
cd .. && source scripts/env.sh 0
docker compose -f infra/compose.yaml --env-file .env up -d --wait
curl localhost:$PORT_FAKE_ERP/api/v1/health
```

가짜 erp는 고정 데이터의 직원 ID(`E0001`~`E0060`)와 `.env`의 `ERP_DEMO_PASSWORD`로 로그인합니다.

## 문서

- 커밋·브랜치·PR: `docs/conventions.md`
- 작업 방식(담당 경로, 이슈 루프): `docs/workflow.md`
- 포트: `docs/ports.md`
- 결정 기록: `docs/decisions/`
- 측정: `docs/measurements/`

## 데이터와 라이선스

- 회사·직원·회의실·잔여 연차는 지어낸 데이터입니다. [Faker](https://github.com/joke2k/faker)(MIT, `ko_KR`, 시드 20261120)로 만들었고 `packs/manufacturing/fixtures/generate.py`로 다시 만들 수 있습니다. 이메일은 `example.invalid` 도메인입니다.
- 공개 규정은 법제처 국가법령정보의 법령·행정규칙을 씁니다(저작권법 제7조, 보호받지 못하는 저작물). 목록은 `packs/manufacturing/docs.yaml`입니다.
- 로컬 모델: Qwen3.5-9B(Apache-2.0)
