# 도구 호출 LoRA 학습 데이터(#469, #111)

`make_toolcall_data.py`는 로컬 모델 도구 호출 미세조정(QLoRA)에 쓸 학습 데이터를 만듭니다. GPU는 쓰지 않습니다. 학습은 GPU 사용권(`scripts/gpu-lease.sh`)을 받아 따로 합니다.

```bash
cd agent
uv run python lora/make_toolcall_data.py --out <저장소 밖 폴더> [--per-tool 40] [--seed 7] [--valid-ratio 0.1]
```

- 예시 하나는 업무 실행의 첫 계획 호출과 같은 모양입니다: 에이전트 system 프롬프트(`run/graph.py` `system_prompt`, 조건 `full`), 그 에이전트가 보는 2단계 이하 도구 정의(`contracts/mcp/tools.json`), 사용자 발화, 정답 행동
- 정답 종류: `direct`(바로 부름), `resolve`(이름·ID가 없어 조회 도구를 먼저 부름), `clarify`(필수 값이 빠져 그 값만 물음)
- 값은 도구 계약과 팩 고정 데이터(직원·회의실·품목·양식)에서만 고릅니다. 문장 틀은 생성기에 직접 썼습니다
- 평가와 섞지 않으려고 확인 묶음은 읽지 않고, 개발 묶음(`eval_dev/tool_calls.jsonl`)과 같은 문장은 버립니다. 문장과 정답이 같은 예시는 하나만 둡니다
- 출력: `train.jsonl`·`valid.jsonl`(줄마다 `{id, agent, kind, tool, today, tools, messages}`), `manifest.json`(개수·시드·입력 해시). 도구 호출은 `tool_calls[].function.arguments`가 객체인 Hugging Face chat template 형식입니다
- 같은 시드면 같은 데이터입니다. 기본 설정(시드 7, 도구당 40)으로 374개(학습 337, 검증 37)가 나옵니다

시험: `uv run pytest -q tests/test_lora_data.py`(정답 인자가 도구 입력 스키마에 맞는지, 도구가 그 에이전트 것인지, system 프롬프트가 업무 프롬프트와 같은지, 개발 묶음 문장과 겹치지 않는지, 재현성).
