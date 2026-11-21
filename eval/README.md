# eval

평가 하네스입니다. 측정 설계는 [protocol.md](protocol.md)에 있습니다.

장치 구현 코드(`gateway/`, `agent/`, `rag/`의 판정·가림 규칙)를 보지 않고, 계약(`contracts/`)과 실행 기록만으로 판정합니다.

## 구성

| 파일 | 하는 일 |
|---|---|
| `harness/scenario.py` | 시나리오 읽기. 계약 스키마(`contracts/eval/scenario.schema.json`)와 추가 규칙(도구 이름, `${이름}` 참조, 정상·우려 조합)을 검사합니다 |
| `harness/erp.py` | operationId로 erp를 부릅니다. 메서드·경로는 `contracts/openapi/erp.yaml`에서 찾습니다 |
| `harness/setup.py` | 대화 전에 `setup`을 실행하고 `saveAs`로 리소스 ID를 저장합니다 |
| `harness/sut.py` | 평가 대상과의 경계. `GatewayChat`은 gateway 계약의 대화·실행 승인(SSE)·감사 조회를 씁니다 |
| `harness/conversation.py` | 발화, 실행 승인(시나리오의 `executionApprover`), 되묻기 응답(`clarifications`)으로 대화를 끝까지 진행합니다 |
| `harness/db.py` | 대화 직후, 되돌리기 전 `dbAssertions`를 JSONPath(RFC 9535)로 판정합니다 |
| `harness/judge.py` | 표지 문자열·금지 도구·DB 상태·외부 전송으로 사고를 판정하고 결과를 분류합니다 |
| `harness/run.py` | 한 회차: setup → 대화 → 기록 수집 → DB 판정 → 사고 판정 |
| `harness/runner.py` | 다섯 조건 × 반복 실행, 실행 정보(커밋·시드·비용 상한) |
| `harness/stats.py` | Wilson·Clopper-Pearson 구간, Newcombe 짝 비교 구간, pass^k |
| `harness/report.py` | 회차별 결과로 보고서(`reports/`) |
| `harness/attachments.py` | 시나리오 턴의 `attachments`(eval 폴더 기준 이미지 경로)를 gateway 메시지의 이미지 첨부로 바꿉니다 |
| `harness/vision.py` | 이미지 읽기 채점: 도면 부품 번호·도면 이름·치수·주기, 불량 품목·유형을 `images/truth.jsonl`과 대조합니다 |
| `harness/bundle.py` | 확인 셋 묶음 해시를 계약 표(`contracts/eval/confirm-sets.md`)와 대조합니다 |
| `harness/cli.py` | `validate`, `run`, `report` 명령 |

## 야간 회귀(#464)

- `uv run python tools/nightly.py --config <조건 설정>`: 고정한 개발 셋 부분집합(`nightly/subset.txt`, 우려 유형마다 3개, 문서형 주입 제외)을 설정의 조건으로 1회 돌리고, 바로 앞 실행과 (시나리오, 조건) 단위로 견줍니다(`harness/nightly.py`). 공식 평가 셋은 쓰지 않습니다.
- GPU 사용권(`scripts/gpu-lease.sh`)이 비어 있을 때만 돕니다. 사용 중이면 아무것도 하지 않고 끝내고, 도는 동안 30분마다 늘리며 끝나면(실패해도) 반납합니다.
- 결과는 저장소 밖 state 폴더(기본 `~/.local/share/inhouse-ai/nightly`)에 `<시각>.{json,md,rows.jsonl}`와 `<시각>-compare.md`로 남습니다. 1회 실행끼리라 회차 간 변동이 섞이므로, 바뀐 회차는 원인 후보를 찾는 출발점입니다.
- 스택은 미리 띄워 둡니다. 타이머 예시는 `nightly/inhouse-eval-nightly.{service,timer}`(systemd 사용자 단위, cron 한 줄도 적음)입니다.

## 업종 팩(#461)

- `scenarios/finance/dev/`(21개), `scenarios/it-services/dev/`(20개)는 업종 팩을 같은 하네스로 돌려 보는 개발 시나리오입니다(설계 `docs/design/stage3-and-packs.md` 2절). 정상 업무와 반응형(고객 연락처·서버 주소·건강 정보가 든 요청)을 섞었습니다. 금융 팩은 팩 전체가 외부 LLM을 쓰지 않으므로 모두 `externalAllowed: false`입니다. IT 서비스 팩 규정 질의는 팩 문서가 생긴 뒤 더합니다.
- 시나리오 검사는 공용 도구(`contracts/mcp/tools.json`)에 더해 시나리오 팩의 양식 도구(`packs/<팩>/forms.yaml`의 `tool.name`, 예: `loan_request`, `effort_report`)를 받습니다. 시험은 시나리오의 팩으로 가짜 erp를 띄웁니다.
- 실행은 팩으로 띄운 스택(`PACK_DIR`)에서 GPU 사용권을 받아 따로 합니다.
- 새 팩을 더할 때 코어(erp·gateway·agent·rag) 변경 줄 수: `uv run python tools/core_lines.py [--pack <팩>]`. 팩마다 팩 폴더를 바꾼 커밋과, `core_lines.yaml`에 이유와 함께 적은 팩 폴더 밖 관련 커밋(처음 그 기능이 필요했던 팩)을 셉니다. 코어 안 `tests/`는 코어 시험, `*.md`는 코어 문서로 따로, rag 문서 템플릿은 팩으로 셉니다. 관련 커밋 후보는 `--suggest <팩>`(gh 필요, 사람이 골라 설정에 적음). 결과는 `reports/packs/2026-11-22-core-lines.md`입니다.

## 실행

```
cd eval
uv run python -m harness.cli validate scenarios
cp conditions.example.yaml conditions.local.yaml   # 주소·상한을 고침
uv run python -m harness.cli run --config conditions.local.yaml \
  --scenarios scenarios --set dev --out reports/<날짜>-dev-<요지>
uv run python -m harness.cli report reports/<이름>.json -o reports/<이름>.md
```

- 회차마다 `<이름>.rows.jsonl`에 한 줄씩 씁니다. 끊기면 같은 명령에 `--resume`을 붙여 끝난 회차를 건너뛰고 이어 돌립니다. 실행 환경 문제(gateway·erp 연결 실패, 재시도 가능한 오류 뒤 모델 서버 무응답)로 끝나지 못한 회차만 같은 회차 2번까지 다시 돌리고, 그 밖의 오류는 실패로 끝남으로 남깁니다(`eval/protocol.md` 2절). 모델 서버 확인은 설정 `modelHealth`로 켭니다.
- 회차마다 하네스 커밋, 스택 커밋(설정 `stackCommit`), 팩 단계(설정 `packStage`)를 남깁니다. 이어 돌릴 때 앞선 회차와 이 셋이 다르면 멈추고, `--allow-mixed`를 붙이면 섞어서 돌리고 보고서에 시스템별 회차 수를 적습니다. 확인 셋(`--bundle`)은 `--allow-mixed`여도 스택 커밋·팩 단계가 앞선 회차와 다르면 멈추고 하네스 커밋 차이만 받습니다(#449). 설정 `stackCheck.containers`가 있으면 시작할 때 그 컨테이너의 `/repo` 아래 파일 SHA-256을 `stackCommit` 시점의 저장소 파일과 견주고, 다른 파일이나 그 커밋에 없는 파일이 있으면 멈춥니다(가상 환경·캐시는 보지 않음). `--bundle` 실행은 이 설정이 있어야 하고, 결과는 보고서 "띄운 스택 확인" 칸에 적힙니다. 소스를 `/repo`에 두지 않는 컨테이너(Java로 빌드한 erp)는 이 방법으로 확인하지 못합니다. `--bundle`이면 비교한 파일에 `agent/`·`gateway/`·`rag/`가 모두 있어야 합니다(#470). `stackCheck.mounts`에 호스트 작업 트리를 마운트한 경로(litellm `/cfg` ← `gateway/litellm`)를 적으면 그 파일도 `stackCommit`과 대조하고, 적지 않으면 보고서 칸에 "마운트 대조 안 함"이 나옵니다. `stackCheck.env`에 적은 환경 변수(예: `GATEWAY_LOCAL_REASONING_EFFORT`, `RAG_MARKERS_FILE`)는 값을 읽어 보고서 "스택 설정 값" 칸에 남깁니다. 이름에 KEY·SECRET·TOKEN·PASSWORD·URL이 들면 받지 않습니다.
- `--max-runs N`이면 이번 실행은 새 회차 N개까지만 돌리고 멈춥니다. `--resume`과 같이 써서 여러 번에 나눠 돌립니다.
- `--injected-docs only|exclude`는 문서형 주입 시나리오만 또는 그 밖의 시나리오만 돌립니다. 주입 문서 파일(`RAG_EXTRA_DOCS`)은 스택 전체 검색에 보이므로, 켠 스택과 끈 스택에서 나눠 같은 결과 파일에 이어 돌립니다. 설정 `rag.container`가 있으면 시작할 때 스택 설정과 맞는지 확인합니다.
- `--set normal`이면 정상 셋만, `--only <ID,...>`면 지정한 시나리오만 돌립니다.
- 확인 셋은 `--bundle <저장소 밖 묶음 폴더>`로 돌립니다. 시작할 때 묶음 manifest의 `files`(목록·객체 둘 다 읽음)로 묶음 해시를 계약 표 머리말의 규칙(모든 줄 끝 줄바꿈, #439)으로만 계산해 `contracts/eval/confirm-sets.md` 표와 대조하고, 각 파일의 SHA-256도 다시 계산합니다. 맞지 않으면 회차를 하나도 돌리지 않고 멈춥니다. 맞으면 보고서 "확인 셋 묶음" 칸에 해시를 적습니다. `--scenarios` 아래에서 실제로 읽는 파일도 모두 그 manifest `files`에 있어야 합니다. 묶음 밖 폴더나 manifest에 없는 파일이 하나라도 있으면 멈춥니다. rag의 주입 문서 파일(`RAG_EXTRA_DOCS`)이 켜져 있으면 `rag.container`에서 그 파일의 SHA-256을 구해 manifest 파일 중 하나와 같은지 보고, 다르거나 구하지 못하면 멈춥니다. `--bundle`이면 `rag.container` 설정과 docker 접근이 있어야 합니다. 시나리오 첨부 파일(`turns[].attachments`)은 아직 묶음에서 읽지 않으므로, 첨부가 있는 시나리오가 있으면 멈춥니다. 회차마다 대조한 묶음을 기록에 남기고, `--resume` 때 앞선 회차 중 다른 묶음(묶음 없이 돈 회차 포함)이 있으면 멈춥니다. 표지 파일(`RAG_MARKERS_FILE`)은 rag만 읽고 하네스 판정은 시나리오의 `expect.markers`를 쓰므로 대조하지 않습니다. 실행 없이 대조만 하려면 `uv run python -m harness.cli bundle-check <폴더> [--name confirm-v1]`입니다.
- 반복 수는 나눠 늘릴 수 있습니다. 회차 번호가 바깥 고리라, 설정 `repeats: 1`로 돈 결과 파일에 `repeats: 3`으로 `--resume`하면 2·3회차만 더 돌립니다. 보고서의 pass^k는 마지막 실행의 설정 `repeats`를 씁니다(1회로 돈 결과는 pass^1, `repeats: 3`으로 다 돈 뒤에는 pass^3).
- 설정의 `notes`는 보고서 실행 정보에 그대로 적힙니다(프로토콜과 다르게 돌린 이유 등).

## 도구 호출 측정(#103, #237)

로컬 모델의 첫 도구 호출을 항목(toolcall-v1, `contracts/eval/toolcall/`)별로 채점합니다. agent를 `AGENT_EVAL_MODE=1`로 띄우고, 토큰 없는 외부 호출이 필요하면 gateway를 `GATEWAY_EVAL_TOOLCALL=1`로 띄웁니다(정상·확인 셋 스택과 따로).

```
cd eval
uv run python -m harness.cli toolcall-validate [--items <jsonl>] [--max-stage 1]
uv run python -m harness.cli toolcall-run --agent-url http://localhost:$PORT_AGENT --model local \
  --variant '{"thinking": false}' --repeats 1 --max-stage 1 --out reports/<날짜>-toolcall-<요지> \
  --note "기기 ..., 모델 digest ..., Ollama 판 ..."
uv run python -m harness.cli toolcall-report reports/<이름>.json   # 기록을 지금 규칙으로 다시 채점
```

- 항목 기본값은 개발 묶음 `agent/eval_dev/tool_calls.jsonl`(60개, 1단계 도구 48개)입니다. 확인 묶음은 총괄이 넘긴 경로를 `--items`로 주고 `--bundle <묶음 폴더>`를 붙입니다. 시작할 때 묶음 해시를 계약 표와 대조하고 `--items`가 그 manifest 파일인지 보며, 맞지 않으면 멈춥니다. 보고서에는 묶음 대조 결과와 묶음 안 경로만 적고 저장소 밖 절대 경로는 남기지 않습니다.
- 첫 행동만 봅니다. 결과는 정답, 대안 정답, 확인 후 진행(되돌릴 수 없는 도구 앞의 확인 질문), 다른 도구, 인자 틀림, 인자를 못 읽음, 부르지 않고 되물음·답함, 되물어야 하는데 부름, 실행 오류(분모 제외)로 나눕니다. 인자 비교는 `argMatch`(`exact`·`date`·`set`·`normalized`·`nonempty`·`ignore`)이고, 날짜·시각은 같은 시점이면 같다고 봅니다.
- 보조로 인자 스키마 유효(`contracts/mcp/tools.json` inputSchema), 되묻기 비율, 지어낸 필수 인자 수, 모델 지연, 모델 위치를 셉니다.
- setup이 있는 항목은 `--erp-url`(필요하면 `--erp-reset`)로 상태를 만든 뒤 발화와 정답의 `${이름}`을 바꿉니다.

## 이미지 읽기 측정(#110, #386)

3단계 연구소·품질 에이전트가 붙인 그림을 제대로 읽는지 봅니다. 그림마다 새 대화를 열어 같은 질문과 함께 붙이고 답 본문을 정답과 대조합니다.

```bash
uv run --group tools python tools/make_images.py          # images/ 다시 만들기(같은 시드면 같은 그림)
uv run python -m harness.cli vision-run --gateway-url http://localhost:$PORT_GATEWAY \
  --out reports/<날짜>-vision-<요지> [--kind drawing|defect] --note "<스택·모델>"
uv run python tools/fetch_visa.py --out <저장소 밖 폴더> --per-class 5   # 실제 불량 사진(VisA) 부분집합
```

- `images/`의 도면과 합성 불량 사진은 `tools/make_images.py`가 만든 것입니다(외부 자료·글꼴 없음). 정답은 `images/truth.jsonl`입니다.
- 표기 차이(지름 기호 Ø·DIA·지름, 띄어쓰기, 대소문자, 불량 유형의 한·영 표현)는 같다고 봅니다. 도면은 부품 번호·도면 이름과 치수·주기 여섯 항목을 모두 맞혀야 "모두 맞음"입니다.
- 숨은 지시가 든 그림(`hiddenInstruction`)은 읽기 점수에서 빼고, 지시를 따랐는지는 개발 셋 시나리오(`dev-s3-inject-*`)로 봅니다.
- VisA(CC BY 4.0) 원본은 저장소에 넣지 않습니다. 스크립트는 저장소 안 경로를 거부하고, 받은 목록(`manifest.jsonl`, SHA-256)과 라이선스 표기를 함께 남깁니다.
- VisA 전통 기준선(#495): `uv run python tools/fetch_visa.py --out ~/data/visa-subset --classes <범주> --per-class N --normal-per-class M`으로 정상 사진도 받은 뒤 `uv run --group tools python tools/visa_baseline.py --data ~/data/visa-subset --out <결과 이름>`. CPU 손 특징(회색 화소·색·기울기 히스토그램)과 최근접 이웃으로 불량 유형 분류(가장 흔한 유형만 답하는 기준 포함)와 정상 거리 기반 이상 탐지(AUROC, 학습 정상 거리 95번째 백분위 문턱)를 냅니다. 학습 없는 하한이라 비전 모델과 견줄 바닥값입니다.

### 가짜 영수증(#462, #100)

```
uv run --group tools python tools/make_receipts.py --out <저장소 밖 폴더> --font <NotoSansKR-Regular.ttf>   # 개발 묶음 40장
uv run --group tools python tools/make_receipts.py --set confirm --seed <비공개 값> --out <저장소 밖> --font ...
uv run python tools/make_receipts.py --truth-only --out receipts/dev-truth.jsonl                          # 개발 정답만
```

- 가맹점·품목·금액·날짜·사업자번호(검증 숫자가 맞는 가상 번호)를 생성기가 정합니다. 레이아웃(마트·음식점·카드 전표), 날짜·금액 표기, 기울기·흐림·구김·그림자를 시드로 섞습니다. 생성 모델은 쓰지 않습니다.
- 정답은 시드만으로 정해지고 글꼴과 관계없습니다. 개발 묶음 정답(`receipts/dev-truth.jsonl`, 시드 `DEV_SEED`)만 커밋하고, 그림은 저장소 밖에 만듭니다. 확인 묶음은 다른 시드를 실행 때만 주며, 스크립트는 개발 시드와 저장소 안 경로를 거부합니다.
- 한글을 그리려면 라이선스가 분명한 한글 글꼴(예: Noto Sans KR, SIL OFL)을 `--font`로 줍니다. 글꼴은 저장소에 넣지 않고, 쓴 글꼴 파일의 SHA-256을 묶음의 `manifest.json`에 남깁니다.
- 채점(`harness/receipts.py`): 금액·날짜·가맹점·사업자번호 필드 완전 일치. 비교 전에 표기만 정규화합니다. 금액은 통화 기호·쉼표·공백·천 단위 마침표를 지우고 만·천 단위를 읽고, 날짜는 ISO로 바꿉니다. 사업자번호는 숫자 10자리, 가맹점은 NFKC·공백 제거·법인 표기 통일로 맞춥니다. 그 밖의 차이는 틀림이고, 읽지 못한 필드도 틀림입니다. 필드별·전체 완전 일치(Clopper-Pearson 95%)와 레이아웃·왜곡 정도별 전체 일치를 냅니다.
- 전통 기준선(#463): `uv run python tools/ocr_baseline.py --images <묶음 폴더> --engine tesseract|rapidocr|oracle --out <결과 이름>`. OCR 엔진이 낸 줄에서 정규식(`harness/receipt_baseline.py`)으로 네 필드를 뽑아 같은 채점기로 셉니다. `oracle`은 OCR 없이 생성기의 줄 텍스트를 써서 정규식만의 상한을 봅니다(개발 묶음 40/40). OCR 엔진(tesseract `kor`, rapidocr 한국어 모델)은 따로 설치합니다.

## 시험

```
cd eval
uv sync
uv run pytest -q
```

시험은 가짜 erp(`contracts/fakes/erp`)를 프로세스 안에서 띄우고, gateway·agent 자리에는 대본대로 답하는 계약 스텁(`tests/stub_system.py`)을 씁니다. 모델을 부르지 않습니다.

## 실행 환경(평가 전용 설정)

- gateway: `GATEWAY_EVAL_MODE=1`(조건 헤더 `X-Eval-Condition`), `GATEWAY_EXTERNAL_LOG=<파일>`(외부로 보낸 요청 본문, `contracts/events/external-request.schema.json`). 설정의 `gateway.externalLog`에 같은 파일을 적습니다.
- erp: `ERP_EVAL_RESET=1`. 실행기가 회차마다 `POST /_eval/reset`으로 팩 고정 데이터 상태로 되돌립니다.
- rag: `RAG_MARKERS_FILE`(제한 문서 표지, 개발 셋은 `eval/markers/dev.yaml`), `RAG_EXTRA_DOCS`(주입 문서, 개발 셋은 `eval/injections/dev.yaml`). 확인 셋 파일은 작업 공간 밖 경로로만 넘깁니다.
