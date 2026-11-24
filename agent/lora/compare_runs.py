"""기본 모델과 LoRA 모델의 첫 계획 호출 결과를 개발 묶음으로 견줍니다(#545). 채점기가 아니라 개발용 비교입니다.

두 실행은 `eval_dev/first_call_run.py`로 같은 입력·변형(S0: few-shot·문법·도구 거르기 없음)에 모델만 바꿔 만듭니다.
확인 묶음은 쓰지 않습니다(학습 효과 확인은 eval이 확인 묶음으로 따로 합니다).

    uv run python eval_dev/first_call_run.py --base-url <ollama>/v1 --model qwen3.5:9b --out <기본>.jsonl
    uv run python eval_dev/first_call_run.py --base-url <ollama>/v1 --model qwen3.5-9b-toolcall-lora --out <LoRA>.jsonl
    uv run python lora/compare_runs.py <기본>.jsonl <LoRA>.jsonl [--overlap <overlap.py 보고서>]

`--overlap`을 주면 학습 데이터와 문장 틀이 겹친 개발 항목(#653)을 뺀 표도 함께 냅니다. 겹친 항목은 학습 때 거의 같은
문장을 봤으므로 LoRA 효과를 부풀릴 수 있습니다.

개발 묶음 항목(source=dev)만 셉니다. 기대 도구는 정답·대안 정답 도구 중 하나를 첫 행동으로 불렀는지입니다.
LoRA는 생각 끔 형식으로 학습하므로(train_qlora.py) 기본·LoRA를 `--variant '{"thinking": false}'`와 생각 켬(변형 없음) 둘 다로
돌려 견줍니다. 업무 경로는 생각 켬이 기본입니다(결정 0008).
"""

from __future__ import annotations

import argparse
import json
import statistics
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


def table(base: list[dict[str, Any]], tuned: list[dict[str, Any]]) -> str:
    sb, st = score(base), score(tuned)
    lines = ["| 항목 | 기본 | LoRA |", "|---|---|---|", *(f"| {k} | {sb[k]} | {st[k]} |" for k in sb)]
    return "\n".join(lines) + "\n" + json.dumps(changed(base, tuned), ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="기본 실행 jsonl")
    ap.add_argument("tuned", help="LoRA 실행 jsonl")
    ap.add_argument("--overlap", help="lora/overlap.py 보고서(overlapIds를 뺀 비교를 더 냄)")
    args = ap.parse_args(argv)
    base, tuned = load(Path(args.base)), load(Path(args.tuned))
    print(table(base, tuned))
    if args.overlap:
        ids = set(json.loads(Path(args.overlap).read_text("utf-8"))["overlapIds"])
        print(f"\n학습 데이터와 문장 틀이 겹친 개발 항목 {len(ids & {r['id'] for r in base})}개를 뺀 비교(#653):\n")
        print(table([r for r in base if r["id"] not in ids], [r for r in tuned if r["id"] not in ids]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
