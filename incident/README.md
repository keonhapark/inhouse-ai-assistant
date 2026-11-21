# incident

장애 분석 모듈입니다(기획서 표 ③, #101). 우리 스택에 장애를 직접 주입해 로그·감사 이벤트·티켓과 정답 원인을 묶음으로 만들고(#283), 그 묶음으로 원인 후보를 내는 분석기를 기준선과 비교합니다(#284).

## 구성

| 파일 | 하는 일 |
|---|---|
| `incident/stack.py` | 세션 스택(`iaa-s<번호>`, `--profile full`)을 docker compose로 다룹니다. 다른 세션의 스택은 프로젝트 이름이 달라 건드리지 않습니다 |
| `incident/faults.py` | 장애 목록. 장애마다 정답 원인(서비스·종류)과 주입·복구 방법 |
| `incident/traffic.py` | 장애 전후로 평소 같은 요청(erp 직접 요청 0.5초마다, gateway 대화 20초마다)을 흘리고 응답을 기록 |
| `incident/tickets.py` | 장애마다 직원이 올렸을 법한 티켓 문장(지어낸 것, 증상만)과 erp 티켓 올리기 |
| `incident/collect.py` | 장애 구간의 서비스 로그(`docker logs`)와 감사 이벤트(JSON Lines, erp `GET /audit-events`) 모으기 |
| `incident/run.py` | 주입 → 수집 → 티켓 → 정답 기록을 장애 × 반복 횟수만큼 |
| `incident/rcaeval.py` | 외부 비교용 RCAEval 일부 내려받기 |

## 장애

| ID | 주입 | 정답 원인(서비스 / 종류) | 복구 |
|---|---|---|---|
| `db_down` | PostgreSQL 컨테이너 중단 | postgres / dependency_down | 다시 시작, erp 정상 확인 |
| `db_lock` | 업무 표(결재·예약·연차·티켓)를 배타 잠금으로 60초 잡음 | postgres / lock_contention | 잠금 세션 종료 |
| `erp_memory` | 실행 중인 erp 컨테이너 메모리 상한을 160MB로 낮춤 | erp / resource_exhaustion | 상한 4GB, 멈췄으면 다시 시작 |
| `llm_timeout` | LiteLLM 컨테이너 일시 정지(연결은 받고 답하지 않음) | litellm / dependency_timeout | 정지 해제 |
| `rag_corrupt` | rag 임베딩 캐시를 깨진 JSON으로 덮고 다시 시작 | rag / data_corruption | 빈 캐시로 바꾸고 다시 시작(다시 임베딩) |
| `gateway_bad_config` | 틀린 LiteLLM 키로 gateway 다시 배포 | gateway / bad_config | 맞는 키로 다시 배포 |

디스크 가득은 넣지 않았습니다. 도커 VM 디스크를 다른 세션의 스택과 같이 써서 그 스택까지 멈출 수 있습니다.

주입 전에 세션 DB에 운영에서 흔히 켜 두는 로그(잠금 대기, 1초 넘는 문장, 연결)를 켭니다(`Stack.prepare`).

## 실행

```bash
source scripts/env.sh 1                  # 저장소 루트에서. 세션 번호는 docs/ports.md
cd incident && uv sync
uv run python -m incident.run --session 1 --up --faults all --repeat 3
```

- `--up`은 세션 스택을 빌드해 띄웁니다. 외부 모델 키(`ANTHROPIC_API_KEY`)는 비워 외부로 나가지 않게 합니다.
- `.env`에 `LITELLM_MASTER_KEY`가 없으면 이 스택 전용 키를 `incident/.stack-secrets`에 만들어 씁니다(커밋하지 않음).
- 장애 하나에 평소 구간 45초, 장애 60~90초, 복구, 복구 뒤 30초가 걸립니다. 6종 × 3회는 약 1시간입니다.

## 묶음

`data/runs/<runId>/<incidentId>/`

| 파일 | 내용 |
|---|---|
| `truth.json` | 정답: 장애 ID, 원인 서비스·종류, 구간(시작·주입·복구·끝), 티켓, 파일별 줄 수 |
| `logs/<서비스>.log` | 구간의 컨테이너 로그(docker가 붙인 UTC 시각, stdout·stderr를 시각 순으로 합침) |
| `audit/*.jsonl` | 구간의 감사 이벤트(gateway·agent·rag 파일, erp `GET /audit-events`) |
| `traffic.jsonl` | 흘린 요청의 응답 상태·지연(사용자가 겪은 증상) |

티켓은 erp에 실제로 올라가 다음 장애의 "과거 티켓"이 됩니다(#284 유사 티켓 검색).

저장소에는 `truth.json`만 둡니다. 로그·감사 이벤트·요청 기록 원문은 저장소가 공개라 커밋하지 않고(`.gitignore`), `incident.run`으로 다시 만듭니다.

## 모아 둔 묶음

장애마다 1회씩 확인한 묶음 7개의 정답(`truth.json`)입니다. 6종 × 3회 본 실행은 1회차 db_down까지 하고 멈췄습니다.

| 실행 | 묶음 | 수집 방식 |
|---|---|---|
| `20261121-0058` | db_down-01, db_lock-01, erp_memory-01, llm_timeout-01 | 서비스 로그·감사 이벤트. 컨테이너 이벤트와 복구 전 로그 따로 받기는 아직 없음 |
| `20261121-0106` | rag_corrupt-01, gateway_bad_config-01 | 위 + 컨테이너 이벤트(`logs/docker-events.log`), 복구 전 로그 |
| `20261121-0115` | db_down-01 | 위와 같음, 평소 구간 45초·복구 뒤 30초(앞 두 실행은 20초·15초) |

알아 둘 것:

- 세션 스택은 외부 모델 키를 비워 띄우므로, 외부 별칭으로 가는 호출은 평소에도 LiteLLM에서 401(Missing Anthropic API Key)로 끝납니다. 장애와 관계없는 잡음입니다.
- 장애를 주입·복구한 docker 조작(pause, stop, update 등)도 컨테이너 이벤트에 남습니다. 분석에서는 이것을 증상이 아닌 조작으로 보고 빼야 합니다.
- 묶음은 커밋하므로 수집할 때 위임 토큰 ID(`delegationTokenId`, 비밀값 검사가 키로 봄)와 erp 시작 로그의 Spring 기본 비밀번호를 `<가림>`으로 바꿉니다(`collect.sanitize`).

## 분석기(#284)

| 파일 | 하는 일 |
|---|---|
| `incident/logs.py` | 묶음 로그를 줄 단위(시각, 서비스, 수준)로 읽음. 스택 추적 줄은 앞 줄에 붙이고, 헬스 검사 줄은 따로 표시하고, 컨테이너 이벤트 중 사람이 한 조작(pause, stop, update 등)은 뺌 |
| `incident/baseline.py` | LLM 없는 기준선. Drain3(MIT)로 로그 템플릿을 묶어 분석 구간에 늘어난 템플릿, 로그가 끊긴 서비스(헬스 검사 줄까지 사라짐), 비슷한 과거 티켓의 원인으로 서비스 순위 |
| `incident/llm.py` | 기준선이 모은 진단 텍스트(늘어난 템플릿, 끊긴 로그, 티켓, 비슷한 과거 티켓)를 gateway `local` 별칭에 주고 원인 후보 3개(서비스, 종류, 근거 줄)를 받음 |
| `bench/rca.py` | 묶음으로 상위 1·3 정확도(원인 서비스)와 지연을 잼 |

```bash
uv run python -m bench.rca --runs data/runs/<runId> ... [--llm http://localhost:8110] --out bench/results/<이름>.json
```

- 신고 시각을 주입 45초 뒤로 두고, 분석 구간은 그 직전 45초, 기준 구간은 묶음 시작부터 분석 구간 앞까지입니다. 정답은 신고 시각을 정하는 데만 씁니다.
- 과거 티켓은 같은 묶음 모음의 다른 장애 티켓과 정답 원인입니다(한 건씩 빼고 나머지).
- `--llm`은 세션 스택의 gateway입니다(`litellm`·`gateway`만 띄워도 됨). 위임 토큰 없는 로컬 별칭 호출입니다.

### `/analyze`(호스트 로컬 도구)

계약은 `contracts/openapi/incident.yaml`입니다. compose에 넣지 않고 호스트에서 띄워 세션 스택 로그를 docker CLI로 읽습니다(도커 소켓을 컨테이너에 열지 않음).

```bash
cd incident && INCIDENT_SESSION=1 uv run uvicorn --factory incident.app:from_env --host 0.0.0.0 --port 8170
```

- 위임 토큰(`X-Delegation-Token`, aud `incident`, scope `incident:read`)을 확인하고, 같은 토큰으로 erp `GET /tickets?box=all`이 되는 사람(티켓 담당)만 분석합니다.
- `ticketId`를 주면 erp에서 티켓을 읽어 본문을 증상으로 쓰고, 분석 기준 시각은 `at`이나 티켓 작성 시각입니다.
- LLM이 실패하거나 후보를 못 내면 기준선 순위로 답합니다(`method: baseline`).
- `INCIDENT_HISTORY_DIR`에 원인이 밝혀진 묶음(truth.json) 폴더를 주면 비슷한 과거 티켓을 씁니다.

### 개발용 측정(7건)

`bench/results/dev-7-1047.json`, 2026-11-21 10:47, 데스크탑(RTX 4070 SUPER, qwen3.5:9b), 묶음 7개(장애 6종 각 1회 + db_down 1회), 각 1회.

| 방법 | 상위 1 | 상위 3 | 지연 중앙값 |
|---|---|---|---|
| 로그(템플릿 변화 + 로그 끊김) | 0.429 | 0.857 | 14ms |
| 로그 + 유사 티켓 | 0.429 | 0.857 | 15ms |
| LLM(진단 텍스트) | 0.571 | 0.714 | 10.5초 |
| LLM(티켓만) | 0.429 | 0.857 | 9.3초 |

- 그 뒤 로그 수준 판정을 고쳤습니다(단어 중간의 ValueError·SQLException을 오류로, HTTP 상태는 접근 로그 모양일 때만). 기준선만 다시 잰 값(`bench/results/dev-7-baseline-1053.json`, 10:53): 로그 상위 1 0.429·상위 3 0.857, 로그 + 유사 티켓 상위 1 0.286·상위 3 0.857. 세션 스택을 메모리 때문에 내려 LLM은 다시 재지 못했습니다.
- 이 7건으로 기준선을 손봤으므로(로그 끊김 신호, 기준 구간) 개발용 수치입니다. 결론은 기준선을 고정한 뒤 새로 모을 6종 × 3회로 냅니다.
- 같은 Ollama를 평가 스택(iaa-s5)이 함께 쓰는 중이라 LLM 지연은 흔들립니다.
- 틀리는 경우: 외부 모델 키를 비워 생기는 LiteLLM 401(Missing Anthropic API Key)이 늘어난 오류로 잡혀 litellm을 원인으로 고름. gateway 잘못된 키 배포는 오류가 LiteLLM 쪽에 찍혀 litellm을 고름.
- 티켓 문장이 증상을 꽤 드러내(예: "AI 비서" → LLM 경로) 티켓만으로도 상위 3이 높습니다.

## 외부 비교 데이터(RCAEval)

```bash
uv run python -m incident.rcaeval --list   # 출처·크기만
uv run python -m incident.rcaeval          # data/external/RE3-SS/에 풀기(101.5MB, 커밋하지 않음)
```

- 출처: Pham et al., RCAEval(https://github.com/phamquiluan/RCAEval), 데이터 Zenodo 레코드 14590730
- 라이선스: Zenodo 데이터는 CC BY 4.0, 코드 저장소 README는 MIT로 적혀 있습니다
- RE3-SS(Sock Shop, 30건, 로그 포함)만 받습니다. 경우 폴더 이름이 정답 원인이고 `inject_time.txt`가 주입 시각입니다

## 시험

```bash
cd incident && uv run pytest
```

장애 목록, 주입 명령(가짜 docker로 세션 컨테이너만 건드리는지), 구간 거르기, 로그 합치기를 봅니다. 실제 주입은 세션 스택에서 `incident.run`으로 확인합니다.
