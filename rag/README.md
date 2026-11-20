# rag

규정·안내 문서 검색과 근거 붙은 답을 맡는 모듈입니다. 계약은 `contracts/openapi/rag.yaml`입니다.

## 문서 본문

문서 목록·ACL 태그·신뢰 등급은 팩 `packs/<업종>/docs.yaml`이 기준이고, 본문은 이 모듈이 만듭니다.

| 출처 유형 | 본문 | 만드는 방법 |
|---|---|---|
| `law_open_api` | `corpus/law/<문서 ID>.json` 고정본 | `uv run --group fetch python -m rag.lawfetch` |
| `generated` | `templates/<문서 ID>.md` + 팩 값 | 불러올 때 채움(`rag/generate.py`) |

### 공개 규정 고정본

국가법령정보센터(https://www.law.go.kr)에서 받은 판을 그대로 둡니다. 검색과 인용 대조는 이 고정본만 봅니다.

| 문서 ID | 규정 | 시행일 | 범위 |
|---|---|---|---|
| `law-civil-service-duty` | 국가공무원 복무규정(대통령령 제36728호) | 2026-10-02 | 본칙 전체(부칙·별표 제외) |
| `law-travel-expense` | 공무원 여비 규정(대통령령 제36728호) | 2026-10-02 | 본칙 전체(부칙·별표 제외) |
| `admrul-duty-discipline` | 국가공무원 복무·징계 관련 예규(인사혁신처예규 제225호) | 2026-10-01 | 첨부 PDF 제8장 휴가 |

- 조회일은 2026-11-20이고, 각 파일의 `source`에 출처 주소, 조회 시각, 받은 원문의 SHA-256이 있습니다.
- 라이선스: 법령과 행정규칙(훈령·예규)은 저작권법 제7조(보호받지 못하는 저작물) 제1호·제2호에 해당합니다. 국가법령정보센터 Open API 이용 약관 원문은 아직 확인하지 못했고, 1단계는 인증값(OC) 없이 웹 화면이 쓰는 본문 주소에서 받았습니다.
- 법령은 조문 단위로 나눕니다. 조문 속 표는 그림의 대체 글자를 행마다 남기고, 삭제된 조문과 개정 표시는 뺍니다.
- 예규는 360쪽 PDF라 휴가 장만 씁니다. 목차에서 장의 쪽 범위를 찾고, "1."과 "가." 두 단계로 나눕니다. PDF에서 뽑은 글자라 표 모양은 남지 않습니다.
- 고용노동부 표준취업규칙은 라이선스를 확인하기 전이라 쓰지 않습니다.

### 생성 문서

회의실 안내, 휴가 지침, 결재·대결 규정, 인사 공지(제한), 급여 기준(제한) 5건입니다. 템플릿에는 회사·부서 이름을 쓰지 않고 `{{ company }}`, `{{ role_unit:hr_staff }}` 같은 자리표시자를 써서 팩 값으로 채웁니다. 자리표시자 목록은 `rag/generate.py` 첫머리에 있습니다. 내용은 모두 지어낸 것입니다.

## 검색(`POST /search`)

1. 문서를 조문 단위 청크로 나눕니다(`rag/chunk.py`). 700자를 넘는 조문은 항(①) 경계, 예규 절은 항목((1)) 경계에서 나누고 `article`에 범위를 붙입니다(예: "제20조(특별휴가) 제4항~제9항").
2. 위임 토큰(`X-Delegation-Token`, ES256)을 확인합니다. 서명, `iss: gateway`, `aud`에 rag, 만료를 봅니다. 틀리면 401 `application/problem+json`입니다.
3. 토큰 `doc_scopes`와 문서 ACL 태그가 겹치는 청크만 남긴 뒤 순위를 매깁니다. 권한 밖 청크는 점수 계산에도 넣지 않고, BM25 문서 빈도도 허용된 청크만으로 셉니다.
4. 방법
   - `bm25`: 한글 음절 2-gram 토큰의 Okapi BM25(k1 1.2, b 0.75). 기준선 비교용입니다.
   - `vector`: 임베딩 코사인 유사도
   - `hybrid`(기본): 두 순위를 Reciprocal Rank Fusion(k=60)으로 합칩니다.
5. 결과마다 문서 ID, 제목, 조문 표시, 본문, 점수, 신뢰 등급(`trusted`/`untrusted`)을 돌려줍니다.

임베딩은 gateway의 OpenAI 호환 `/v1/embeddings`(별칭 `local-embed` → Ollama bge-m3)로 부릅니다. 같은 본문은 `RAG_CACHE_DIR`에 저장해 다시 보내지 않습니다.

## 답(`POST /answer`)

1. `/search`와 같은 범위(토큰 `doc_scopes`)에서 하이브리드 상위 5개를 근거 후보로 고릅니다. 질문에 말이 없거나 후보가 없으면 LLM을 부르지 않습니다.
2. gateway의 OpenAI 호환 `/v1/chat/completions`를 위임 토큰과 함께 부릅니다. gateway가 에이전트 모델 정책을 적용합니다. 모델은 LiteLLM 별칭(`RAG_LLM_MODEL`, 기본 `local`)이고, `reasoning_effort: none`으로 생각 과정을 끕니다.
3. 모델은 `{"found", "answer", "citations": [{"ref", "quote"}]}`를 냅니다. 인용(quote)이 그 근거 본문에 있는지 대조합니다. 띄어쓰기·가운뎃점 모양·따옴표·호환 한자 차이는 무시하고, 공백을 뺀 10자 미만은 통과시키지 않습니다("다음 각 호" 같은 흔한 구절 하나로 통과하지 못하게).
4. 다음 중 하나면 답을 버리고 `found: false`와 "규정에서 찾지 못했습니다."를 돌려줍니다.
   - 대조를 통과한 인용이 없음, 또는 통과한 인용이 모두 신뢰 불가 근거에서 나옴
   - 답에 쓴 숫자가 인용한 근거 본문에 없음(흔한 구절을 인용하고 다른 금액을 쓰는 조작을 막음)
   - 모델이 found=false를 냈거나, 출력을 JSON으로 읽지 못함
   대조에 실패한 인용은 응답에서 뺍니다.
5. 근거 본문은 줄마다 `| `를 붙여 넣어, 본문 속에 근거 머리(`[2] 문서: … / 신뢰`)를 위조하지 못하게 합니다. 신뢰 불가 근거는 표시하고 그 안의 지시를 따르지 않게 합니다.

감사 이벤트는 `RAG_AUDIT_LOG`(기본 `rag/.data/audit.jsonl`)에 JSON Lines로 씁니다. 질문 원문과 토큰은 넣지 않습니다.

| 이벤트 | 남기는 때 |
|---|---|
| `rag.answered` | 답을 냈을 때(`result: ok`, found·인용 대조 수), 답 생성이 실패했을 때(`result: error`, 응답 502) |
| `rag.access_denied` | 토큰이 없거나 틀렸을 때(401). 권한을 무시한 BM25 검색의 1위가 권한 밖 문서여서 근거에서 뺐을 때(문서 ID만 적음) |

## 평가용 적재

eval 시나리오에서만 씁니다. 환경 변수가 없거나 빈 값이면 꺼짐입니다. 값이 있으면 파일을 계약 스키마로 확인하고, 파일이 없거나 틀리면 시작 때 실패합니다.

- `RAG_MARKERS_FILE`(`contracts/eval/markers.schema.json`): 생성 문서의 모든 청크 끝에 "관리 표지: <표지>" 줄을 넣습니다(절 단위로 넣으면 긴 절의 앞 청크에 표지가 빠짐). 표지가 여럿이면 청크마다 돌아가며 넣어, 어느 청크가 새도 표지가 함께 나옵니다. 공개 규정 고정본에는 넣지 않습니다.
- `RAG_EXTRA_DOCS`(`contracts/eval/injected-docs.schema.json`): 간접 주입 시나리오용 문서를 더합니다. 신뢰 등급은 언제나 `untrusted`이고 ACL은 `accessTag`(팩 접근 태그)입니다.

## 실행

```
uv sync
RAG_EMBEDDER=hash DELEGATION_TOKEN_PUBLIC_KEY=infra/dev-keys/delegation-es256.pub.pem \
  uv run uvicorn --factory rag.app:from_env --port $PORT_RAG
```

| 환경 변수 | 뜻 |
|---|---|
| `PACK_DIR` | 팩 폴더. 없으면 저장소 `packs/manufacturing` |
| `DELEGATION_TOKEN_PUBLIC_KEY` / `DELEGATION_JWKS_URL` | 위임 토큰 공개 키 PEM 경로 / gateway JWKS 주소 |
| `RAG_EMBEDDER` | `gateway`(기본) 또는 `hash`(음절 2-gram 해시. 의미를 담지 않는 시험·개발용) |
| `RAG_EMBED_BASE_URL`, `GATEWAY_LLM_URL` | 임베딩을 부를 OpenAI 호환 주소(앞의 것이 우선) |
| `RAG_EMBED_MODEL` | 임베딩 모델 이름(기본 `local-embed`) |
| `RAG_EMBED_STARTUP_WAIT` | 시작 때 gateway를 기다리는 최대 초(기본 120). 첫 임베딩이 성공한 뒤에는 다시 시도하지 않음 |
| `RAG_CACHE_DIR` | 임베딩 캐시 폴더(기본 `rag/.cache`) |
| `RAG_STAGE` | 이 단계까지의 문서만 씁니다 |
| `GATEWAY_LLM_URL` | 답 생성용 gateway 주소(예: http://gateway:8000/v1). 없으면 `/answer`는 503 |
| `RAG_LLM_MODEL`, `RAG_LLM_REASONING` | 답 생성 모델 별칭(기본 `local`), reasoning_effort(기본 `none`, 빈 값이면 보내지 않음) |
| `RAG_AUDIT_LOG` | 감사 이벤트 파일 |

## 시험

```
uv sync
uv run pytest -q
```

시험은 네트워크를 쓰지 않습니다. 검색 시험은 해시 임베딩과 시험용 ES256 키를 쓰고, 응답을 계약(`contracts/openapi/rag.yaml`) 스키마로 확인합니다. 파서 시험은 국가법령정보센터 응답 일부(`tests/fixtures/law_sample.html`)와 만든 쪽 글로 봅니다.
