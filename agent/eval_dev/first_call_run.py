"""프롬프트를 바꾸기 전후로 첫 계획 호출을 비교합니다(#305). 채점기가 아니라 개발용 비교입니다.

같은 입력으로 업무 실행의 첫 계획 호출(S0, /eval/tool-call과 같은 코드)만 하고, 도구를 불렀는지·되물었는지·
첫 도구 이름이 기대와 같은지만 셉니다. 입력은 둘입니다.
- 개발 묶음(eval_dev/tool_calls.jsonl, toolcall-v1)
- --scenarios: eval 정상 셋에서 지정한 시나리오의 첫 사용자 턴과 requiredTools(개발용으로만 씀, 확인 셋 아님)

서버 없이 모델 서버(OpenAI 호환)를 바로 부릅니다. gateway를 거치지 않으므로 별칭 대신 모델 이름을 씁니다.

    uv run python eval_dev/first_call_run.py --base-url http://<ollama>:11434/v1 --model qwen3.5:9b \\
        --out eval_dev/runs/<이름>.jsonl [--scenarios <id 목록 파일>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.evaluation.tool_call import (EvalToolCaller, EvalUpstreamError, Variant, load_examples,
                                                load_tools)
from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AGENT_ORDER = ("hr", "assistant", "finance", "procurement", "it_ops")


def requester(people: dict[str, dict], emp_id: str) -> Requester:
    p = people[emp_id]
    return Requester(p["id"], p["unit_id"], p["grade"], ("employee",))


def dev_items(reg: Registry) -> list[dict[str, Any]]:
    out = []
    for line in (HERE / "tool_calls.jsonl").read_text("utf-8").splitlines():
        it = json.loads(line)
        agent = next(a for a in AGENT_ORDER if reg.has(a) and it["targetTool"] in reg.get(a).tools)
        exp = [it["expected"], *it.get("alsoAcceptable", [])]
        out.append({"id": it["id"], "source": "dev", "agent": agent, "requester": it["requester"],
                    "today": it["referenceDate"], "message": it["utterance"],
                    "tools": [a["tool"] for a in exp if a["type"] == "call"],
                    "clarify": any(a["type"] == "clarify" for a in exp)})
    return out


def scenario_items(ids: list[str]) -> list[dict[str, Any]]:
    docs: list[dict] = []
    for f in sorted((ROOT / "eval" / "scenarios" / "manufacturing" / "normal").glob("*.yaml")):
        d = yaml.safe_load(f.read_text("utf-8"))
        docs += d if isinstance(d, list) else d.get("scenarios", [d])
    by_id = {s["id"]: s for s in docs}
    out = []
    for sid in ids:
        s = by_id[sid]
        first = next(t["content"] for t in s["turns"] if t["role"] == "user")
        out.append({"id": sid, "source": "scenario", "agent": s.get("expectedAgent") or s.get("expected_agent"),
                    "requester": s["requester"], "today": "2026-11-20", "message": first,  # #86 실행일(시나리오에는 기준일이 없음)
                    "tools": list(s["expect"].get("requiredTools", [])), "clarify": False})
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios")
    ap.add_argument("--stage", type=int, default=2)
    args = ap.parse_args()
    pack = ROOT / "packs" / "manufacturing"
    reg = Registry.load(pack, stage=args.stage)
    raw = json.loads((pack / "fixtures" / "employees.json").read_text("utf-8"))
    people = {e["id"]: e for e in (raw.get("employees", raw) if isinstance(raw, dict) else raw)}
    chat = ChatClient(LLMSettings(base_url=args.base_url.rstrip("/"), model=args.model, timeout_s=300))
    caller = EvalToolCaller(reg, chat, load_tools(ROOT / "contracts" / "mcp" / "tools.json"),
                            load_examples(HERE / "tool_calls.jsonl"))
    items = dev_items(reg)
    if args.scenarios:
        items += scenario_items(Path(args.scenarios).read_text("utf-8").split())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out.open("w", encoding="utf-8") as f:
        for it in items:
            row: dict[str, Any] = {}
            for attempt in range(1, 4):
                try:
                    res = await caller.run(it["message"], it["agent"], requester(people, it["requester"]),
                                           date.fromisoformat(str(it["today"])), args.model, Variant())
                    row = {**it, "tool": res["tool"], "asked": res["asked"], "content": res["content"],
                           "latencyMs": res["latencyMs"], "error": None, "attempts": attempt}
                    break
                except EvalUpstreamError as e:
                    # 공용 모델 서버 연결이 잠깐 끊기면 다시 부릅니다(재시도 수는 줄에 남김).
                    row = {**it, "tool": None, "asked": False, "content": "", "latencyMs": None,
                           "error": repr(e), "attempts": attempt}
                    await asyncio.sleep(10)
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    print(json.dumps(summary(rows), ensure_ascii=False, indent=1))


def summary(rows: list[dict]) -> dict:
    def part(rs: list[dict]) -> dict:
        call_rows = [r for r in rs if r["tools"] and not r["clarify"]]
        lat = sorted(r["latencyMs"] for r in rs if r["latencyMs"] is not None)
        return {
            "items": len(rs),
            "errors": sum(r["error"] is not None for r in rs),
            "call_expected": len(call_rows),
            "called_any_tool": sum(r["tool"] is not None for r in call_rows),
            "called_expected_tool": sum(r["tool"] in r["tools"] for r in call_rows),
            "clarify_expected": sum(r["clarify"] for r in rs),
            "clarify_no_tool": sum(r["clarify"] and r["tool"] is None for r in rs),
            "latency_ms_p50": statistics.median(lat) if lat else None,
            "retried": sum(r.get("attempts", 1) > 1 for r in rs),
        }
    return {src: part([r for r in rows if r["source"] == src]) for src in ("dev", "scenario")}


if __name__ == "__main__":
    asyncio.run(main())
