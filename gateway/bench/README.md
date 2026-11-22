# gateway 측정

실제 로컬 모델을 부르는 측정입니다. GPU 사용권(`scripts/gpu-lease.sh`)을 받은 동안에만 돌립니다. 스크립트는 측정 대상 Ollama 주소를
작업 공간 `.env`의 `COLAB_OLLAMA_BASE_URL`(또는 `--base-url`)에서 읽고, 주소는 출력하거나 기록하지 않습니다. 결과는 `results/`에 둡니다.
질문·문장·영수증은 모두 지어낸 것입니다.

## 2026-11-22 코랩 T4, 터널 경유

기기: 코랩 T4(Ollama 0.40.17, `qwen3.5:9b` Q4_K_M·vision, `bge-m3` F16), 이 PC(WSL)에서 터널로 호출. 응답 시간에는 터널 왕복이 들어
있습니다. 스크립트는 이 PR의 판이고, 결과 파일의 `commit`은 실행 때의 develop(6a4aee2)입니다.

### 의미 캐시 문턱(#465·#484) — `cache_threshold.py`, [results/cache-threshold.json](results/cache-threshold.json)

같은 뜻 쌍(양성) 20개와 달라야 하는 쌍(음성) 23개(이름·지명·반대말·시점·대상·사유·숫자, `cache_pairs.jsonl`)를 bge-m3로 임베딩해
gateway 캐시와 같은 코사인 유사도를 봅니다. 1회(임베딩은 결정적).

| 문턱 | 양성 적중 | 음성 적중(숫자 조건 적용) |
|---|---|---|
| 0.85 | 18/20 | 8/23 |
| 0.90 | 11/20 | 5/23 |
| 0.95(현재 기본) | 4/20 | 1/23 |
| 0.96 | 1/20 | 0/23 |
| 0.97 | 0/20 | 0/23 |

- 가장 비슷한 음성 쌍은 "이번 달 경비 합계 알려 줘" / "지난달 경비 합계 알려 줘"(0.960)로, 기본 문턱 0.95에서 적중합니다.
  그다음은 "오늘/내일 회의 일정"(0.917), "최정남/최정민 대리"(0.915), 휴가 사유 "아이/부모님 병원"(0.911)입니다.
- 음성 적중이 0인 가장 낮은 문턱은 0.96이고, 그때 양성은 20개 중 1개("보안 교육 어디서 들어?" / "보안 교육은 어디서 수강해?",
  0.970)만 적중합니다. 짧은 한국어 문장에서 bge-m3 유사도로는 같은 뜻과 다른 뜻이 거의 갈리지 않습니다.
- 숫자 조건은 숫자 쌍 두 개("3월 9일/10일" 0.924, "5만/50만 원" 0.914)를 막지만, 가장 비슷한 음성 쌍은 숫자가 없어 문턱을 바꾸지 않습니다.

### 로컬로 돌린 호출의 생각 끔(#427) — `reroute_latency.py`, [results/reroute-latency.json](results/reroute-latency.json)

gateway가 로컬로 돌린 호출 모양(시스템 프롬프트 + 도구 두 개 + 질문)을 LiteLLM 1.108.1 `ollama_chat/qwen3.5:9b`(num_ctx 8192)로
보냅니다. 질문 5개 × 3회, 질문마다 두 조건을 번갈아 보내고 적재 호출 1번은 버립니다.

| 조건 | n | 중앙값 | 평균 | 최대 | 60초 초과 | 완성 토큰 중앙값 |
|---|---|---|---|---|---|---|
| `reasoning_effort: none`(#427이 채움) | 15 | 2.96초 | 3.87초 | 10.54초 | 0 | 68 |
| 없음(모델 기본, 생각함) | 15 | 8.19초 | 13.07초 | 79.91초 | 1 | 193 |

- 생각을 켠 쪽의 79.9초(휴가 신청 질문)는 gateway 시간 제한(`LLM_TIMEOUT_SECONDS` 60초)을 넘습니다. #427이 막으려던 경우입니다.

### 첨부 이미지 재압축과 영수증 읽기(#458) — `jpeg_receipts.py`, [results/jpeg-receipts.json](results/jpeg-receipts.json)

개발 영수증 40장(`eval/tools/make_receipts.py`, 시드 DEV_SEED, 글꼴 Noto Sans KR Regular, SIL OFL)을 휴대폰 사진처럼 JPEG 품질 90에
지어낸 GPS·기기 EXIF를 넣어 '원본'으로, `gateway.vision.strip_metadata`(품질 95 재압축)를 거친 것을 '재압축'으로 두고, 같은 모델
(`qwen3.5:9b` vision, 생각 끔, JSON 스키마)로 읽어 `eval/harness/receipts.py`로 채점했습니다. 영수증마다 두 조건 순서를 번갈아, 1회.

| 조건 | 금액 | 날짜 | 가맹점 | 사업자번호 | 네 필드 모두 | 읽기 시간 중앙값 |
|---|---|---|---|---|---|---|
| 원본(JPEG 90, EXIF 있음) | 36/40 | 32/40 | 33/40 | 38/40 | 23/40 | 3.31초 |
| 재압축(JPEG 95, EXIF 없음) | 34/40 | 31/40 | 33/40 | 37/40 | 25/40 | 3.31초 |

- 네 필드 모두 맞음이 한쪽에서만 맞은 영수증은 원본만 1장, 재압축만 3장입니다(필드 하나씩: 날짜 2, 사업자번호 2). 방향이 섞여 있어
  재압축이 읽기를 떨어뜨린다는 근거는 없고, 1회 측정이라 이 정도 차이는 모델 출력의 흔들림과 구분되지 않습니다.
- 평균 픽셀 차이(0~255)는 0.091이고, 40장 모두 재압축 뒤 EXIF가 남지 않았습니다.

### 다시 재는 방법

```bash
bash scripts/gpu-lease.sh take colab gateway 60 "gateway 측정"
cd gateway
uv run python bench/cache_threshold.py --device "코랩 T4, 터널 경유"
uv run --with litellm==1.108.1 --with mcp python bench/reroute_latency.py --reps 3
uv run --with litellm==1.108.1 --with mcp python bench/jpeg_receipts.py --font <NotoSansKR-Regular.ttf>
bash ../scripts/gpu-lease.sh release colab gateway
```

`--with mcp`는 LiteLLM 1.108.1이 도구·이미지가 든 요청을 변환할 때 `mcp` 모듈을 불러서 넣습니다. 데스크탑 Ollama로 재려면
`--base-url`에 그 주소를 주고 `--device`를 바꿉니다.
