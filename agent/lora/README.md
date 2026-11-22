# 도구 호출 LoRA 학습 데이터(#469, #111)

`make_toolcall_data.py`는 로컬 모델 도구 호출 미세조정(QLoRA)에 쓸 학습 데이터를 만듭니다. GPU는 쓰지 않습니다. 학습은 GPU 사용권(`scripts/gpu-lease.sh`)을 받아 따로 합니다.

```bash
cd agent
uv run python lora/make_toolcall_data.py --out <저장소 밖 폴더> [--per-tool 150] [--seed 7] [--valid-ratio 0.1] \
  [--exclude <toolcall-v1 확인 묶음 jsonl>]
```

- 예시 하나는 업무 실행의 첫 계획 호출과 같은 모양입니다: 에이전트 system 프롬프트(`run/graph.py` `system_prompt`, 조건 `full`), 그 에이전트가 보는 2단계 이하 도구 정의(`contracts/mcp/tools.json`), 사용자 발화, 정답 행동
- 정답 종류: `direct`(바로 부름), `resolve`(이름·ID가 없어 조회 도구를 먼저 부름), `clarify`(필수 값이 빠져 그 값만 물음)
- 값은 도구 계약과 팩 고정 데이터(직원·회의실·품목·양식)에서만 고릅니다. 문장 틀은 생성기에 직접 썼습니다
- 평가와 겹치지 않게 개발 묶음(`eval_dev/tool_calls.jsonl`)과 `--exclude`로 준 묶음(toolcall-v1 형식)의 문장과 정확히 같거나(띄어쓰기·문장부호 무시) 가까운(글자 3-gram 자카드 0.6 이상) 생성 문장은 버립니다(#544). 생성에는 평가 묶음을 쓰지 않고, 겹침 검사에만 씁니다. 문장과 정답이 같은 예시는 하나만 둡니다
- 문장 틀: 말끝(해 줘·해 주세요·부탁해요 등), 날짜(내일·모레·이번 주/다음 주 요일·지난주 요일·다음 달 D일·M/D·M월 D일), 시각(오후 2시·14시·오후 두 시·2시 반·14:30)과 길이(30분~두 시간), 생략(사유·날짜·시간·목적·금액·수량·맡을 사람이 빠진 되묻기), 선택 값이 들어간 경우(회수 사유, 대결 금액 한도, 사업자번호, 티켓 우선순위)
- 출력: `train.jsonl`·`valid.jsonl`(줄마다 `{id, agent, kind, tool, today, tools, messages}`), `manifest.json`(개수, 종류·정답 도구별 수, 시드, 대조한 묶음의 이름·해시·문장 수(경로는 남기지 않음), 걸러낸 문장 수). 도구 호출은 `tool_calls[].function.arguments`가 객체인 Hugging Face chat template 형식입니다
- 같은 시드면 같은 데이터입니다. 기본 설정(시드 7, 문장 틀 묶음당 150, 개발 묶음만 대조)으로 1,382개(학습 1,244, 검증 138, 서로 다른 문장 1,381)가 나옵니다. 바로 부름 1,053, 조회 먼저 148, 되묻기 181이고 정답 도구는 21종입니다. 개발 묶음과 겹쳐 버린 문장은 정확 일치 3, 근접 4입니다
- 날짜가 없는 조회(잔여 휴가 9, 인사 정보 7, 규정 16)는 문장 틀 수만큼만 나옵니다

시험: `uv run pytest -q tests/test_lora_data.py`(정답 인자가 도구 입력 스키마에 맞는지, 도구가 그 에이전트 것인지, system 프롬프트가 업무 프롬프트와 같은지, 개발 묶음과 정확·근접 중복이 없는지, `--exclude` 검사, 조사, 문장 다양성, 재현성).

## QLoRA 학습·평가(#545)

학습·평가는 GPU 사용권(`scripts/gpu-lease.sh`, desktop 또는 colab)을 받은 동안에만 돌립니다. 학습 환경과 결과는 모두 저장소 밖입니다.

```bash
cd agent
bash lora/install_qlora.sh                                   # ~/.cache/iaa-qlora-venv, ~/.cache/iaa-llama.cpp
uv run python lora/make_toolcall_data.py --out ~/lora/data   # 학습 데이터(GPU 없음)
PY=~/.cache/iaa-qlora-venv/bin/python
$PY lora/train_qlora.py --data ~/lora/data --out ~/lora/run1 --dry-run   # 토큰 길이·버리는 예시만(GPU 없음)
$PY lora/train_qlora.py --data ~/lora/data --out ~/lora/run1             # 학습
$PY lora/export_ollama.py --run ~/lora/run1 --llama-cpp ~/.cache/iaa-llama.cpp --ollama http://172.17.0.1:11434
# 개발 묶음으로 기본·LoRA 비교(생각 끔·켬 각각)
uv run python eval_dev/first_call_run.py --base-url http://172.17.0.1:11434/v1 --model qwen3.5:9b --variant '{"thinking": false}' --out ~/lora/base-nothink.jsonl
uv run python eval_dev/first_call_run.py --base-url http://172.17.0.1:11434/v1 --model qwen3.5-9b-toolcall-lora --variant '{"thinking": false}' --out ~/lora/lora-nothink.jsonl
uv run python lora/compare_runs.py ~/lora/base-nothink.jsonl ~/lora/lora-nothink.jsonl
```

- 기본 모델: Hugging Face `Qwen/Qwen3.5-9B`(Apache-2.0, `Qwen3_5ForConditionalGeneration`). 리비전을 고정하지 않으면 받은 sha를 `run.json`에 남깁니다
- 학습(`train_qlora.py`): 4비트 NF4·이중 양자화(양자화하지 않은 층을 fp32로 올리는 `prepare_model_for_kbit_training`은 쓰지 않음), bf16 계산(T4처럼 bf16이 없으면 fp16), 언어 모델 attention·MLP 선형층에만 LoRA(r 16, alpha 32, dropout 0.05), 정답(assistant) 토큰만 손실, 2 epoch, 학습률 2e-4(cosine), 배치 1 × 누적 8, gradient checkpointing, paged AdamW 8bit, 시드 7
- chat template은 생각 끔 형식입니다. 데이터에 생각 내용이 없어 생각 켬 형식으로 만들면 빈 생각을 가르치게 되고 토큰 경계도 어긋납니다. 업무 경로는 생각 켬이 기본(결정 0008)이라 평가는 생각 끔·켬 둘 다 합니다
- `--dry-run`은 토큰화에 더해 학습 설정도 봅니다: 인자 이름이 설치된 transformers의 `TrainingArguments` 필드에 있는지, torch가 있으면 `TrainingArguments` 생성과 `Trainer` 인자까지(#551 v2는 transformers 5에서 없어진 `warmup_ratio`로 학습 시작 때 멈췄습니다. 지금은 `warmup_steps=0.03`(비율))
- 토큰 길이(기본 데이터, Qwen3.5 토크나이저): p50 1,296, 최대 1,834. 정답 토큰 합 학습 62,780·검증 7,533. 확인은 `--dry-run`으로 했습니다(transformers 5.22.2, GPU 없음)
- 내보내기(`export_ollama.py`): PEFT 어댑터를 llama.cpp `convert_lora_to_gguf.py`로 GGUF 어댑터로 바꾸고, Ollama API(`/api/blobs`, `/api/create`의 `adapters`)로 `qwen3.5:9b` 위에 얹은 모델을 만듭니다. 학습은 bf16 원본, 실행은 Q4_K_M 기본 모델이라 수치가 조금 다릅니다
- 비교(`compare_runs.py`): `eval_dev/first_call_run.py` 두 실행의 개발 묶음 항목만 견줍니다(기대 도구, 되묻기 정답에서 도구 없이 답함, 지연, 좋아진·나빠진 항목). 확인 묶음 평가는 eval이 합니다
- 의존성 판(`install_qlora.sh`): torch 2.14.1, transformers 5.22.2, peft 0.21.2, bitsandbytes 0.50.2, accelerate 1.15.0, gguf 0.19.0. 실제 판과 llama.cpp 커밋은 가상환경의 `install.json`에 남습니다

### Kaggle에서 학습하기(#551)

Kaggle 노트북(T4 x2)에 Ollama와 터널을 띄운 셀이 돌고 있을 때, 셀 하나로 학습부터 Ollama 등록까지 끝까지 가게 합니다. 셀 코드는 저장소 밖에 두고(노트북에 붙여 넣음), 순서는 아래와 같습니다.

1. 디스크·GPU·Ollama 확인. 기본 모델(약 19GB)은 `/kaggle/working`(20GB) 밖(`HF_HOME=/tmp/hf`)에 받습니다. T4 한 장(15GB)에는 4비트 모델과 양자화하지 않은 임베딩·lm_head가 함께 들어가지 않아(#551 OOM) 두 GPU에 나눠 올립니다(`device_map=auto`). 학습하는 동안 Kaggle Ollama는 부르지 않습니다
2. 공개 저장소를 받아 커밋을 고정
3. `QLORA_SYSTEM=1 bash lora/install_qlora.sh`: 새 가상환경 없이 Kaggle 파이썬에 학습 패키지와 llama.cpp `gguf-py`를 넣습니다(Kaggle torch 그대로)
4. `uv run python lora/make_toolcall_data.py --out …`(agent는 파이썬 3.12가 필요해 uv로). 기본 시드, 개발 묶음만 대조합니다. 확인 묶음 겹침 검사는 eval이 따로 합니다(#544)
5. `train_qlora.py --dry-run` 뒤 학습. 학습은 백그라운드로 돌리고 `--progress-minutes 3` 진행 줄(단계·손실·경과·남은 시간)을 셀 출력에 옮겨 적습니다. T4는 bf16이 없어 fp16으로 계산합니다
6. `export_ollama.py --ollama http://localhost:11434`로 `qwen3.5-9b-toolcall-lora`를 만들고 `run.json`·`ollama.json` 요약을 출력합니다

평가(개발 묶음, 생각 끔·켬, 기본 대비)는 GPU 사용권 `kaggle`을 받아 터널 주소로 `eval_dev/first_call_run.py`와 `lora/compare_runs.py`를 돌립니다.
