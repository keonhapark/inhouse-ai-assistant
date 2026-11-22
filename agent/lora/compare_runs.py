"""기본 모델과 LoRA 모델의 첫 계획 호출 결과를 개발 묶음으로 견줍니다(#545). 채점기가 아니라 개발용 비교입니다.

두 실행은 `eval_dev/first_call_run.py`로 같은 입력·변형(S0: few-shot·문법·도구 거르기 없음)에 모델만 바꿔 만듭니다.
확인 묶음은 쓰지 않습니다(학습 효과 확인은 eval이 확인 묶음으로 따로 합니다).

    uv run python eval_dev/first_call_run.py --base-url <ollama>/v1 --model qwen3.5:9b --out <기본>.jsonl
    uv run python eval_dev/first_call_run.py --base-url <ollama>/v1 --model qwen3.5-9b-toolcall-lora --out <LoRA>.jsonl
    uv run python lora/compare_runs.py <기본>.jsonl <LoRA>.jsonl

개발 묶음 항목(source=dev)만 셉니다. 기대 도구는 정답·대안 정답 도구 중 하나를 첫 행동으로 불렀는지입니다.
LoRA는 생각 끔 형식으로 학습하므로(train_qlora.py) 기본·LoRA를 `--variant '{"thinking": false}'`와 생각 켬(변형 없음) 둘 다로
돌려 견줍니다. 업무 경로는 생각 켬이 기본입니다(결정 0008).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("source") == "dev"]


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    call_rows = [r for r in rows if r["tools"] and not r["clarify"]]
    clarify_rows = [r for r in rows if r["clarify"]]
    lat = [r["latencyMs"] for r in rows if r.get("latencyMs") is not None]
    return {
        "items": len(rows),
        "errors": sum(r.get("error") is not None for r in rows),
        "expectedTool": f"{sum(r['tool'] in r['tools'] for r in call_rows)}/{len(call_rows)}",
        "clarifyNoTool": f"{sum(r['tool'] is None for r in clarify_rows)}/{len(clarify_rows)}",
        "latencyP50Ms": statistics.median(lat) if lat else None,
    }


def changed(base: list[dict[str, Any]], tuned: list[dict[str, Any]]) -> dict[str, list[str]]:
    """항목별로 기대 도구 호출이 좋아진 것·나빠진 것(호출이 정답인 항목만)."""
    t = {r["id"]: r for r in tuned}
    better, worse = [], []
    for b in base:
        o = t.get(b["id"])
        if o is None or not b["tools"] or b["clarify"]:
            continue
        before, after = b["tool"] in b["tools"], o["tool"] in o["tools"]
        if after and not before:
            better.append(b["id"])
        elif before and not after:
            worse.append(b["id"])
    return {"better": better, "worse": worse}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit("사용: compare_runs.py <기본 실행 jsonl> <LoRA 실행 jsonl>")
    base, tuned = load(Path(argv[0])), load(Path(argv[1]))
    sb, st = score(base), score(tuned)
    print("| 항목 | 기본 | LoRA |\n|---|---|---|")
    for k in sb:
        print(f"| {k} | {sb[k]} | {st[k]} |")
    print(json.dumps(changed(base, tuned), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
