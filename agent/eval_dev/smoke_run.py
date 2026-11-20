"""개발 묶음을 실제 agent 평가 경로(POST /eval/tool-call)로 한 번 돌려 경로가 도는지 확인합니다.

채점기가 아닙니다(채점·측정은 eval #237, 규칙은 contracts/eval/toolcall). 첫 행동의 도구 이름 일치와 되묻기 모양만
세어 경로 확인 기록으로 남깁니다. 항목에 에이전트가 없어 targetTool을 가진 에이전트를 AGENT_ORDER 순서로 고릅니다.

    uv run python eval_dev/smoke_run.py --url http://localhost:$PORT_AGENT --out eval_dev/runs/<이름>.jsonl \\
        [--model local] [--variant '{"thinking": false}']
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

DEV_SET = Path(__file__).with_name("tool_calls.jsonl")
AGENT_ORDER = ("hr", "assistant", "finance", "procurement")


def agent_for(tool: str, agent_tools: dict[str, list[str]]) -> str:
    return next(a for a in AGENT_ORDER if tool in agent_tools.get(a, []))


def employees(pack_dir: Path) -> dict[str, dict]:
    raw = json.loads((pack_dir / "fixtures" / "employees.json").read_text("utf-8"))
    rows = raw.get("employees", raw) if isinstance(raw, dict) else raw
    return {e["id"]: e for e in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model")
    ap.add_argument("--variant", default="{}")
    ap.add_argument("--pack", default="../packs/manufacturing")
    args = ap.parse_args()
    people = employees(Path(args.pack))
    import yaml  # agent 의존성(pyyaml)

    reg = yaml.safe_load((Path(args.pack) / "agents.yaml").read_text("utf-8"))
    agent_tools = {a["id"]: a["tools"] for a in reg["agents"]}
    variant = json.loads(args.variant)
    items = [json.loads(line) for line in DEV_SET.read_text("utf-8").splitlines() if line.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(base_url=args.url, timeout=300) as client, out.open("w", encoding="utf-8") as f:
        for it in items:
            p = people[it["requester"]]
            agent = agent_for(it["targetTool"], agent_tools)
            body = {"message": it["utterance"], "agentId": agent, "today": it["referenceDate"], "variant": variant,
                    "requester": {"employeeId": p["id"], "unitId": p["unit_id"], "grade": p["grade"],
                                  "roles": ["employee"]}}
            if args.model:
                body["model"] = args.model
            started = time.time()
            r = client.post("/eval/tool-call", json=body)
            row = {"id": it["id"], "agentId": agent, "category": it["category"], "status": r.status_code,
                   "expected": [it["expected"], *it.get("alsoAcceptable", [])],
                   "result": r.json() if r.status_code == 200 else r.text[:300],
                   "wallMs": int((time.time() - started) * 1000)}
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    print(json.dumps(summary(rows), ensure_ascii=False, indent=1))


def first_action_matches(row: dict) -> bool:
    """도구 이름 또는 되묻기 모양만 봅니다(인자는 보지 않음)."""
    res = row["result"]
    for act in row["expected"]:
        if act["type"] == "call" and res["tool"] == act["tool"]:
            return True
        if act["type"] == "clarify" and res["tool"] is None and res["asked"]:
            return True
    return False


def summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == 200]
    calls = [r for r in ok if r["expected"][0]["type"] == "call"]
    clarify = [r for r in ok if r["expected"][0]["type"] == "clarify"]
    lat = sorted(r["result"]["latencyMs"] for r in ok)
    return {
        "items": len(rows),
        "http_ok": len(ok),
        "first_action_name_match": sum(first_action_matches(r) for r in ok),
        "call_items": len(calls),
        "call_items_no_tool": sum(r["result"]["tool"] is None for r in calls),
        "call_items_no_tool_asked": sum(r["result"]["tool"] is None and r["result"]["asked"] for r in calls),
        "clarify_items": len(clarify),
        "clarify_items_asked": sum(r["result"]["tool"] is None and r["result"]["asked"] for r in clarify),
        "latency_ms_p50": statistics.median(lat) if lat else None,
        "latency_ms_p95": lat[max(0, int(len(lat) * 0.95) - 1)] if lat else None,
        "egress": sorted({(r["result"]["model"]["egress"] or "") for r in ok}),
    }


if __name__ == "__main__":
    main()
