"""야간 회귀(#464): 같은 개발 셋 부분집합을 돌린 두 실행을 (시나리오, 조건) 단위로 견줍니다.

결과가 바뀐 회차(예: 막음 → 사고), 조건별 사고·통과 수 변화, 두 실행의 시스템(하네스·스택 커밋)을 적습니다.
1회 실행끼리라 회차 간 변동이 섞이므로, 바뀐 회차는 원인 후보를 찾는 출발점으로만 씁니다.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from harness.runner import RunMeta, RunRow, load_run


def read_subset(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def latest_run(state: Path, exclude: Path | None = None) -> Path | None:
    """state 폴더에서 끝난 실행(.json) 중 가장 최근 것(이름순). exclude는 지금 실행."""
    runs = sorted(p for p in state.glob("*.json") if not p.name.endswith("-compare.json")
                  and (exclude is None or p.resolve() != exclude.resolve()))
    return runs[-1] if runs else None


def _stack(rows: list[RunRow]) -> str:
    """회차에 남은 스택 커밋(여럿이면 모두)."""
    seen = sorted({(r.stack_commit or "?")[:7] for r in rows})
    return ", ".join(seen) or "?"


def compare(prev: tuple[list[RunRow], RunMeta], cur: tuple[list[RunRow], RunMeta]) -> dict[str, Any]:
    (prows, pmeta), (crows, cmeta) = prev, cur
    p = {(r.scenario_id, r.condition): r for r in prows if r.repeat == 1}
    c = {(r.scenario_id, r.condition): r for r in crows if r.repeat == 1}
    changed = [{"scenario": k[0], "condition": k[1], "before": p[k].outcome, "after": c[k].outcome}
               for k in sorted(p.keys() & c.keys()) if p[k].outcome != c[k].outcome]

    def tally(rows: dict) -> dict[str, dict[str, int]]:
        out: dict[str, Counter] = {}
        for (sid, cond), r in rows.items():
            t = out.setdefault(cond, Counter())
            t["incident"] += r.outcome == "incident"
            t["passed"] += bool(r.passed)
            t["runs"] += 1
        return {k: dict(v) for k, v in out.items()}

    return {
        "before": {"started_at": pmeta.started_at, "commit": pmeta.commit, "stack": _stack(prows)},
        "after": {"started_at": cmeta.started_at, "commit": cmeta.commit, "stack": _stack(crows)},
        "only_before": sorted(f"{s} {c}" for s, c in p.keys() - c.keys()),
        "only_after": sorted(f"{s} {c}" for s, c in c.keys() - p.keys()),
        "changed": changed,
        "tally_before": tally(p), "tally_after": tally(c),
    }


def render(diff: dict[str, Any]) -> str:
    b, a = diff["before"], diff["after"]
    out = ["# 야간 회귀 비교", "",
           f"- 이전: {b['started_at']} 하네스 `{(b['commit'] or '')[:7]}` 스택 `{b['stack']}`",
           f"- 이번: {a['started_at']} 하네스 `{(a['commit'] or '')[:7]}` 스택 `{a['stack']}`",
           "- 1회 실행끼리라 회차 간 변동이 섞입니다. 바뀐 회차는 원인 후보를 찾는 출발점입니다.", "",
           "| 조건 | 사고(이전 → 이번) | 통과(이전 → 이번) |", "|---|---|---|"]
    for cond in sorted(set(diff["tally_before"]) | set(diff["tally_after"])):
        tb, ta = diff["tally_before"].get(cond, {}), diff["tally_after"].get(cond, {})
        out.append(f"| {cond} | {tb.get('incident', 0)} → {ta.get('incident', 0)} | "
                   f"{tb.get('passed', 0)}/{tb.get('runs', 0)} → {ta.get('passed', 0)}/{ta.get('runs', 0)} |")
    out += ["", f"## 결과가 바뀐 회차 {len(diff['changed'])}개", ""]
    if diff["changed"]:
        out += ["| 시나리오 | 조건 | 이전 | 이번 |", "|---|---|---|---|"]
        out += [f"| {x['scenario']} | {x['condition']} | {x['before']} | {x['after']} |" for x in diff["changed"]]
    else:
        out.append("없음")
    if diff["only_before"] or diff["only_after"]:
        out += ["", f"- 이전에만 있는 회차: {', '.join(diff['only_before']) or '없음'}",
                f"- 이번에만 있는 회차: {', '.join(diff['only_after']) or '없음'}"]
    return "\n".join(out) + "\n"


def compare_files(prev: Path, cur: Path) -> tuple[dict[str, Any], str]:
    diff = compare(load_run(prev), load_run(cur))
    return diff, render(diff)
