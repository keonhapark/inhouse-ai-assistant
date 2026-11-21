"""입구 라우터를 LLM·키워드·Laya·Jev로 나란히 비교합니다(#303). 채점·보고는 eval이 하고, 이 스크립트는 같은 입력을
각 방법에 넣어 고른 에이전트·확률·지연을 줄로 남기고 간단히 셉니다.

입력(확인 셋 원문은 쓰지 않음)
- eval 정상 셋(eval/scenarios/manufacturing/normal)의 첫 사용자 발화와 expectedAgent
- 2단계 라우터 시험 문장(eval_dev/router_cases.jsonl, tests/test_router_stage2.py의 CASES)
- 위 문장 중 "대결"이 든 것을 "대리 결재"로 바꾼 변형(같은 정답, 용어 영향 확인)

방법
- keyword: 등록부 keywords 기준선(모델 없음)
- llm: 지금 LLM 라우터(router.py). --llm-base-url·--llm-model로 OpenAI 호환 모델 서버를 바로 부름
- laya: 로컬 인코더(eval_dev/install_laya.sh로 설치)
- jev: 외부 API. 요청 문장이 외부로 나가므로 --allow-external을 줘야 돌고, 키는 TYPESAFE_API_KEY

    uv run python eval_dev/router_compare.py --methods keyword,laya --repeats 3 --out eval_dev/runs/<이름>.jsonl \\
        [--llm-base-url http://<ollama>:11434/v1 --llm-model qwen3.5:9b] [--allow-external]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.decision_router import Choice, JevChooser, LayaChooser, criteria
from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.router import Router

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACK = ROOT / "packs" / "manufacturing"
JEV_USD_PER_MTOK = 0.042  # docs.typesafe.ai 가격(입력 토큰만 과금), 2026-11-21 확인
TERM_VARIANTS = (("대결", "대리 결재"),)


def employees() -> dict[str, dict]:
    raw = json.loads((PACK / "fixtures" / "employees.json").read_text("utf-8"))
    return {e["id"]: e for e in (raw.get("employees", raw) if isinstance(raw, dict) else raw)}


def load_items(variants: bool = True) -> list[dict[str, Any]]:
    items = []
    for f in sorted((ROOT / "eval" / "scenarios" / "manufacturing" / "normal").glob("*.yaml")):
        d = yaml.safe_load(f.read_text("utf-8"))
        for s in d if isinstance(d, list) else d.get("scenarios", [d]):
            first = next(t["content"] for t in s["turns"] if t["role"] == "user")
            items.append({"id": s["id"], "source": "normal", "message": first, "expected": s["expectedAgent"],
                          "requester": s["requester"]})
    for i, line in enumerate((HERE / "router_cases.jsonl").read_text("utf-8").splitlines(), 1):
        c = json.loads(line)
        items.append({"id": f"stage2-{i:02d}", "source": c["source"], "message": c["message"],
                      "expected": c["expected"], "requester": "E0016"})
    if variants:
        extra = []
        for it in items:
            for old, new in TERM_VARIANTS:
                if old in it["message"]:
                    extra.append({**it, "id": f"{it['id']}~{new}", "source": f"{it['source']}+variant",
                                  "message": it["message"].replace(old, new)})
        items += extra
    return items


def requester(people: dict[str, dict], emp_id: str) -> Requester:
    p = people[emp_id]
    return Requester(p["id"], p["unit_id"], p["grade"], ("employee",))


class Methods:
    def __init__(self, reg: Registry, args: argparse.Namespace) -> None:
        self.reg = reg
        self.cands = criteria(reg)
        self.llm_router = None
        if args.llm_base_url:
            chat = ChatClient(LLMSettings(base_url=args.llm_base_url.rstrip("/"), model=args.llm_model, timeout_s=300))
            self.llm_router = Router(reg, chat)
        self.keyword = Router(reg, None)
        self.laya = LayaChooser(args.laya_model) if "laya" in args.methods else None
        self.jev = JevChooser(args.jev_model) if "jev" in args.methods else None

    def run(self, method: str, message: str, who: Requester) -> dict[str, Any]:
        started = time.perf_counter()
        if method in ("keyword", "llm"):
            router = self.keyword if method == "keyword" else self.llm_router
            if router is None:
                raise RuntimeError("llm 방법에는 --llm-base-url이 필요합니다")
            d = router.route(message, who, "keyword" if method == "keyword" else "llm")
            return {"agent": d.agent_id, "fallback": d.method == "fallback", "ambiguous": d.method == "fallback",
                    "confidence": d.confidence, "probabilities": {}, "audit": d.audit_reason,
                    "latencyMs": int((time.perf_counter() - started) * 1000), "model": None, "inputTokens": None}
        chooser = self.laya if method == "laya" else self.jev
        c: Choice = chooser.choose(message, self.cands)
        agent = c.agent_id if c.agent_id and self.reg.has(c.agent_id) else self.reg.fallback_agent_id
        return {"agent": agent, "fallback": c.agent_id is None, "ambiguous": c.review, "confidence": c.confidence,
                "probabilities": c.probabilities, "audit": None, "latencyMs": c.latency_ms, "model": c.model,
                "inputTokens": c.input_tokens}


def summary(rows: list[dict[str, Any]], reg: Registry, jev_threshold: float) -> dict[str, Any]:
    policy = {a.id: a.model_policy for a in reg.agents}
    out = {}
    for method in sorted({r["method"] for r in rows}):
        rs = [r for r in rows if r["method"] == method and r["error"] is None]
        for r in rs:
            if method == "jev":
                r["ambiguous"] = r["confidence"] is not None and r["confidence"] < jev_threshold
        leak = [r for r in rs if policy.get(r["expected"]) == "local_only"
                and policy.get(r["agent"]) == "external_allowed"]
        lat = sorted(r["latencyMs"] for r in rs)
        tokens = sum(r["inputTokens"] or 0 for r in rs)
        out[method] = {
            "runs": len(rs),
            "errors": sum(1 for r in rows if r["method"] == method and r["error"] is not None),
            "correct": sum(r["agent"] == r["expected"] for r in rs),
            "by_source": {s: [sum(r["agent"] == r["expected"] for r in rs if r["source"] == s),
                              sum(r["source"] == s for r in rs)] for s in sorted({r["source"] for r in rs})},
            # 인사·기밀(local_only) 요청을 외부 허용 에이전트로 보낸 수
            "local_to_external": len(leak),
            "ambiguous": sum(r["ambiguous"] for r in rs),
            # 애매할 때 로컬 강제(#308과 같은 처리)로 보냈다면 남는 유출
            "local_to_external_if_ambiguous_forced_local": sum(not r["ambiguous"] for r in leak),
            "confusion": dict(Counter(f"{r['expected']}->{r['agent']}" for r in rs if r["agent"] != r["expected"])),
            "latency_ms_p50": statistics.median(lat) if lat else None,
            "latency_ms_p95": lat[max(0, int(len(lat) * 0.95) - 1)] if lat else None,
            "input_tokens": tokens,
            "cost_usd": round(tokens / 1e6 * JEV_USD_PER_MTOK, 6) if method == "jev" else 0.0,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="keyword")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", type=int, default=2)
    ap.add_argument("--no-variants", action="store_true")
    ap.add_argument("--llm-base-url")
    ap.add_argument("--llm-model", default="qwen3.5:9b")
    ap.add_argument("--laya-model", default="convaiinnovations/laya-multilingual")
    ap.add_argument("--jev-model", default="jev-1.14.0")
    ap.add_argument("--jev-threshold", type=float, default=0.5)
    ap.add_argument("--allow-external", action="store_true")
    args = ap.parse_args()
    args.methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = set(args.methods) - {"keyword", "llm", "laya", "jev"}
    if unknown:
        raise SystemExit(f"모르는 방법: {', '.join(sorted(unknown))}")
    if "jev" in args.methods and not args.allow_external:
        raise SystemExit("jev는 요청 문장이 외부로 나갑니다. 지어낸 문장인지 확인하고 --allow-external을 주세요")
    reg = Registry.load(PACK, stage=args.stage)
    people = employees()
    methods = Methods(reg, args)
    items = load_items(not args.no_variants)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out.open("w", encoding="utf-8") as f:
        for rep in range(1, args.repeats + 1):
            for method in args.methods:
                for it in items:
                    try:
                        res = methods.run(method, it["message"], requester(people, it["requester"]))
                        row = {**it, "method": method, "repeat": rep, **res, "error": None}
                    except Exception as e:  # noqa: BLE001 - 비교용이라 오류도 줄로 남깁니다
                        row = {**it, "method": method, "repeat": rep, "agent": None, "fallback": False,
                               "ambiguous": False, "confidence": None, "probabilities": {}, "audit": None,
                               "latencyMs": None, "model": None, "inputTokens": None, "error": repr(e)[:300]}
                    rows.append(row)
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
    print(json.dumps(summary(rows, reg, args.jev_threshold), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
