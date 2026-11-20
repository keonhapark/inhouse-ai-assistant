# gateway

web이 부르는 유일한 서버입니다. 계약은 `contracts/openapi/gateway.yaml`(서버 기준 경로 `/api`)입니다.

지금 있는 것(1단계 #8):

- `GET /health`, `GET /api/health`
- `GET /api/.well-known/jwks.json`: 위임 토큰 검증용 공개 키. `kid`는 RFC 7638 지문입니다.
- `POST /api/auth/login`, `GET /api/me`: erp에 그대로 넘기고 상태 코드와 본문을 그대로 돌려줍니다.
- 위임 토큰 발급(`gateway/delegation.py`): 대화마다 ES256, 10분. 클레임은 `contracts/auth/delegation-token.schema.json`입니다.
  - `scopes`: 라우팅된 에이전트 도구(`agents.yaml`의 `tools`)의 `required_scope`에서 사람 화면 전용 scope를 뺀 것입니다.
    직원 JWT는 erp에서 모든 scope를 가지므로, 요청자 쪽 제한은 erp가 "토큰 주인의 권한 ∩ 토큰 scopes"로 다시 봅니다.
  - `doc_scopes`: erp `/me/access-tags` ∩ 에이전트 `doc_scopes`
  - 에이전트 `callable_by`에 맞지 않는 요청자는 403입니다.
- 토큰 위생: 모든 로그 레코드에서 JWT 모양과 `Bearer <값>`을 가립니다(`gateway/redact.py`). 발급 기록은 `jti`만 남깁니다.

## 실행

```bash
source ../scripts/env.sh 2
bash ../scripts/dev-keys.sh                       # 위임 토큰 키(커밋하지 않음)
(cd ../contracts && DELEGATION_TOKEN_PUBLIC_KEY=infra/dev-keys/delegation-es256.pub.pem \
  uv run uvicorn fakes.erp.app:app --port $PORT_FAKE_ERP) &
ERP_BASE_URL=http://localhost:$PORT_FAKE_ERP/api/v1 \
DELEGATION_TOKEN_PRIVATE_KEY=infra/dev-keys/delegation-es256.pem \
  uv run uvicorn --factory gateway.main:create_app --port $PORT_GATEWAY
```

환경 변수: `ERP_BASE_URL`, `PACK_DIR`(기본 `packs/manufacturing`), `CONTRACTS_DIR`(기본 `contracts`),
`DELEGATION_TOKEN_PRIVATE_KEY`(없으면 임시 키를 만들고 경고를 남깁니다). 상대 경로는 저장소 루트 기준입니다.

## 시험

```bash
uv sync && uv run pytest -q
```

시험은 `contracts/fakes/erp`를 프로세스 안에서 띄워 erp 자리에 둡니다. 발급한 토큰을 가짜 erp가 받아들이는지,
범위 밖 scope와 사람 화면 전용 API를 거절하는지도 봅니다.
