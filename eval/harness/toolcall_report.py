"""도구 호출 측정 집계와 보고서(#237). 채점은 harness/toolcall.py입니다."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from harness.report import proportion, rate_text, table
from harness.stats import pass_k, percentile
from harness.toolcall import CORRECT

OUTCOME_LABEL = {
    "correct": "정답", "alternative": "대안 정답", "confirm_then_proceed": "확인 후 진행",
    "wrong_tool": "다른 도구", "wrong_args": "인자 틀림", "unparsed_args": "인자를 못 읽음",
    "no_call_asked": "부르지 않고 되물음", "no_call_answered": "부르지 않고 답함",
    "called_instead_of_clarify": "되물어야 하는데 부름", "error": "실행 오류(분모 제외)",
}


def _scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["outcome"] != "error"]


def summarize(rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    scored = _scored(rows)

    def rate(sub: list[dict[str, Any]]) -> dict[str, Any]:
        return proportion(sum(r["passed"] for r in sub), len(sub))

    def by(key: str) -> list[dict[str, Any]]:
        groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for r in scored:
            groups[r[key]].append(r)
        return [{"key": k, "rate": rate(v)} for k, v in sorted(groups.items(), key=lambda x: str(x[0]))]

    runs_by_item: dict[str, list[bool]] = defaultdict(list)
    for r in sorted(scored, key=lambda r: r["repeat"]):
        runs_by_item[r["id"]].append(r["passed"])
    x, n = pass_k(runs_by_item, repeats)
    calls = [r for r in scored if r["tool"] is not None]
    lat = [r["latency_ms"] for r in scored if r["latency_ms"] is not None]
    return {
        "runs": len(rows), "scored": len(scored), "errors": len(rows) - len(scored),
        "accuracy": rate(scored),
        "passK": {"k": repeats, **proportion(x, n)},
        "byCategory": by("category"), "byTool": by("target_tool"), "byStage": by("stage"),
        # 외부 별칭을 요청해도 local_only 에이전트는 gateway가 로컬로 보내므로 위치별로 따로 봅니다
        "byLocation": by("location"),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "schemaValid": proportion(sum(bool(r["schema_valid"]) for r in calls), len(calls)),
        "asked": proportion(sum(bool(r["asked"]) for r in scored), len(scored)),
        "fabricated": sum(r["fabricated"] for r in scored),
        "latencyMs": {"p50": percentile(lat, 50), "p95": percentile(lat, 95)},
        "locations": dict(Counter(str(r["location"]) for r in scored)),
    }


def render(rows: list[dict[str, Any]], meta: dict[str, Any], title: str = "도구 호출 측정") -> str:
    s = summarize(rows, meta.get("repeats", 1))
    out = [f"# {title}", ""]
    out += table(["항목", "값"], [[k, str(v)] for k, v in meta.items() if k != "notes"])
    if meta.get("notes"):
        out += ["", *[f"- {n}" for n in meta["notes"]]]
    out += ["", "채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.", ""]
    out += ["## 정확도", ""]
    out += table(["구분", "맞음"], [
        ["전체(회차 단위)", rate_text(s["accuracy"])],
        [f"pass^{s['passK']['k']}(항목 단위)", rate_text(s["passK"])],
        ["도구를 부른 것 중 인자 스키마 유효", rate_text(s["schemaValid"])],
        ["되묻기 모양으로 답함", rate_text(s["asked"])],
    ])
    out += ["", f"- 지어낸 필수 인자(정답에 없고 발화에 없는 값): {s['fabricated']}개",
            f"- 지연(모델 호출): p50 {s['latencyMs']['p50'] or 0:.0f}ms, p95 {s['latencyMs']['p95'] or 0:.0f}ms",
            f"- 모델 위치: " + ", ".join(f"{k} {v}회차" for k, v in sorted(s["locations"].items()))]
    for name, key in (("모델 위치별", "byLocation"), ("유형별", "byCategory"), ("단계별", "byStage"),
                      ("도구별(targetTool)", "byTool")):
        out += ["", f"## {name}", ""]
        out += table(["구분", "맞음"], [[str(x["key"]), rate_text(x["rate"])] for x in s[key]])
    out += ["", "## 결과 분포(회차 단위)", ""]
    out += table(["결과", "회차"], [[OUTCOME_LABEL.get(o, o) + (" (맞음)" if o in CORRECT else ""), str(n)]
                                   for o, n in sorted(s["outcomes"].items(), key=lambda x: -x[1])])
    wrong = [r for r in rows if r["outcome"] in ("wrong_args",)]
    if wrong:
        out += ["", "## 인자 틀림", ""]
        out += table(["항목", "도구", "틀린 인자"], [[r["id"], str(r["tool"]), ", ".join(r["mismatched"])]
                                                   for r in wrong])
    return "\n".join(out) + "\n"
