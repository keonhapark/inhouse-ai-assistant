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

임베딩은 gateway의 OpenAI 호환 `/v1/embeddings`로 부릅니다. 같은 본문은 `RAG_CACHE_DIR`에 저장해 다시 보내지 않습니다.

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
| `RAG_CACHE_DIR` | 임베딩 캐시 폴더(기본 `rag/.cache`) |
| `RAG_STAGE` | 이 단계까지의 문서만 씁니다 |

## 시험

```
uv sync
uv run pytest -q
```

시험은 네트워크를 쓰지 않습니다. 검색 시험은 해시 임베딩과 시험용 ES256 키를 쓰고, 응답을 계약(`contracts/openapi/rag.yaml`) 스키마로 확인합니다. 파서 시험은 국가법령정보센터 응답 일부(`tests/fixtures/law_sample.html`)와 만든 쪽 글로 봅니다.
